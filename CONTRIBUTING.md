# Contributing to BLAXCY

Thanks for your interest. BLAXCY is a safety-critical desktop agent, so the bar
for changes is high and the rules are explicit. Please read this before opening a
pull request.

## Ground rules

1. **Never fake a capability.** If something is not implemented or not verified,
   mark it `NOT_STARTED` / `BLOCKED` in
   [`.build-state/REQUIREMENTS.md`](.build-state/REQUIREMENTS.md). Do not weaken
   a requirement to make a feature look done.
2. **Safety first.** Real input stays dry-run by default. Nothing may bypass the
   Policy chokepoint, and no change may auto-perform an auth boundary (lock
   screen, sudo/polkit, keyring, 2FA, CAPTCHA).
3. **Tests never touch the real machine.** Use the fake Eye/Body adapters. A test
   must not move the real mouse or press a real key.
4. **Keep the direction lock.** BLAXCY is "an AI like a human computer user" — not
   a chatbot, a terminal wrapper, or a thin model wrapper. See
   [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Development setup

```bash
git clone https://github.com/alex3430143/blaxcyds.git
cd blaxcyds
./install.sh --dev          # creates .venv and installs everything + dev extras
source .venv/bin/activate
```

## Before you open a pull request

```bash
python -m pytest -q                       # 246 tests
python -m compileall -q blaxcy tests      # syntax
bash -n install.sh upgrade.sh uninstall.sh
ruff check --select E9,F63,F7,F82 blaxcy tests   # real errors (undefined names, syntax)
```

The full default Ruff rule set is **not** yet enforced; the project runs the
error-only preset above in CI so that style work can proceed incrementally
without blocking correctness. If you touch a file, leaving it cleaner is
welcome.

## Style

- Python 3.11+, `from __future__ import annotations`, type hints on public
  functions.
- Match the surrounding code; keep functions focused and side effects explicit.
- Formatting: 100-column lines (`[tool.ruff]` in `pyproject.toml`).

## Commits and pull requests

- Write a clear, imperative subject line and explain *why* in the body.
- Keep each pull request focused; describe the safety impact explicitly.
- Update [`.build-state/`](.build-state/) when you change what is verified: this
  is the recovery source of truth for the next contributor (or agent).

## Reporting security issues

Do **not** open a public issue for a security problem. Follow
[`SECURITY.md`](SECURITY.md).

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
