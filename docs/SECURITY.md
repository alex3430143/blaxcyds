# BLAXCY Security & Privacy

## Posture

- **Least privilege, user-level.** BLAXCY runs as the user. It does not install
  setuid helpers, root daemons, or system services.
- **Dry-run by default.** Real mouse/keyboard control requires
  `BLAXCY_ENABLE_REAL_INPUT=1` **and** Policy approval of each action. With the
  gate off, every input action is simulated by `DryRunBackend`.
- **Single risk chokepoint.** Every action is risk-classified in
  `blaxcy/policy.py`. `AUTH_BOUNDARY` actions (sudo/polkit, keyring, login,
  2FA, CAPTCHA, unlock) are **never** auto-performed — they escalate to the user.
  `HIGH`/`DESTRUCTIVE` actions require explicit confirmation.
- **Destructive-command detection.** Terminal actions matching destructive
  patterns (`rm -rf`, `mkfs`, `dd if=`, `shred`, fork-bombs, raw-device writes)
  are classified `DESTRUCTIVE` and refused unless explicitly approved.

## Latches

- **Emergency stop** — blocks all further actions immediately.
- **Pause / resume** — suspends action execution.
- **User takeover** — BLAXCY yields control; no actions run until released.
- Applied before every action in `Body.execute` and honoured by the orchestrator
  loop and the GUI panel controls.

## Safe input release

`X11Backend.release_all()` releases any held mouse buttons and modifier keys, and
the `Supervisor` calls it **before restarting any component**, so a crash can
never leave the machine with a stuck key or button.

## Filesystem confinement

`SystemBackend` runs commands without a shell (no metacharacter expansion) and
confines writes to explicitly allowed roots (`BLAXCY_WORKSPACE`, else the current
working directory). Writes outside those roots raise `PermissionError`.

## Secrets and privacy

- Structured JSON logs pass through a redaction filter that scrubs private-key
  blocks, `sk-`/`ghp_`/`xox*` tokens, long hex blobs, and `key=value` secrets
  (`password`, `token`, `secret`, `api_key`, `authorization`, cookies).
- `Memory` redacts content before storage and never stores secrets deliberately.
- **Screen frames are not persisted by default** (`Settings.persist_frames`).
- No telemetry and no network calls unless a model provider is configured and
  used. The Ollama adapter only probes `127.0.0.1`.

## Prompt / content injection

External content (web pages, files, third-party tool output) is tagged
`TrustLevel.UNTRUSTED`. `Policy.may_follow_instructions()` refuses to treat
untrusted content as an instruction, so a malicious page cannot promote itself to
a command. Systems that ingest external text must keep this tag.

## Honest gaps

These are not vulnerabilities, but they are things BLAXCY does **not** yet do.
They are stated plainly rather than hidden:

- **Wayland portal capture/control** is implemented and unit-tested against a
  fake portal bus, but has no live evidence — that needs a Wayland host that
  advertises the XDG portals (see `.build-state/BLOCKERS.md`, B-003).
- **Browser isolation / delegation sandboxing** do not exist yet. Page content
  and delegated model output remain untrusted, and every browser/delegation
  action is policy-gated, but a truly sandboxed browser profile (separate
  user-data-dir, no ambient session credentials) is future work.
- **Remote (network) IPC is out of scope by design.** The authenticated transport
  is a local Unix domain socket only (B-009); a remote transport would need its
  own TLS/authorization design.
- **No third-party security audit.** The code is defensive and covered by tests,
  but it has not been through an independent audit.
- **In-memory secret handling** relies on process isolation, not on memory
  locking (e.g. `mlock`). Do not run BLAXCY on a host you do not trust.
