# Security Policy

EdgeGate terminates VPN traffic and manages firewall/NAT rules on the host, so
security reports are taken seriously.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, report privately via GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
(the "Report a vulnerability" button under the repository's **Security** tab),
or contact the maintainer directly.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a proof-of-concept if possible).
- Affected version (`VERSION` file / `/health` endpoint) and deployment details.

You can expect an initial acknowledgement within a few days. Please give us a
reasonable window to release a fix before any public disclosure.

## Supported versions

Security fixes target the latest released `vX.Y.Z` tag. Deployed appliances
update in place via the built-in update agent (`vpnctl update`) or migrate via
`vpnctl backup` + a fresh install + `vpnctl restore`.

## Handling secrets

- Never commit a real `.env`, private keys, certificates, or `.ovpn` profiles.
  The `.gitignore` blocks the common cases.
- Rotate the auto-generated tokens (`SECRET_KEY`, `JWT_SECRET_KEY`,
  `*_AGENT_TOKEN`) if a host is ever compromised.
- Trusted Hosts (source-IP allowlists) and MFA are available for admin and
  service accounts — enable them for internet-facing panels.
