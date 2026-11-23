# Security Policy

[English](SECURITY.md) · [简体中文](SECURITY.zh-CN.md)

DrPanda MCP is a read-only troubleshooting service that stores connection metadata and encrypted credentials. Please treat security reports as sensitive.

## Supported versions

| Version | Supported |
|---|---|
| 1.13.x | Yes |
| < 1.13 | No |

## Reporting a vulnerability

Do **not** open a public issue for security problems.

1. Use GitHub's private security advisory: <https://github.com/linyu19872008/dr-panda-mcp/security/advisories/new> (preferred), or
2. Email the maintainer at <linyu19872008@gmail.com> with the subject `[SECURITY] DrPanda MCP`.

Please include:

- affected version/commit;
- deployment mode (local, reverse proxy, container) and whether authentication was enabled;
- reproduction steps and expected/actual behavior;
- impact assessment (credential exposure, read-only guard bypass, auth bypass, etc.);
- any suggested fix.

Do not include real production credentials, tokens, or customer data. Redact logs and hostnames.

## Scope

Examples of in-scope reports:

- bypassing the read-only whitelist or dangerous-operation rules;
- authentication/authorization bypass for the web console or `/mcp`;
- leakage of target secrets, MCP tokens, session cookies, or encrypted credential material;
- secret exposure through logs, audit, errors, or API responses;
- CSRF/Host/Origin/CSP weaknesses with concrete impact.

Examples of out-of-scope reports:

- reports requiring a compromised administrator browser or host;
- findings from scanners without a reproducible impact;
- missing security headers without an exploit path;
- social engineering, physical access, denial of service against your own instance.

## Response

This is a best-effort open-source project. We aim to acknowledge reports within 7 days and will coordinate disclosure after a fix is available. Please do not disclose the issue publicly before coordination.
