---
type: Wiki Overview
title: 'TASK-1115: parrot/conf.py — AWS_CREDENTIALS[''security''] slot'
id: doc:sdd-tasks-completed-task-1115-aws-credentials-security-slot-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Adds an `AWS_CREDENTIALS['security']` slot in `parrot/conf.py` derived
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

# TASK-1115: parrot/conf.py — AWS_CREDENTIALS['security'] slot

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Adds an `AWS_CREDENTIALS['security']` slot in `parrot/conf.py` derived
from the existing `aws_security` INI section so the SecurityAgent can
call `FileManagerFactory.create(manager_type='s3', aws_id='security', ...)`
idiomatically (resolved U2).

Implements Spec §3 Module 9 Path A.

---

## Scope

- Modify `parrot/conf.py` (committed file — this is the tracked half of
  Module 9):
  - Locate the existing `AWS_CREDENTIALS` dict (verify the surrounding
    code first).
  - Read the three values from the `aws_security` INI section via
    `config.get('aws_security', 'aws_key', fallback=None)`,
    `config.get('aws_security', 'aws_secret', fallback=None)`,
    `config.get('aws_security', 'region_name', fallback=config.AWS_REGION_NAME)`.
  - Register `AWS_CREDENTIALS['security'] = {"aws_key": ..., "aws_secret": ..., "region_name": ...}`
    AT MODULE LOAD TIME (alongside the existing `AWS_CREDENTIALS[...]`
    registrations).
  - Handle missing INI section gracefully: if `aws_key` is `None`,
    SKIP the registration (do NOT raise at import time) and log a
    warning. The SecurityAgent will fall back to default credentials
    if `aws_id='security'` is unavailable.
- Add a small unit test in `tests/conf/test_aws_credentials_security.py`:
  - With env vars / INI mocked, confirm `AWS_CREDENTIALS['security']`
    is populated.
  - With INI section absent, confirm the key is absent from
    `AWS_CREDENTIALS` and a warning was logged.

**NOT in scope**: any SecurityAgent wiring (TASK-1116); any other
parrot/conf.py changes; new env vars beyond what's already specified
in the spec §6 Configuration References table.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/conf.py` | MODIFY | Add `AWS_CREDENTIALS['security']` slot |
| `tests/conf/__init__.py` | CREATE (if missing) | Test package init |
| `tests/conf/test_aws_credentials_security.py` | CREATE | Unit test for the new slot |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Inside parrot/conf.py, no new external imports should be needed.
# Verify at task start by reading the file head — navconfig.config is
# already imported.
```

### Existing Signatures to Use

```python
# parrot/conf.py — (verify at task start; line numbers approximate)
# - AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_REGION_NAME constants                F014
# - AWS_CREDENTIALS: dict[str, dict[str, str]] registered at module load     F014
# - config.get('aws_security', '<key>') reads INI section                    F014
#
# Look for the existing AWS_CREDENTIALS[...] block; add the 'security'
# entry there, matching the style.
```

### Does NOT Exist

- ~~`config.AWS_KEY` / `config.AWS_SECRET`~~ — real constants are
  `AWS_ACCESS_KEY` / `AWS_SECRET_KEY`.
- ~~`config.aws_security.<key>`~~ — `aws_security` is an INI **section**,
  read via `config.get('aws_security', '<key>')`.
- ~~`AWS_CREDENTIALS['security']`~~ — does not exist yet; this task adds it.
- ~~A bootstrap step or factory for `AWS_CREDENTIALS`~~ — entries are
  added at module load. Follow the existing style.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/conf.py — diff sketch (verify exact location at task start)
# Existing AWS_CREDENTIALS registrations look something like:
# AWS_CREDENTIALS = {}
# AWS_CREDENTIALS['default'] = {
#     'aws_key': AWS_ACCESS_KEY,
#     'aws_secret': AWS_SECRET_KEY,
#     'region_name': AWS_REGION_NAME,
# }
# ... possibly other slots ...

