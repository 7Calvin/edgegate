#!/usr/bin/env python3
"""
IPsec Agent - runs on the HOST to drive strongSwan via **swanctl/vici**.

Provides a small REST API the backend uses to control IPsec tunnels. Migrated
from the legacy stroke/`ipsec` CLI to swanctl: config lives in
/etc/swanctl/conf.d/, loaded with `swanctl --load-all`; status comes from
`swanctl --list-sas`. Endpoint NAMES are kept stable so the backend mapping is
unchanged; only the implementation underneath switched to swanctl.
"""
import os
import glob
import time
import ipaddress
import threading
import subprocess
import logging
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AUTH_TOKEN = os.environ.get('IPSEC_AGENT_TOKEN', 'changeme-ipsec-token')
SWANCTL_DIR = os.environ.get('SWANCTL_CONFD', '/etc/swanctl/conf.d')
MANAGED_FILE = os.path.join(SWANCTL_DIR, 'edgegate.conf')
STRONGSWAN_SERVICE = os.environ.get('STRONGSWAN_SERVICE', 'strongswan')


def check_auth():
    return request.headers.get('Authorization', '') == f'Bearer {AUTH_TOKEN}'


def _strip_plugin_noise(text: str) -> str:
    """swanctl's CLI prints 'plugin 'X' failed to load' lines to stderr for
    optional plugins that aren't installed. They're cosmetic — drop them."""
    if not text:
        return text
    return "\n".join(
        l for l in text.splitlines()
        if "failed to load" not in l or "plugin" not in l
    ).strip()


