"""
Unit tests for the hybrid (local + AD) authentication decision in AuthService.

The async DB session is mocked and LdapService.authenticate is patched, so these
run with no database and no directory server. They cover exactly the behaviours we
promised the user:

- a local user still authenticates with AD enabled (AD is never consulted);
- a local user with a wrong password is NOT silently retried against AD;
- an AD user in the VPN group succeeds and is JIT-provisioned as a shadow user;
- an AD user out of the group is denied (no shadow user created);
- with AD disabled, an unknown user gets a generic failure (no info leak).
"""
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.auth_service import AuthService
from app.services.ldap_service import LdapService
from app.models.user import User, UserType, AuthSource
from app.core.security import hash_password


def make_db(existing_user):
    """Mock AsyncSession whose SELECT resolves to `existing_user`."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_user
    result.scalar_one.return_value = existing_user

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    return db


def local_user(username="joao", password="secret"):
    return User(
        username=username,
        auth_source=AuthSource.LOCAL,
        user_type=UserType.HUMAN,
        password_hash=hash_password(password),
        is_active=True,
        mfa_required=False,
        mfa_enabled=False,
    )


async def test_local_user_authenticates_with_ad_enabled():
    db = make_db(local_user())
    svc = AuthService(db)

    with patch.object(LdapService, "authenticate", new=AsyncMock()) as ldap_auth:
        user, error, mfa_pending = await svc.authenticate_user("joao", "secret")

    assert error is None
    assert mfa_pending is False
    assert user is not None and user.username == "joao"
    ldap_auth.assert_not_called()  # local account never touches AD


async def test_local_user_wrong_password_does_not_fall_through_to_ad():
    db = make_db(local_user(password="right-pass"))
    svc = AuthService(db)

    with patch.object(LdapService, "authenticate", new=AsyncMock()) as ldap_auth:
        user, error, _ = await svc.authenticate_user("joao", "wrong-pass")

    assert user is None
    assert error == "Invalid username or password"
    ldap_auth.assert_not_called()


async def test_ad_user_in_group_succeeds_and_is_provisioned():
    db = make_db(None)  # unknown locally
    svc = AuthService(db)

    ad_ok = AsyncMock(return_value=(True, {"email": "joao@empresa.com"}, None))
    with patch.object(LdapService, "authenticate", new=ad_ok):
        user, error, mfa_pending = await svc.authenticate_user("Joao", "ad-pass")

    assert error is None
    assert mfa_pending is False
    assert user.username == "joao"              # JIT provisioning lowercases
    assert user.auth_source == AuthSource.AD
    assert user.email == "joao@empresa.com"
    db.add.assert_called_once()                 # shadow user created


async def test_ad_user_out_of_group_is_denied_and_not_provisioned():
    db = make_db(None)
    svc = AuthService(db)

    denied = AsyncMock(return_value=(False, None, "User not found or not a member of the VPN group"))
    with patch.object(LdapService, "authenticate", new=denied):
        user, error, _ = await svc.authenticate_user("joao", "ad-pass")

    assert user is None
    assert "VPN group" in error
    db.add.assert_not_called()                  # no shadow user for a denied login


async def test_unknown_user_with_ad_disabled_gets_generic_error():
    db = make_db(None)
    svc = AuthService(db)

    disabled = AsyncMock(return_value=(False, None, "LDAP is not enabled"))
    with patch.object(LdapService, "authenticate", new=disabled):
        user, error, _ = await svc.authenticate_user("ghost", "whatever")

    assert user is None
    assert error == "Invalid username or password"  # no hint that AD exists
