# BLAXCY — B7 Live Acceptance Evidence (REFUSED RUN — NOT EVIDENCE)

This file records an **unauthorized** `blaxcy accept-live` attempt. A refusal is
an authorization outcome, not acceptance evidence, and it must never overwrite a
genuine artifact.

- date: 2026-10-03
- real input authorized: **no (refused)**
- **verified: False**
- reason: real input not authorized; set `BLAXCY_ENABLE_REAL_INPUT=1`

## Why the real artifact is missing

No genuine B7 artifact exists on disk. The "4/4 verified" run recorded by previous
sessions lives only as prose in `CHECKPOINT.md` and `REQUIREMENTS.md`; the on-disk
artifact was overwritten by an unauthorized run before 2026-10-03. Root cause: the
test `tests/test_acceptance.py::test_cli_accept_live_refuses_without_authorization`
ran the CLI against the project root, so `Application()` wrote into the real
`.build-state/`. Both that test and `blaxcy/acceptance.py` are now fixed: a refusal
is written to this `.refused.md` sibling and never replaces `B7_EVIDENCE.md`.

## How to produce real evidence

```bash
BLAXCY_ENABLE_REAL_INPUT=1 blaxcy accept-live
```

This is tracked as **B-010** in `BLOCKERS.md`. Until it is produced, B7 must not be
reported as `VERIFIED`.
