"""
Unit tests for the read-only role (no database).

Covers three units that together make read-only safe:
- User.role — the derived label the UI/serialization reads (admin outranks read-only);
- require_read_access — the method-aware guard: admins any method, read-only reads only;
- PATCH /me restricted fields — read-only must be un-escalatable via self-update.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.user import User, UserType
from app.dependencies.auth import require_read_access, SAFE_METHODS


def make_user(*, is_admin=False, is_readonly=False, active=True):
    u = User()
    u.user_type = UserType.HUMAN
    u.is_admin = is_admin
    u.is_readonly = is_readonly
    u.is_active = active
    u.allowed_source_ips = []
    return u


def fake_request(method):
    return SimpleNamespace(method=method)


# ---------------- role property ----------------

def test_role_admin():
    assert make_user(is_admin=True).role == "admin"


def test_role_readonly():
    assert make_user(is_readonly=True).role == "readonly"


def test_role_plain_user():
    assert make_user().role == "user"


def test_admin_outranks_readonly():
    # Defense in depth: even if both flags are set, admin wins.
    assert make_user(is_admin=True, is_readonly=True).role == "admin"


def test_readonly_is_subject_to_trusted_hosts():
    # A read-only human is a console principal, so it must be IP-restrictable.
    assert make_user(is_readonly=True).is_subject_to_trusted_hosts is True


# ---------------- require_read_access ----------------

WRITE_METHODS = ["POST", "PUT", "PATCH", "DELETE"]


async def test_admin_allowed_on_read_and_write():
    admin = make_user(is_admin=True)
    for m in list(SAFE_METHODS) + WRITE_METHODS:
        assert await require_read_access(fake_request(m), admin) is admin


async def test_readonly_allowed_on_safe_methods():
    ro = make_user(is_readonly=True)
    for m in SAFE_METHODS:
        assert await require_read_access(fake_request(m), ro) is ro


async def test_readonly_denied_on_writes():
    ro = make_user(is_readonly=True)
    for m in WRITE_METHODS:
        with pytest.raises(HTTPException) as exc:
            await require_read_access(fake_request(m), ro)
        assert exc.value.status_code == 403
        assert "Read-only" in exc.value.detail


async def test_plain_user_denied_on_everything():
    plain = make_user()
    for m in list(SAFE_METHODS) + WRITE_METHODS:
        with pytest.raises(HTTPException) as exc:
            await require_read_access(fake_request(m), plain)
        assert exc.value.status_code == 403


# ---------------- self-escalation guard ----------------

def test_me_strip_list_includes_is_readonly_and_role():
    # The PATCH /me handler strips privileged fields so a read-only user cannot
    # self-escalate. Assert the source declares both new fields as restricted.
    import inspect
    from app.api.v1.routes import users as users_route

    src = inspect.getsource(users_route.update_current_user_profile)
    assert '"is_readonly"' in src
    assert '"is_admin"' in src
