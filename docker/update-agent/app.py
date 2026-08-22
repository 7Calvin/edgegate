#!/usr/bin/env python3
"""
Update Agent - runs on the HOST (systemd), orchestrates full-system updates.

It exists as a host service (not a container) on purpose: the update rebuilds and
restarts the backend/frontend containers, so whatever drives the update must live
outside the docker-compose lifecycle or it would kill itself mid-update.

Responsibilities:
  * report the running version + git details        (GET  /version)
  * check upstream for a newer version              (GET  /latest)
  * kick off update.sh detached, survives agent restart (POST /update)
  * expose live progress from status.json + log     (GET  /status)
  * regenerate OpenVPN server.conf preserving certs (POST /openvpn/regenerate-config)

Mirrors the auth/shape of the existing ipsec-agent.
"""
import os
import json
import subprocess
import logging
from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AUTH_TOKEN = os.environ.get("UPDATE_AGENT_TOKEN", "changeme-update-token")

INSTALL_DIR = os.environ.get("INSTALL_DIR", "/opt/edgegate")
REPO_DIR = os.environ.get("REPO_DIR", os.path.join(INSTALL_DIR, "repo"))
REPO_SUBDIR = os.environ.get("REPO_SUBDIR", "")  # empty = app at repo root
GIT_REMOTE = os.environ.get("GIT_REMOTE", "https://github.com/7Calvin/edgegate.git")
GIT_BRANCH = os.environ.get("GIT_BRANCH", "main")
STATE_DIR = os.environ.get("STATE_DIR", "/var/lib/edgegate-update")
STATUS_FILE = os.path.join(STATE_DIR, "status.json")
LOG_FILE = os.path.join(STATE_DIR, "update.log")
UPDATE_SCRIPT = os.environ.get(
    "UPDATE_SCRIPT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "update.sh")
)
RESTORE_SCRIPT = os.environ.get(
    "RESTORE_SCRIPT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "restore.sh")
)
OPENVPN_CONTAINER = os.environ.get("OPENVPN_CONTAINER", "edgegate-openvpn")

os.makedirs(STATE_DIR, exist_ok=True)


def check_auth():
    return request.headers.get("Authorization", "") == f"Bearer {AUTH_TOKEN}"


def _git(*args, cwd=REPO_DIR):
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=120
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


def read_status():
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"state": "idle", "pct": 0, "message": "No update has run yet"}


def log_tail(n=80):
    try:
        with open(LOG_FILE) as f:
            return f.readlines()[-n:]
    except OSError:
        return []


def current_version():
    for p in (os.path.join(INSTALL_DIR, "VERSION"),
              os.path.join(REPO_DIR, REPO_SUBDIR, "VERSION")):
        try:
            with open(p) as f:
                v = f.read().strip()
                if v:
                    return v
        except OSError:
            continue
    return None


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "agent": "update-agent",
        "time": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/version", methods=["GET"])
def version():
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401
    sha = _git("rev-parse", "--short", "HEAD")[1] or None
    build_date = _git("show", "-s", "--format=%cI", "HEAD")[1] or None
    return jsonify({
        "current": current_version(),
        "git_sha": sha,
        "build_date": build_date,
        "branch": GIT_BRANCH,
    })


