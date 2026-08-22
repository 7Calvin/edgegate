# IPsec HA/Failover — Session Handoff

> Continuation doc so work can resume on another machine. **No secrets here**
> (this repo's remote is on GitHub) — SSH passwords / PSK live only in local
> Claude memory. Re-provide access creds in chat when resuming.

Last updated: 2026-07-22 (end of session).

## TL;DR — where we are

- **Released & functional:** `v1.5.2` — swanctl IPsec (running in prod "alphaquimica" and on the homolog box).
- **COMPLETE on this branch (NOT released yet):** the **IPsec HA/failover feature** — a peer (FortiGate) with **2 fixed public IPs**; the tunnel fails over between them. Built, **validated live** (incl. a real primary-link-down from the FortiGate), and pushed as `452b254 → 29fa919 → eddee80`. Awaiting merge to `main` + release (~v1.6.0). Full detail: `docs/ipsec-ha-failover.md` §8–§12.
- **Where it's deployed:** manually on the **homolog box** (`/opt/edgegate`, backend/frontend rebuilt by hand). This branch (`feature/ipsec-failover`) is the same code, committed + on origin. Not on `main`, not released.
- **Current tunnel state on homolog:** both primary and backup **ESTABLISHED + INSTALLED**.

## What this branch adds

Connection model gains a **second peer endpoint** + a **manual switch** flag, plus ops buttons and three bug fixes.

- **Schema/DB:** `right_ip_backup` (alembic `012`, revises 011) and `prefer_backup` (alembic `013`, revises 012, `server_default=false`). `right_id` relaxed to allow empty → defaults to `right_ip` (fixes a 422 on create).
- **swanctl generation (`backend/app/models/ipsec.py`):**
  - `_remote_addrs()` → `remote_addrs = primary, backup` (native multi-homing failover). Ordered **backup-first** when `prefer_backup` is set.
  - `to_swanctl()` `remote {}` block **does not pin `id`** (accept any peer id; security = `remote_addrs` source-IP pinning + the PSK).
  - `to_swanctl_secret()` emits the PSK keyed to **all** peer ids, and each bare IP in **both** forms: address (`1.2.3.4`) **and** string/FQDN (`@1.2.3.4`) — see Bug 3.
- **Service (`backend/app/services/ipsec_service.py`):** `set_prefer_backup()` (flag + apply, then block/unblock the primary via the agent so the switch actually forces over — a mere reorder loses the race because the peer initiates from primary), `test_failover()` (agent blocks the active endpoint, auto-restores after `FAILOVER_TEST_RESTORE_SECONDS=120`).
- **Routes (`backend/app/api/v1/routes/ipsec.py`):** `switch-backup`, `rollback-primary`, `test-failover`.
- **Agent (`docker/ipsec-agent/app.py`):** `/block-peer/<ip>`, `/unblock-peer/<ip>`, `/test-failover-block/<ip>`.
- **UI (`frontend/src/pages/IPsecPage.tsx` + `api/client.ts` + `types/index.ts`):** "IP de Backup (failover)" field, 3 buttons (test / switch / rollback), a BACKUP badge, and a ✓ marker on the active IP.

## Three bugs found & fixed (all deployed to homolog)

1. **PSK not keyed to the backup IP** — the secret only listed the primary, and `remote{}` pinned the primary id → auth from the backup IP failed silently (retransmit). Fixed: secret lists all peer ids; no id pin.
2. **PUT `/connections` returned 500 while the save+apply actually succeeded** — the route returned the ORM object; FastAPI serialized it after the apply/restart awaits had expired the attributes → `DetachedInstanceError`. Fixed: re-fetch fresh before returning. (This misleading 500 is why panel edits looked failed and silently wiped fields.)
3. **PSK id-TYPE mismatch (the big one)** — a FortiGate with a **text "Local ID" set to its WAN IP** sends that identity as **ID_FQDN (a string), not ID_IPV4_ADDR**, so an address-typed secret id doesn't match → `no shared key found` → auth fails (a *wrong* key would instead say "MAC mismatched"). Fixed: for every bare IP, emit both `IP` and `@IP` (the `@` forces FQDN type). Verified via a real API `/apply` — both tunnels re-established.

## FortiGate (peer) side — SD-WAN failover

Moved off equal-distance/equal-weight static routes (which caused **ECMP → asymmetric routing → one-way ping**) to **SD-WAN zone + rule + Performance SLA**.

- **RESOLVED:** SLA health-check wouldn't come UP because the probe was **sourced from an IP outside** the protected subnet (`192.168.1.2` tunnel-iface / WAN). Fixed on the FortiGate: set the health-check **source** to an IP inside the remote subnet.

## Status — COMPLETE & validated (2026-07-22)

The whole feature is built, tested live, and pushed to the branch. The full record —
final swanctl format, every bug + fix, the FortiGate-side setup/gotchas, the export
feature, the live-failover validation, and the architecture decision — is in
**`docs/ipsec-ha-failover.md` (§8–§12)**. Highlights:

- **Live failover proven** two ways: the *Testar failover* button (blocked the active
  endpoint → DPD → moved to backup in ~42s → auto-restored), and a **real primary
  link-down from the FortiGate** (`set status down` on the primary tunnel interface —
  no management loss) where the EG carried all traffic on the backup during the outage
  and returned to primary ~5s after `set status up`.
- **Resolved items** that used to be open here: the FortiGate transit-NAT (it was a
  **stale cached session**, not the policy — fixed with `diagnose sys session clear`;
  the route was already `via sdwan-zone`); NAT-T `enable` on the primary phase1; the
  SLA `source` inside the protected subnet.
- **Edit-form wipe FIXED** — the form is now diff-based (only changed fields sent).

## Architecture decision (2026-07-22): keep "A" — single-connection active/standby

`remote_addrs = [primary, backup]`, both SAs up in parallel, one outbound path. Covers
the real need (link-down failover). The **two-tunnel route-based split** (needed for
per-member SD-WAN SLA staying green while idle, latency-based failover, and load-balance)
is **shelved** — only revisit if the requirement becomes "fail over on quality, not just
on down". Accepted trade-off: the backup member shows down-while-idle in the FortiGate
dashboard (self-heals on real failover). The test-failover auto-restore hardening was
also **dropped** (only leaks a stuck iptables block if the agent restarts within the 120s
window — a dev-churn artifact, not normal use).

## TODO before releasing (~v1.6.0)

Only one thing left, then ship: **merge `feature/ipsec-failover` → `main` + cut the
release**. Do NOT release unprompted — the user validates and signals when.

## How to resume on a new machine

1. `git fetch && git checkout feature/ipsec-failover`.
2. Re-provide SSH access to the homolog + web-panel creds in chat (kept out of git).
3. Read `docs/ipsec-ha-failover.md` §8–§12 for the complete final state.
4. The homolog deploy is **manual** (outside git) — connecting to it doesn't depend on which PC you use.
