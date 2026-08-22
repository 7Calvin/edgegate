"""
Unit tests for the Trusted Hosts feature (FortiOS-style source-IP allowlist).

Two units, no database:
- User.is_source_ip_trusted / is_subject_to_trusted_hosts — who is restricted and
  whether a given source IP is allowed (IPv4/IPv6, CIDR, empty=allow, None=deny);
- get_trusted_client_ip — the anti-spoof resolution that makes the whole feature
  trustworthy: a client-supplied X-Forwarded-For must never override the real IP.
"""
from types import SimpleNamespace

from app.models.user import User, UserType
from app.core.net import get_trusted_client_ip


def make_user(*, is_admin=False, service=False, allowed=None):
    u = User()
    u.user_type = UserType.SERVICE if service else UserType.HUMAN
    u.is_admin = is_admin
    u.allowed_source_ips = allowed or []
    return u


def fake_request(xff=None, peer="10.0.0.9"):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=peer) if peer else None,
    )


# ---------------- subject scoping ----------------

def test_plain_vpn_user_is_exempt():
    user = make_user(allowed=["203.0.113.0/24"])
    assert user.is_subject_to_trusted_hosts is False
    # Exempt even from an IP the list would reject.
    assert user.is_source_ip_trusted("8.8.8.8") is True


def test_admin_and_service_are_subject():
    assert make_user(is_admin=True).is_subject_to_trusted_hosts is True
    assert make_user(service=True).is_subject_to_trusted_hosts is True


# ---------------- membership ----------------

def test_empty_list_means_no_restriction():
    assert make_user(is_admin=True, allowed=[]).is_source_ip_trusted("8.8.8.8") is True


def test_cidr_match_and_miss():
    user = make_user(is_admin=True, allowed=["203.0.113.0/24"])
    assert user.is_source_ip_trusted("203.0.113.5") is True
    assert user.is_source_ip_trusted("203.0.114.5") is False


def test_bare_host_entry():
    user = make_user(service=True, allowed=["203.0.113.5"])
    assert user.is_source_ip_trusted("203.0.113.5") is True
    assert user.is_source_ip_trusted("203.0.113.6") is False


def test_ipv6_cidr():
    user = make_user(is_admin=True, allowed=["2001:db8::/48"])
    assert user.is_source_ip_trusted("2001:db8:0:1::5") is True
    assert user.is_source_ip_trusted("2001:db9::1") is False


def test_restricted_account_denies_unknown_ip():
    # Fail closed: a restricted account whose IP can't be resolved is denied.
    assert make_user(is_admin=True, allowed=["203.0.113.0/24"]).is_source_ip_trusted(None) is False


def test_garbage_ip_denied():
    assert make_user(is_admin=True, allowed=["203.0.113.0/24"]).is_source_ip_trusted("not-an-ip") is False


# ---------------- anti-spoof IP resolution (TRUSTED_PROXY_COUNT=1) ----------------

def test_direct_client_ip():
    assert get_trusted_client_ip(fake_request(xff="1.2.3.4"), trusted_hops=1) == "1.2.3.4"


def test_client_forged_xff_is_ignored():
    # Attacker prepends a trusted-looking IP; Traefik appends the real one on the
    # right. We must return the rightmost (real) entry, not the forged left one.
    req = fake_request(xff="203.0.113.0, 1.2.3.4")
    assert get_trusted_client_ip(req, trusted_hops=1) == "1.2.3.4"


def test_falls_back_to_peer_without_xff():
    assert get_trusted_client_ip(fake_request(xff=None, peer="10.0.0.9"), trusted_hops=1) == "10.0.0.9"


def test_hops_zero_ignores_xff():
    assert get_trusted_client_ip(fake_request(xff="9.9.9.9", peer="10.0.0.9"), trusted_hops=0) == "10.0.0.9"


def test_two_trusted_hops():
    req = fake_request(xff="client, proxyB, proxyA")
    assert get_trusted_client_ip(req, trusted_hops=2) == "proxyB"


# ---------------- response serialization (regression) ----------------

def test_response_coerces_ipaddress_objects_to_str():
    # asyncpg decodes INET into ipaddress objects; the response schema must coerce
    # them to strings or the whole list endpoint 500s for any user with a host set.
    import ipaddress
    import uuid
    from datetime import datetime
    from app.schemas.user import UserListResponse

    r = UserListResponse.model_validate({
        "id": uuid.uuid4(),
        "username": "x",
        "email": None,
        "user_type": UserType.HUMAN,
        "is_active": True,
        "is_admin": True,
        "mfa_enabled": False,
        "mfa_required": False,
        "last_login_at": None,
        "created_at": datetime.utcnow(),
        "allowed_source_ips": [ipaddress.ip_address("1.1.1.1"), ipaddress.ip_network("10.0.0.0/24")],
    })
    assert r.allowed_source_ips == ["1.1.1.1", "10.0.0.0/24"]
    assert all(isinstance(x, str) for x in r.allowed_source_ips)
