---
name: Bug report
about: Report a problem with EdgeGate
title: "[bug] "
labels: bug
---

**Describe the bug**
A clear description of what went wrong.

**To reproduce**
Steps to reproduce the behavior.

**Expected behavior**
What you expected to happen.

**Environment**
- EdgeGate version (`VERSION` file / `/health` endpoint):
- OS (e.g. Ubuntu 24.04):
- Install type: fresh / upgrade / migrated via backup-restore
- Component: backend / frontend / openvpn / ipsec / nat-agent / update-agent / install

**Logs**
Relevant output (scrub secrets/IPs first):
```
docker compose logs --tail=100 backend
# or: vpnctl logs
```

**Additional context**
Anything else that helps.