# ADD (alongside the existing slots):
_aws_security_key = config.get('aws_security', 'aws_key', fallback=None)
if _aws_security_key:
    AWS_CREDENTIALS['security'] = {
        'aws_key':     _aws_security_key,
        'aws_secret':  config.get('aws_security', 'aws_secret', fallback=None),
        'region_name': config.get('aws_security', 'region_name', fallback=AWS_REGION_NAME),
    }
else:
    # Soft warn — the SecurityAgent will fall back to 'default' creds.
    import logging
    logging.getLogger(__name__).warning(
        "aws_security INI section not configured; AWS_CREDENTIALS['security'] not registered. "
        "SecurityAgent will use default credentials."
    )
```

### Key Constraints

- Do NOT raise at module import if `aws_security` is missing — many dev
  environments won't have it. Log a warning, leave the slot unregistered.
- Match the existing style for other `AWS_CREDENTIALS` slots in the file
  (whitespace, ordering, etc.).
- This is the ONLY tracked file change for Module 9; TASK-1116 deals with
  the gitignored `agents/security.py`.

### References in Codebase

- Spec §3 Module 9 Path A, §6 Configuration References.
- Finding F014 — current navconfig surface.

---

## Acceptance Criteria

- [ ] `parrot/conf.py` registers `AWS_CREDENTIALS['security']` when the
      `aws_security` INI section provides `aws_key`.
- [ ] When `aws_security` is missing, importing `parrot.conf` does NOT
      raise; a warning is logged instead.
- [ ] `from parrot.conf import AWS_CREDENTIALS; 'security' in AWS_CREDENTIALS`
      is `True` in environments that configure the INI section.
- [ ] All unit tests pass: `pytest tests/conf/test_aws_credentials_security.py -v`.
- [ ] No regressions in `parrot.conf` import behavior elsewhere.

---

## Test Specification

```python
# tests/conf/test_aws_credentials_security.py
import importlib
import logging
import pytest


class TestAwsSecuritySlot:
    def test_slot_registered_when_ini_present(self, monkeypatch):
        # Adapt this to the project's test-config harness — likely
        # involves writing a temp .ini or patching navconfig's loader.
        # If navconfig caches at import time, force a reimport:
        import parrot.conf as conf
        # ... arrange aws_security INI keys to be present ...
        importlib.reload(conf)
        assert 'security' in conf.AWS_CREDENTIALS
        assert conf.AWS_CREDENTIALS['security']['aws_key'] is not None

    def test_no_raise_when_ini_missing(self, monkeypatch, caplog):
        # Force aws_security absence
        # ...
        with caplog.at_level(logging.WARNING):
            import parrot.conf as conf
            importlib.reload(conf)
        # Either 'security' absent OR keys are None — both acceptable
        if 'security' in conf.AWS_CREDENTIALS:
            pytest.skip("INI configured in this environment; cannot test absence")
        assert any("aws_security" in r.message for r in caplog.records)
```

(Adapt to the project's actual `parrot.conf` test fixtures — confirm at
task start whether tests live under `tests/conf/`, `tests/config/`, or
elsewhere.)

---

## Agent Instructions

1. Read the spec section §3 Module 9 Path A.
2. Inspect `parrot/conf.py` for the existing `AWS_CREDENTIALS` block —
   capture the exact line range and style.
3. Apply the diff.
4. Run unit tests + any broader `parrot.conf` smoke tests.
5. Move this file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Added `AWS_CREDENTIALS['security']` slot at lines ~460-474 in `parrot/conf.py`,
immediately after the existing `AWS_CREDENTIALS` dict literal (after the `"backend"` entry).
Surrounding style matched (4-space indent, single-quoted keys).

Deviated from the task spec's `config.get('aws_security', 'aws_key', fallback=None)` call —
the actual navconfig signature is `get(key, section=None, fallback=None)`, so the positional
form would have reversed section and key. Used keyword form instead:
`config.get('aws_key', section='aws_security', fallback=None)`.

`logging` was already imported at the top of `conf.py` via `from navconfig.logging import logging`.
No new import needed. Both unit tests pass (2 passed in 0.05s).

**Deviations from spec**: navconfig call uses keyword `section=` instead of positional arg order
to correctly read from the [aws_security] INI section.