def run_swanctl(args):
    """Run a swanctl command and return a normalized result dict."""
    try:
        cmd = ['swanctl'] + args
        logger.info("Running: %s", ' '.join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        stdout = r.stdout or ''
        stderr = _strip_plugin_noise(r.stderr or '')
        return {
            'success': r.returncode == 0,
            'stdout': stdout,
            'stderr': stderr,
            'output': (stdout + ('\n' + stderr if stderr else '')).strip(),
            'returncode': r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'output': 'Command timed out', 'returncode': -1}
    except FileNotFoundError:
        return {'success': False, 'output': 'swanctl command not found', 'returncode': -1}
    except Exception as e:  # noqa: BLE001
        return {'success': False, 'output': str(e), 'returncode': -1}


@app.route('/health', methods=['GET'])
def health():
    r = run_swanctl(['--stats'])
    return jsonify({
        'status': 'healthy' if r['success'] else 'unhealthy',
        'ipsec_installed': r['success'],
        'version': (r['stdout'].splitlines() or [None])[0] if r['success'] else None,
    })


@app.route('/version', methods=['GET'])
def version():
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    r = run_swanctl(['--version'])
    return jsonify(r)


@app.route('/status', methods=['GET'])
def status():
    """Live SAs (swanctl --list-sas). Backend parses this text."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(run_swanctl(['--list-sas']))


@app.route('/status/<connection_name>', methods=['GET'])
def status_connection(connection_name):
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(run_swanctl(['--list-sas', '--ike', connection_name]))


@app.route('/up/<connection_name>', methods=['POST'])
def connection_up(connection_name):
    """Initiate a connection (its IKE SA + configured children).

    --timeout caps how long swanctl waits for establishment so an unreachable
    peer can't block the worker (and cascade timeouts onto other requests)."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(run_swanctl(['--initiate', '--ike', connection_name, '--timeout', '8']))


@app.route('/down/<connection_name>', methods=['POST'])
def connection_down(connection_name):
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(run_swanctl(['--terminate', '--ike', connection_name]))


@app.route('/reload', methods=['POST'])
def reload_config():
    """Reconcile loaded config with /etc/swanctl (adds/updates AND unloads
    removed connections/secrets)."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(run_swanctl(['--load-all', '--noprompt']))


@app.route('/restart', methods=['POST'])
def restart_ipsec():
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        r = subprocess.run(['systemctl', 'restart', STRONGSWAN_SERVICE],
                           capture_output=True, text=True, timeout=60)
        return jsonify({'success': r.returncode == 0,
                        'output': (r.stdout + r.stderr).strip(),
                        'returncode': r.returncode})
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'output': str(e), 'returncode': -1})


@app.route('/config/write', methods=['POST'])
def write_config():
    """Write the managed swanctl config. The backend regenerates the FULL config
    for all connections, so we own conf.d: clear other *.conf, write edgegate.conf."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    conf = data.get('swanctl_conf')
    if conf is None:
        return jsonify({'swanctl_conf': {'success': False, 'error': 'no swanctl_conf provided'}}), 400

    try:
        os.makedirs(SWANCTL_DIR, exist_ok=True)
        # We are the sole manager of conf.d — remove stale/hand-made files so
        # `swanctl --load-all` doesn't load duplicate/leftover connections.
        for f in glob.glob(os.path.join(SWANCTL_DIR, '*.conf')):
            if os.path.abspath(f) != os.path.abspath(MANAGED_FILE):
                try:
                    os.remove(f)
                except OSError:
                    pass
        with open(MANAGED_FILE, 'w') as fh:
            fh.write(conf)
        os.chmod(MANAGED_FILE, 0o600)
        logger.info("Wrote %s", MANAGED_FILE)
        return jsonify({'swanctl_conf': {'success': True}})
    except Exception as e:  # noqa: BLE001
        return jsonify({'swanctl_conf': {'success': False, 'error': str(e)}}), 500


@app.route('/config/read', methods=['GET'])
def read_config():
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    result = {}
    try:
        with open(MANAGED_FILE) as fh:
            result['swanctl_conf'] = fh.read()
    except Exception as e:  # noqa: BLE001
        result['swanctl_conf_error'] = str(e)
    return jsonify(result)


@app.route('/statusall', methods=['GET'])
def statusall():
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify(run_swanctl(['--list-sas']))


@app.route('/logs', methods=['GET'])
def get_logs():
    """Recent charon logs from the strongswan (swanctl) systemd unit."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401

    lines = request.args.get('lines', '100')
    connection = request.args.get('connection', None)
    try:
        max_lines = int(lines)
        r = subprocess.run(
            ['journalctl', '-u', STRONGSWAN_SERVICE, '--no-pager',
             '-n', str(max_lines * 3 if connection else max_lines)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            log_lines = r.stdout.strip().split('\n')
            if connection:
                cl = connection.lower()
                log_lines = [l for l in log_lines
                             if cl in l.lower() or 'error' in l.lower() or 'failed' in l.lower()]
                source = f'journalctl (filtered: {connection})'
            else:
                source = 'journalctl'
            out = '\n'.join(log_lines[-max_lines:])
            if out.strip():
                return jsonify({'success': True, 'logs': out, 'source': source,
                                'connection': connection})
        return jsonify({'success': True,
                        'logs': f'No logs found{" for " + connection if connection else ""}',
                        'source': None, 'connection': connection})
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'logs': 'Timeout reading logs', 'source': None})
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'logs': str(e), 'source': None})


def _valid_ip(ip):
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


_BOTH_CHAINS = (('OUTPUT', '-d'), ('INPUT', '-s'))
_INBOUND_ONLY = (('INPUT', '-s'),)


def _peer_iptables(action, ip, chains=_BOTH_CHAINS):
    """action 'I' (insert/block) or 'D' (delete/unblock).

    Default blocks both directions. For a DPD-driven failover *test* pass
    `chains=_INBOUND_ONLY`: an OUTPUT DROP makes charon's own DPD probe fail to send
    with EPERM ("Operation not permitted"), which charon treats as a transient local
    error and never counts as dead-peer — so it never fails over. Blocking only INBOUND
    lets the DPD probe go out and simply get no reply, which is what trips DPD."""
    for chain, flag in chains:
        subprocess.run(['iptables', f'-{action}', chain, flag, ip, '-j', 'DROP'],
                       capture_output=True, text=True, timeout=10)


@app.route('/block-peer/<ip>', methods=['POST'])
def block_peer(ip):
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    if not _valid_ip(ip):
        return jsonify({'success': False, 'error': 'invalid ip'}), 400
    _peer_iptables('I', ip)
    logger.info("Blocked peer %s", ip)
    return jsonify({'success': True, 'blocked': ip})


@app.route('/unblock-peer/<ip>', methods=['POST'])
def unblock_peer(ip):
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    if not _valid_ip(ip):
        return jsonify({'success': False, 'error': 'invalid ip'}), 400
    for _ in range(4):  # clear any duplicate rules
        _peer_iptables('D', ip)
    logger.info("Unblocked peer %s", ip)
    return jsonify({'success': True, 'unblocked': ip})


@app.route('/test-failover-block/<ip>', methods=['POST'])
def test_failover_block(ip):
    """Block a peer IP to trip a failover, then AUTO-UNBLOCK after a delay so the test
    can never leave a path blocked. Returns immediately."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    if not _valid_ip(ip):
        return jsonify({'success': False, 'error': 'invalid ip'}), 400
    restore = int(os.environ.get('FAILOVER_TEST_RESTORE_SECONDS', '120'))
    # INBOUND-only: block the peer's replies so charon's DPD probe goes out, gets no
    # answer, and trips dead-peer detection -> failover. (An OUTPUT DROP would make the
    # probe fail to send with EPERM, which never counts as dead-peer.)
    _peer_iptables('I', ip, chains=_INBOUND_ONLY)
    logger.info("Failover test: blocked inbound from %s, auto-restore in %ds", ip, restore)

    def _restore():
        time.sleep(restore)
        for _ in range(4):
            _peer_iptables('D', ip, chains=_INBOUND_ONLY)
        logger.info("Failover test: auto-unblocked %s", ip)

    threading.Thread(target=_restore, daemon=True).start()
    return jsonify({'success': True, 'blocked': ip, 'auto_restore_seconds': restore})


@app.route('/active-remote', methods=['POST'])
def active_remote():
    """Report the remote endpoint currently carrying OUTBOUND traffic, read from the
    kernel XFRM policy (`dir out` -> `tmpl ... dst <ip>`). With two overlapping failover
    SAs (same reqid/TS) the outbound policy points at the last-installed SA — this is the
    ONLY reliable signal of which path is active; swanctl list-sas can't disambiguate and
    prefer_backup only affects initiate order, not the installed policy."""
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        out = subprocess.run(['ip', 'xfrm', 'policy'],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(e)}), 500
    remotes, in_out = [], False
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith('dir out'):
            in_out = True
        elif s.startswith('dir '):
            in_out = False
        elif in_out and s.startswith('tmpl ') and ' dst ' in s:
            parts = s.split()
            remotes.append(parts[parts.index('dst') + 1])
    return jsonify({'success': True, 'active': remotes[0] if remotes else None,
                    'all': remotes})


if __name__ == '__main__':
    port = int(os.environ.get('IPSEC_AGENT_PORT', 8101))
    logger.info("Starting IPsec Agent (swanctl) on port %d", port)
    app.run(host='0.0.0.0', port=port)
