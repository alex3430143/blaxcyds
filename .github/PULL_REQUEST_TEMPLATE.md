## Summary

<!-- What does this change, and why? -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor
- [ ] Documentation
- [ ] Tests
- [ ] Packaging / CI

## Safety checklist

- [ ] Real input remains dry-run by default; nothing bypasses Policy.
- [ ] No auth boundary (lock screen, sudo/polkit, keyring, 2FA, CAPTCHA) is
      auto-performed.
- [ ] Untrusted external content is still treated as untrusted.
- [ ] No secret is logged, stored in memory, or written to disk in plaintext.

## Verification

- [ ] `python -m pytest -q` passes (246 tests, no real mouse/keyboard).
- [ ] `python -m compileall -q blaxcy tests` passes.
- [ ] `bash -n install.sh upgrade.sh uninstall.sh` passes.
- [ ] `ruff check --select E9,F63,F7,F82 blaxcy tests` passes.
- [ ] `.build-state/` updated if what is verified changed.

<!-- If a capability is implemented but not verified, say so plainly and do not
mark it VERIFIED. -->
