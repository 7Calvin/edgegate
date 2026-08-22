"""
LDAP / Active Directory service.

Authenticates VPN users against Active Directory and enforces VPN-group membership
(nested groups resolved via LDAP_MATCHING_RULE_IN_CHAIN). Two bind mechanisms, over
the same plain 389 port (no LDAPS):

- NTLM (default): a *signed* bind. Modern AD rejects unsigned simple binds over
  cleartext ("strongerAuthRequired" — integrity required). NTLM signs the session,
  so it works on 389 without TLS and without changing the DC — the same mechanism
  appliances like FortiGate use. Implemented with msldap (async, pure-Python).
- Simple: classic unsigned simple bind, for directories that still allow it.
  Implemented with ldap3 (blocking, run in a threadpool).

Config is read from the single `ldap_settings` row (managed from the admin UI).
"""
from typing import Optional, Tuple
from urllib.parse import quote
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.ldap_settings import LdapSettings

logger = logging.getLogger(__name__)

# Active Directory "member of, recursively" matching rule OID — lets a user in a
# nested group (VPN-Users -> Financeiro -> user) satisfy the group requirement.
MATCHING_RULE_IN_CHAIN = "1.2.840.113556.1.4.1941"


class LdapService:
    """Active Directory authentication backed by the ldap_settings table."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_settings(self) -> Optional[LdapSettings]:
        """Load the single LDAP settings row (None if never configured)."""
        result = await self.db.execute(select(LdapSettings).limit(1))
        return result.scalar_one_or_none()

    async def is_enabled(self) -> bool:
        """True when AD auth is configured and turned on."""
        cfg = await self.get_settings()
        return bool(cfg and cfg.is_active)

    async def authenticate(
        self, username: str, password: str
    ) -> Tuple[bool, Optional[dict], Optional[str]]:
        """
        Authenticate a user against AD and enforce group membership.

        Returns (ok, attrs, error):
          - (True, {email, display_name}, None) on success
          - (False, None, reason) otherwise
        """
        if not password:
            # Guard against a bind falling back to anonymous.
            return False, None, "Empty password"

        cfg = await self.get_settings()
        if not cfg or not cfg.is_active:
            return False, None, "LDAP is not enabled"

        if cfg.use_ntlm:
            try:
                return await self._authenticate_ntlm(cfg, username, password)
            except asyncio.TimeoutError:
                logger.error("LDAP NTLM timeout authenticating '%s'", username)
                return False, None, "LDAP server timeout"
            except Exception as exc:  # noqa: BLE001 - never leak to the OpenVPN login
                logger.error("Unexpected NTLM LDAP error for '%s': %s", username, exc)
                return False, None, "LDAP server error"

        conf = self._simple_conf(cfg)
        return await run_in_threadpool(self._authenticate_simple, conf, username, password)

    async def test_connection(self, conf: dict) -> Tuple[bool, Optional[str]]:
        """
        Verify a candidate configuration (service-account bind + base search).
        `conf` is a plain dict so unsaved form values can be tested.
        """
        if conf.get("use_ntlm"):
            try:
                return await self._test_ntlm(conf)
            except asyncio.TimeoutError:
                return False, "Connection timeout"
            except Exception as exc:  # noqa: BLE001
                return False, f"Connection error: {exc}"
        return await run_in_threadpool(self._test_simple, conf)

    # ------------------------------------------------------------------ #
    # Group sync (mirror AD group members -> local shadow users)         #
    # ------------------------------------------------------------------ #

    async def enumerate_group_members(self):
        """List every member of the required VPN group (nested resolved).

        Returns (members, error) where members is a list of dicts
        {username, email, display_name, disabled}. Reuses the same signed NTLM /
        simple bind machinery as authenticate(), just without the per-user filter.
        """
        cfg = await self.get_settings()
        if not cfg or not cfg.is_active:
            return None, "LDAP is not enabled"
        if not cfg.required_group_dn:
            return None, "No VPN group configured"

        if cfg.use_ntlm:
            try:
                return await self._enumerate_ntlm(cfg)
            except asyncio.TimeoutError:
                return None, "LDAP server timeout"
            except Exception as exc:  # noqa: BLE001
                logger.error("LDAP NTLM group enumeration error: %s", exc)
                return None, f"LDAP error: {exc}"
        conf = self._simple_conf(cfg)
        return await run_in_threadpool(self._enumerate_simple, conf)

    async def sync_group(self, delete_mode: str = "deactivate", dry_run: bool = False) -> dict:
        """Mirror the AD group into local shadow users.

        - Creates a shadow user (auth_source=AD) for every group member missing locally.
        - Reactivates AD users that were disabled locally but are back in the group.
        - For local AD users that left the group, applies ``delete_mode``:
            "deactivate" (default, reversible) -> is_active = False
            "delete"                            -> hard delete (cascades profile/conns)
            "keep"                              -> leave untouched
        NEVER touches LOCAL users, admins or service accounts. If the group
        enumeration returns zero members, removals are SKIPPED (safety guard so a
        transient LDAP failure can't wipe everyone). ``dry_run=True`` previews only.
        """
        from app.models.user import User, AuthSource, UserType

        summary = {
            "success": False, "message": None, "dry_run": dry_run,
            "delete_mode": delete_mode, "total_in_group": 0,
            "added": 0, "removed": 0, "reactivated": 0, "skipped": 0,
            "added_users": [], "removed_users": [],
        }

        members, err = await self.enumerate_group_members()
        if err:
            summary["message"] = err
            return summary

        members = members or []
        summary["total_in_group"] = len(members)
        group_usernames = {
            (m.get("username") or "").lower() for m in members if m.get("username")
        }

        existing_ad = (await self.db.execute(
            select(User).where(User.auth_source == AuthSource.AD)
        )).scalars().all()
        existing_by_name = {u.username.lower(): u for u in existing_ad}

        # ---- add / reactivate / refresh email ----
        for m in members:
            uname = (m.get("username") or "").lower()
            if not uname:
                continue
            u = existing_by_name.get(uname)
            if u is None:
                # Never clobber an existing LOCAL user that happens to share the name.
                clash = (await self.db.execute(
                    select(User).where(User.username == uname)
                )).scalar_one_or_none()
                if clash is not None:
                    summary["skipped"] += 1
                    continue
                if not dry_run:
                    self.db.add(User(
                        username=uname,
                        email=m.get("email"),
                        password_hash=None,
                        user_type=UserType.HUMAN,
                        auth_source=AuthSource.AD,
                        is_active=True,
                    ))
                summary["added"] += 1
                summary["added_users"].append(uname)
            else:
                if m.get("email") and u.email != m.get("email") and not dry_run:
                    u.email = m.get("email")
                if not u.is_active:
                    if not dry_run:
                        u.is_active = True
                    summary["reactivated"] += 1

        # ---- remove those who left the group (guarded) ----
        if group_usernames and delete_mode != "keep":
            for uname, u in existing_by_name.items():
                if uname in group_usernames:
                    continue
                if u.is_admin or u.user_type == UserType.SERVICE:
                    summary["skipped"] += 1
                    continue
                if delete_mode == "delete":
                    if not dry_run:
                        await self.db.delete(u)
                    summary["removed"] += 1
                    summary["removed_users"].append(uname)
                elif delete_mode == "deactivate":
                    if u.is_active:
                        if not dry_run:
                            u.is_active = False
                        summary["removed"] += 1
                        summary["removed_users"].append(uname)

        if dry_run:
            await self.db.rollback()
        else:
            await self.db.commit()

        summary["success"] = True
        verb = "removed" if delete_mode == "delete" else "deactivated"
        summary["message"] = (
            f"{summary['added']} added, {summary['removed']} {verb}, "
            f"{summary['reactivated']} reactivated, {summary['skipped']} skipped"
        )
        return summary

    # ------------------------------------------------------------------ #
    # Config helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _netbios(server_bind_dn: Optional[str], ad_domain: Optional[str],
                 search_base: Optional[str]) -> str:
        """Resolve the NetBIOS domain for NTLM binds."""
        if ad_domain:
            return ad_domain
        if server_bind_dn and "\\" in server_bind_dn:
            return server_bind_dn.split("\\", 1)[0]
        if search_base:
            for part in search_base.split(","):
                part = part.strip()
                if part.lower().startswith("dc="):
                    return part.split("=", 1)[1].upper()
        return ""

    @staticmethod
    def _split_bind(bind_dn: Optional[str], default_domain: str) -> Tuple[str, str]:
        """Return (domain, sAMAccountName) for the service account NTLM bind."""
        b = (bind_dn or "").strip()
        if "\\" in b:
            d, u = b.split("\\", 1)
            return d, u
        if "=" in b:
            # A full DN was entered; take the first RDN value as the account name.
            first = b.split(",", 1)[0].strip()
            if "=" in first:
                return default_domain, first.split("=", 1)[1]
        return default_domain, b

    def _simple_conf(self, cfg: LdapSettings) -> dict:
        return {
            "server": cfg.server,
            "port": cfg.port,
            "bind_dn": cfg.bind_dn,
            "bind_password": cfg.bind_password,
            "search_base": cfg.search_base,
            "user_attr": cfg.user_attr or "sAMAccountName",
            "required_group_dn": cfg.required_group_dn,
            "timeout": cfg.timeout or 5,
        }

    @staticmethod
    def _ntlm_url(host, port, domain, user, password) -> str:
        userinfo = f"{quote(domain, safe='')}%5C{quote(user, safe='')}"
        return f"ldap+ntlm-password://{userinfo}:{quote(password or '', safe='')}@{host}:{int(port)}"

    async def _ntlm_client(self, host, port, domain, user, password, timeout):
        """Open a signed NTLM LDAP connection; returns (client, error)."""
        from msldap.commons.factory import LDAPConnectionFactory

        url = self._ntlm_url(host, port, domain, user, password)
        client = LDAPConnectionFactory.from_url(url).get_client()
        _, err = await asyncio.wait_for(client.connect(), timeout=timeout)
        return client, err

    @staticmethod
    def _first(value):
        if isinstance(value, (list, tuple)):
            return str(value[0]) if value else None
        return str(value) if value is not None else None

    # ------------------------------------------------------------------ #
    # NTLM (signed) — msldap                                             #
    # ------------------------------------------------------------------ #

    async def _authenticate_ntlm(self, cfg: LdapSettings, username: str, password: str):
        from ldap3.utils.conv import escape_filter_chars

        timeout = cfg.timeout or 5
        domain = self._netbios(cfg.bind_dn, cfg.ad_domain, cfg.search_base)
        svc_domain, svc_user = self._split_bind(cfg.bind_dn, domain)

        # 1) Service-account bind to search the directory.
        client, err = await self._ntlm_client(
            cfg.server, cfg.port, svc_domain, svc_user, cfg.bind_password, timeout
        )
        if err:
            logger.error("LDAP NTLM service bind failed: %s", err)
            return False, None, "Directory bind failed (service account)"

        try:
            # 2) Find the user AND require VPN-group membership (nested via IN_CHAIN).
            safe_user = escape_filter_chars(username)
            search_filter = (
                f"(&({cfg.user_attr}={safe_user})"
                f"(memberOf:{MATCHING_RULE_IN_CHAIN}:={cfg.required_group_dn}))"
            )
            found = None
            async for entry, e in client.pagedsearch(
                search_filter, ["distinguishedName", "mail", "displayName"]
            ):
                if e:
                    logger.error("LDAP NTLM search error: %s", e)
                    break
                if entry:
                    found = entry
                    break
            if not found:
                logger.info("LDAP deny for '%s': not found or not in VPN group", username)
                return False, None, "User not found or not a member of the VPN group"

            attrs = found.get("attributes", found) or {}
            email = self._first(attrs.get("mail"))
            display_name = self._first(attrs.get("displayName"))
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

        # 3) Verify the user's password with a signed NTLM bind as DOMAIN\user.
        user_client, uerr = await self._ntlm_client(
            cfg.server, cfg.port, domain, username, password, timeout
        )
        if uerr:
            logger.info("LDAP NTLM password verification failed for '%s'", username)
            return False, None, "Invalid username or password"
        try:
            await user_client.disconnect()
        except Exception:  # noqa: BLE001
            pass

        logger.info("LDAP NTLM auth success for '%s'", username)
        return True, {"email": email, "display_name": display_name}, None

    async def _test_ntlm(self, conf: dict):
        if not conf.get("server"):
            return False, "Server is required"
        timeout = conf.get("timeout") or 5
        domain = self._netbios(conf.get("bind_dn"), conf.get("ad_domain"), conf.get("search_base"))
        if not domain:
            return False, "NetBIOS domain is required for NTLM (e.g. DOMAIN)"
        svc_domain, svc_user = self._split_bind(conf.get("bind_dn"), domain)
        client, err = await self._ntlm_client(
            conf["server"], conf.get("port") or 389, svc_domain, svc_user,
            conf.get("bind_password"), timeout,
        )
        if err:
            return False, f"Bind failed: {err}"
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return True, None

    async def _enumerate_ntlm(self, cfg: LdapSettings):
        timeout = cfg.timeout or 5
        domain = self._netbios(cfg.bind_dn, cfg.ad_domain, cfg.search_base)
        svc_domain, svc_user = self._split_bind(cfg.bind_dn, domain)

        client, err = await self._ntlm_client(
            cfg.server, cfg.port, svc_domain, svc_user, cfg.bind_password, timeout
        )
        if err:
            logger.error("LDAP NTLM service bind failed (enumerate): %s", err)
            return None, "Directory bind failed (service account)"

        members = []
        try:
            search_filter = (
                f"(&(objectCategory=person)(objectClass=user)"
                f"(memberOf:{MATCHING_RULE_IN_CHAIN}:={cfg.required_group_dn}))"
            )
            async for entry, e in client.pagedsearch(
                search_filter,
                ["sAMAccountName", "mail", "displayName", "userAccountControl"],
            ):
                if e:
                    logger.error("LDAP NTLM group search error: %s", e)
                    return None, "Directory search error"
                if not entry:
                    continue
                attrs = entry.get("attributes", entry) or {}
                m = self._member_from_attrs(attrs)
                if m:
                    members.append(m)
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        logger.info("LDAP NTLM group enumeration: %d member(s)", len(members))
        return members, None

    # ------------------------------------------------------------------ #
    # Simple (unsigned) bind — ldap3, blocking (run in threadpool)       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _connect(conf: dict, user=None, password=None):
        import ldap3

        server = ldap3.Server(
            conf["server"], port=int(conf["port"]), get_info=ldap3.NONE,
            connect_timeout=int(conf["timeout"]),
        )
        bind_user = user if user is not None else conf.get("bind_dn")
        bind_pass = password if user is not None else conf.get("bind_password")
        return ldap3.Connection(
            server, user=bind_user or None, password=bind_pass or None,
            auto_bind=False, receive_timeout=int(conf["timeout"]),
        )

    @classmethod
    def _authenticate_simple(cls, conf: dict, username: str, password: str):
        import ldap3
        from ldap3.utils.conv import escape_filter_chars

        try:
            conn = cls._connect(conf)
            if not conn.bind():
                logger.error("LDAP simple service bind failed: %s", conn.result)
                return False, None, "Directory bind failed (service account)"

            safe_user = escape_filter_chars(username)
            search_filter = (
                f"(&({conf['user_attr']}={safe_user})"
                f"(memberOf:{MATCHING_RULE_IN_CHAIN}:={conf['required_group_dn']}))"
            )
            conn.search(
                search_base=conf["search_base"], search_filter=search_filter,
                search_scope=ldap3.SUBTREE,
                attributes=["distinguishedName", "mail", "displayName"],
            )
            if not conn.entries:
                conn.unbind()
                return False, None, "User not found or not a member of the VPN group"

            entry = conn.entries[0]
            user_dn = str(entry.entry_dn)
            email = str(entry.mail) if "mail" in entry else None
            display_name = str(entry.displayName) if "displayName" in entry else None
            conn.unbind()

            user_conn = cls._connect(conf, user=user_dn, password=password)
            if not user_conn.bind():
                return False, None, "Invalid username or password"
            user_conn.unbind()

            return True, {"email": email, "display_name": display_name}, None
        except ldap3.core.exceptions.LDAPException as exc:
            logger.error("LDAP simple error authenticating '%s': %s", username, exc)
            return False, None, "LDAP server error"
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected LDAP error authenticating '%s': %s", username, exc)
            return False, None, "LDAP server error"

    @classmethod
    def _test_simple(cls, conf: dict):
        import ldap3

        conf = {
            "server": conf.get("server"), "port": conf.get("port") or 389,
            "bind_dn": conf.get("bind_dn"), "bind_password": conf.get("bind_password"),
            "search_base": conf.get("search_base"), "timeout": conf.get("timeout") or 5,
        }
        if not conf["server"]:
            return False, "Server is required"
        try:
            conn = cls._connect(conf)
            if not conn.bind():
                return False, f"Bind failed: {conn.result.get('description', 'invalid credentials')}"
            if conf["search_base"]:
                conn.search(
                    search_base=conf["search_base"], search_filter="(objectClass=*)",
                    search_scope=ldap3.BASE, attributes=["distinguishedName"],
                )
            conn.unbind()
            return True, None
        except ldap3.core.exceptions.LDAPException as exc:
            return False, f"Connection error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Connection error: {exc}"

    @classmethod
    def _member_from_attrs(cls, attrs: dict):
        """Normalize an AD user entry into {username, email, display_name, disabled}."""
        username = cls._first(attrs.get("sAMAccountName"))
        if not username:
            return None
        uac = attrs.get("userAccountControl")
        if isinstance(uac, (list, tuple)):
            uac = uac[0] if uac else None
        try:
            disabled = bool(int(uac) & 0x2) if uac is not None else False
        except (TypeError, ValueError):
            disabled = False
        return {
            "username": username,
            "email": cls._first(attrs.get("mail")),
            "display_name": cls._first(attrs.get("displayName")),
            "disabled": disabled,
        }

    @classmethod
    def _enumerate_simple(cls, conf: dict):
        import ldap3

        try:
            conn = cls._connect(conf)
            if not conn.bind():
                logger.error("LDAP simple service bind failed (enumerate): %s", conn.result)
                return None, "Directory bind failed (service account)"

            search_filter = (
                f"(&(objectCategory=person)(objectClass=user)"
                f"(memberOf:{MATCHING_RULE_IN_CHAIN}:={conf['required_group_dn']}))"
            )
            members = []
            for entry in conn.extend.standard.paged_search(
                search_base=conf["search_base"], search_filter=search_filter,
                search_scope=ldap3.SUBTREE,
                attributes=["sAMAccountName", "mail", "displayName", "userAccountControl"],
                paged_size=500, generator=True,
            ):
                if entry.get("type") != "searchResEntry":
                    continue
                m = cls._member_from_attrs(entry.get("attributes", {}) or {})
                if m:
                    members.append(m)
            conn.unbind()
            logger.info("LDAP simple group enumeration: %d member(s)", len(members))
            return members, None
        except ldap3.core.exceptions.LDAPException as exc:
            logger.error("LDAP simple group enumeration error: %s", exc)
            return None, f"LDAP error: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected LDAP group enumeration error: %s", exc)
            return None, f"LDAP error: {exc}"