@app.route("/latest", methods=["GET"])
def latest():
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401

    # Lazily clone the repo on first check so "Verificar atualizações" works
    # immediately instead of requiring a first update to bootstrap the checkout.
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        try:
            r = subprocess.run(
                ["git", "clone", "--no-checkout", GIT_REMOTE, REPO_DIR],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode != 0:
                return jsonify({
                    "error": f"could not clone source repo: {r.stderr.strip()}",
                    "update_available": False,
                }), 200
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": f"clone failed: {e}", "update_available": False}), 200

    code, _, err = _git("fetch", "--tags", "--prune", "origin")
    if code != 0:
        return jsonify({"error": f"git fetch failed: {err}", "update_available": False}), 200

    # Compare the INSTALLED version (the VERSION file the running system uses)
    # against the version at the latest available ref. The repo checkout's HEAD
    # is NOT a reliable proxy for what's installed (a fresh clone sits at the
    # newest commit), so we read the VERSION file out of the target ref instead.
    installed = current_version()
    latest_tag = _git("tag", "-l", "v*", "--sort=-v:refname")[1].splitlines()
    latest_tag = latest_tag[0] if latest_tag else None

    if latest_tag:
        target = latest_tag
    else:
        target = f"origin/{GIT_BRANCH}"

    ver_path = f"{REPO_SUBDIR}/VERSION" if REPO_SUBDIR else "VERSION"
    rc, latest_ver, _ = _git("show", f"{target}:{ver_path}")
    latest_ver = latest_ver.strip() if rc == 0 and latest_ver.strip() else None

    # Different version at the target ref => an update is available.
    update_available = bool(latest_ver) and bool(installed) and latest_ver != installed

    return jsonify({
        "current": installed,
        "latest": latest_ver or latest_tag,
        "latest_tag": latest_tag,
        "target": target,
        "update_available": update_available,
    })


@app.route("/tags", methods=["GET"])
def tags():
    """List available version tags (newest first) so the UI can target a specific
    version — including OLDER tags for a rollback. Also returns the installed
    version so the UI can mark which tags are ahead (upgrade) vs behind (rollback)."""
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401

    # Lazily clone (no checkout) so this works before the first update, like /latest.
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        try:
            r = subprocess.run(
                ["git", "clone", "--no-checkout", GIT_REMOTE, REPO_DIR],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode != 0:
                return jsonify({"error": f"could not clone source repo: {r.stderr.strip()}",
                                "tags": []}), 200
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": f"clone failed: {e}", "tags": []}), 200

    code, _, err = _git("fetch", "--tags", "--prune", "origin")
    if code != 0:
        return jsonify({"error": f"git fetch failed: {err}", "tags": []}), 200

    tag_list = [t for t in _git("tag", "-l", "v*", "--sort=-v:refname")[1].splitlines() if t.strip()]
    return jsonify({"current": current_version(), "tags": tag_list})


@app.route("/update", methods=["POST"])
def update():
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401

    status = read_status()
    if status.get("state") == "running":
        return jsonify({"error": "An update is already in progress"}), 409

    body = request.get_json(silent=True) or {}
    ref = (body.get("ref") or "").strip()
    do_backup = "1" if body.get("backup", True) else "0"
    run_migrations = "1" if body.get("run_migrations", True) else "0"
    job_id = "job-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    env = dict(os.environ)
    env.update({
        "UPDATE_REF": ref,
        "DO_BACKUP": do_backup,
        "RUN_MIGRATIONS": run_migrations,
        "JOB_ID": job_id,
    })

    # Detached so it survives even if this agent is restarted mid-update.
    try:
        subprocess.Popen(
            ["bash", UPDATE_SCRIPT],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"failed to launch updater: {e}"}), 500

    return jsonify({"job_id": job_id, "state": "running", "ref": ref or "latest"}), 202


@app.route("/restore", methods=["POST"])
def restore():
    """Restore a backup that has already been placed on the host (path in the body).
    Runs restore.sh detached — it is destructive (drops the DB schema) and recreates
    the stack, so it must live outside the containers, like update.sh."""
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401

    status = read_status()
    if status.get("state") == "running":
        return jsonify({"error": "An operation is already in progress"}), 409

    body = request.get_json(silent=True) or {}
    path = (body.get("path") or "").strip()
    if not path or not os.path.isfile(path):
        return jsonify({"error": "backup file not found on host"}), 400

    job_id = "restore-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    env = dict(os.environ)
    env.update({"RESTORE_FILE": path, "JOB_ID": job_id})

    try:
        subprocess.Popen(
            ["bash", RESTORE_SCRIPT],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"failed to launch restore: {e}"}), 500

    return jsonify({"job_id": job_id, "state": "running"}), 202


@app.route("/status", methods=["GET"])
def status():
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401
    data = read_status()
    data["log_tail"] = log_tail(int(request.args.get("lines", 80)))
    return jsonify(data)


@app.route("/openvpn/regenerate-config", methods=["POST"])
def regenerate_openvpn_config():
    """Rebuild server.conf from the image template, PRESERVING all PKI/certs.
    Done by removing server.conf and restarting OpenVPN — start.sh regenerates
    it while its `if [ ! -f ca.crt ]` guard keeps the existing PKI intact."""
    if not check_auth():
        return jsonify({"error": "unauthorized"}), 401
    try:
        subprocess.run(
            ["docker", "exec", OPENVPN_CONTAINER, "sh", "-c",
             "cp /etc/openvpn/server.conf /etc/openvpn/server.conf.bak 2>/dev/null; "
             "rm -f /etc/openvpn/server.conf"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        subprocess.run(["docker", "restart", OPENVPN_CONTAINER],
                       check=True, capture_output=True, text=True, timeout=60)
        return jsonify({"success": True, "message": "server.conf regenerated; PKI preserved"})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "error": e.stderr or str(e)}), 500
    except Exception as e:  # noqa: BLE001
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("UPDATE_AGENT_PORT", "8102"))
    app.run(host="0.0.0.0", port=port)
