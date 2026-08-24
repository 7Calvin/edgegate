"""
Regression tests for the IPsec failover local-id fix.

Bug: on a failover connection both FortiGate phase1 tunnels were exported with the
SAME `localid` (the shared `right_id`). Presenting one identity from two tunnels makes
each tunnel's INITIAL_CONTACT destroy the other on our strongSwan responder, so the
tunnel renegotiates from scratch every ~DPD interval (~100s observed in prod).

Fix: `IPsecConnection.failover_peer_ids()` derives a stable, DISTINCT id per path
(`<right_id>-01` / `-02`), used by BOTH the FortiGate export (each phase1 `localid`) and
`to_swanctl_secret()` (keys the same ids so both paths authenticate).

These are pure-method tests — no DB/session needed.
"""
from app.models.ipsec import IPsecConnection


def _conn(**overrides):
    base = dict(
        name="AWS_to_CWB",
        auth_method="psk",
        psk="s3cr3t",
        left_id="18.229.12.160",
        right_id="tocwbtunnel",
        right_ip="189.26.9.234",
        right_ip_backup="187.72.128.202",
    )
    base.update(overrides)
    return IPsecConnection(**base)


def test_failover_peer_ids_are_distinct():
    pri, bak = _conn().failover_peer_ids()
    assert pri != bak, "the two paths must present distinct IKE identities"
    assert (pri, bak) == ("tocwbtunnel-01", "tocwbtunnel-02")


def test_no_backup_returns_none():
    # Single link: no INITIAL_CONTACT war to avoid, so no derived ids.
    assert _conn(right_ip_backup=None).failover_peer_ids() is None
    assert _conn(right_ip_backup="").failover_peer_ids() is None


def test_falls_back_to_right_ip_when_id_blank():
    pri, bak = _conn(right_id="").failover_peer_ids()
    assert (pri, bak) == ("189.26.9.234-01", "189.26.9.234-02")


def test_secret_keys_both_derived_ids():
    secret = _conn().to_swanctl_secret()
    # Both derived ids must be present or the backup path fails "no shared key found".
    assert "tocwbtunnel-01" in secret
    assert "tocwbtunnel-02" in secret
    # The shared base id and both raw IPs stay keyed too (transition-friendly).
    assert "tocwbtunnel" in secret
    assert "189.26.9.234" in secret
    assert "187.72.128.202" in secret


def test_single_link_secret_has_no_suffixed_ids():
    secret = _conn(right_ip_backup=None).to_swanctl_secret()
    assert "-01" not in secret
    assert "-02" not in secret
