# Security Policy

BLAXCY drives a real mouse, keyboard and windows, so security is a first-class
concern. This file describes how to report a vulnerability and what BLAXCY does
and does not do. The full posture is in [`docs/SECURITY.md`](docs/SECURITY.md).

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report privately through GitHub's
[Report a vulnerability](https://github.com/alex3430143/blaxcyds/security/advisories/new)
form. Include, where possible:

- a description of the issue and its impact;
- precise reproduction steps;
- the version/commit and your session type (X11/Wayland) and desktop;
- any suggested fix or mitigation.

We aim to acknowledge reports within a few days and will credit reporters who
wish to be named.

## Supported versions

The latest release on the default branch is supported. This is a young project;
security fixes will land on the current `1.x` line.

| Version | Supported |
|---|---|
| 1.x | ✅ |
| < 1.0 | ❌ |

## What BLAXCY guarantees

- **Dry-run by default.** Live input requires `BLAXCY_ENABLE_REAL_INPUT=1` **and**
  per-action Policy approval.
- **Single risk chokepoint.** Every action is risk-classified before it can reach
  a backend.
- **Auth boundaries are never bypassed.** Lock screens, sudo/polkit, keyrings,
  2FA and CAPTCHA are handed back to the user.
- **Authenticated IPC.** The supervised-process transport is HMAC-authenticated,
  freshness-windowed, replay-protected and size-bounded.
- **Secrets are protected.** Credentials resolve through the OS keyring,
  `secret-tool`, then an encrypted file — never plaintext by default — and logs
  and memory are redacted.
- **No telemetry.** No network call happens unless you configure a model
  provider and use it.

## In scope

- Policy bypass or a way to reach the real Body without the gate.
- IPC authentication/replay/duplicate-field bypass.
- Credential or secret disclosure (logs, memory, files, errors).
- Prompt-injection paths that let untrusted content authorize actions.
- Denial of service that leaves input stuck (held buttons/modifiers).

## Out of scope

- Issues that require `BLAXCY_ENABLE_REAL_INPUT=1` **and** an already-compromised
  local account.
- The deliberate absence of remote (network) IPC.
- Missing Wayland live support on an X11-only host (a documented, environment-
  gated gap, not a vulnerability).
