"""
Unit tests for the LDAP/AD group-based authentication logic.

ldap3 is fully mocked, so these run without any directory server. They lock down
the parts that are easy to get subtly wrong:
- the search filter enforces VPN-group membership with nested-group resolution;
- a user not in the group (empty search result) is denied;
- a wrong password (user rebind fails) is denied;
- a service-account bind failure is surfaced, not treated as success.
"""
from unittest.mock import MagicMock, patch

from app.services.ldap_service import LdapService, MATCHING_RULE_IN_CHAIN


CONF = {
    "server": "dc.empresa.com",
    "port": 389,
    "bind_dn": "CN=svc,DC=empresa,DC=com",
    "bind_password": "svc-pass",
    "search_base": "DC=empresa,DC=com",
    "user_attr": "sAMAccountName",
    "required_group_dn": "CN=VPN-Users,OU=Groups,DC=empresa,DC=com",
    "timeout": 5,
}


class FakeEntry:
    """Minimal stand-in for an ldap3 search Entry."""

    def __init__(self, dn, mail=None, display_name=None):
        self.entry_dn = dn
        self.mail = mail
        self.displayName = display_name

    def __contains__(self, attr):  # supports `"mail" in entry`
        return getattr(self, attr, None) is not None


def _conn(bind_result=True, entries=None):
    """Build a mock ldap3.Connection."""
    conn = MagicMock()
    conn.bind.return_value = bind_result
    conn.entries = entries if entries is not None else []
    conn.result = {"description": "invalidCredentials"}
    return conn


def test_success_returns_attrs_and_uses_nested_group_filter():
    service_conn = _conn(bind_result=True, entries=[
        FakeEntry("CN=Joao,OU=Users,DC=empresa,DC=com", mail="joao@empresa.com",
                  display_name="Joao Silva"),
    ])
    user_conn = _conn(bind_result=True)  # password verification succeeds

    with patch("ldap3.Server"), patch("ldap3.Connection", side_effect=[service_conn, user_conn]):
        ok, attrs, error = LdapService._authenticate_simple(CONF, "joao", "correct-pass")

    assert ok is True
    assert error is None
    assert attrs == {"email": "joao@empresa.com", "display_name": "Joao Silva"}

    # The membership check must use IN_CHAIN (nested groups) against the VPN group.
    used_filter = service_conn.search.call_args.kwargs["search_filter"]
    assert MATCHING_RULE_IN_CHAIN in used_filter
    assert CONF["required_group_dn"] in used_filter
    assert "sAMAccountName=joao" in used_filter


def test_user_not_in_group_is_denied():
    service_conn = _conn(bind_result=True, entries=[])  # no match => not in group / unknown

    with patch("ldap3.Server"), patch("ldap3.Connection", side_effect=[service_conn]):
        ok, attrs, error = LdapService._authenticate_simple(CONF, "joao", "correct-pass")

    assert ok is False
    assert attrs is None
    assert "VPN group" in error


def test_wrong_password_is_denied():
    service_conn = _conn(bind_result=True, entries=[
        FakeEntry("CN=Joao,DC=empresa,DC=com"),
    ])
    user_conn = _conn(bind_result=False)  # rebind as user fails => bad password

    with patch("ldap3.Server"), patch("ldap3.Connection", side_effect=[service_conn, user_conn]):
        ok, attrs, error = LdapService._authenticate_simple(CONF, "joao", "wrong-pass")

    assert ok is False
    assert error == "Invalid username or password"


def test_service_bind_failure_is_surfaced():
    service_conn = _conn(bind_result=False)

    with patch("ldap3.Server"), patch("ldap3.Connection", side_effect=[service_conn]):
        ok, attrs, error = LdapService._authenticate_simple(CONF, "joao", "pass")

    assert ok is False
    assert "service account" in error


def test_username_is_escaped_against_ldap_injection():
    service_conn = _conn(bind_result=True, entries=[])

    with patch("ldap3.Server"), patch("ldap3.Connection", side_effect=[service_conn]):
        LdapService._authenticate_simple(CONF, "ev*il)(uid=*", "pass")

    used_filter = service_conn.search.call_args.kwargs["search_filter"]
    # Raw injection metacharacters must not appear unescaped in the filter.
    assert "ev*il)(uid=*" not in used_filter
    assert r"\2a" in used_filter.lower()  # '*' escaped (ldap3 emits \2a)
