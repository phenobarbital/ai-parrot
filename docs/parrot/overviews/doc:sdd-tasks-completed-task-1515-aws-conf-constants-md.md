---
type: Wiki Overview
title: 'TASK-1515: Add AWS session-token & Anthropic-AWS workspace conf constants'
id: doc:sdd-tasks-completed-task-1515-aws-conf-constants-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4** of the spec. The Bedrock and AWS-workspace backends
  need
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

# TASK-1515: Add AWS session-token & Anthropic-AWS workspace conf constants

**Feature**: FEAT-232 — Enable Anthropic AWS Bedrock & AWS-native Backends
**Spec**: `sdd/specs/enable-anthropic-aws-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec. The Bedrock and AWS-workspace backends need
two config values that do not yet exist as `parrot.conf` constants. This task adds
them next to the existing AWS constants so the credential-resolution code
(TASK-1518) can import them, mirroring how `interfaces/aws.py` already imports
`AWS_ACCESS_KEY` etc.

---

## Scope

- In `packages/ai-parrot/src/parrot/conf.py`, alongside the existing AWS block
  (`AWS_ACCESS_KEY`/`AWS_SECRET_KEY`/`AWS_REGION_NAME`/`AWS_CREDENTIALS`), add:
  - `AWS_SESSION_TOKEN = config.get("AWS_SESSION_TOKEN", fallback=None)`
  - `ANTHROPIC_AWS_WORKSPACE_ID = config.get("ANTHROPIC_AWS_WORKSPACE_ID", fallback=None)`
- Use `fallback=` (NOT `default=`) — navconfig's `config.get` signature.

**NOT in scope**: reading these in `claude.py` (TASK-1518), backends, packaging.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | add two module-level constants |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py
AWS_ACCESS_KEY  = config.get("AWS_ACCESS_KEY",  fallback=aws_key)     # line 457
AWS_SECRET_KEY  = config.get("AWS_SECRET_KEY",  fallback=aws_secret)  # line 458
AWS_REGION_NAME = config.get("AWS_REGION_NAME", fallback=aws_region)  # line 459
AWS_CREDENTIALS = { ... }                                            # line 473
# `config` is navconfig's config object, already imported at top of conf.py.
```

### Does NOT Exist (this task adds them)
- ~~`AWS_SESSION_TOKEN`~~ in `conf.py` — add it.
- ~~`ANTHROPIC_AWS_WORKSPACE_ID`~~ in `conf.py` — add it.

---

## Implementation Notes

### Key Constraints
- navconfig `config.get(...)` uses keyword `fallback=`, never `default=` (raises TypeError).
- Place the two constants adjacent to the existing AWS block for discoverability.
- The conf constant is `ANTHROPIC_AWS_WORKSPACE_ID`, but downstream it feeds the
  SDK's `workspace_id` parameter (no `aws_` prefix on the SDK side) — documented
  in TASK-1518, not here.

### References in Codebase
- `packages/ai-parrot/src/parrot/conf.py:457-484` — existing AWS constants block.
- `packages/ai-parrot/src/parrot/interfaces/aws.py:10-14` — consumer import pattern.

---

## Acceptance Criteria

- [ ] `from parrot.conf import AWS_SESSION_TOKEN, ANTHROPIC_AWS_WORKSPACE_ID` works.
- [ ] Both default to `None` when the env vars are unset.
- [ ] Setting the env vars before import yields their values.
- [ ] `ruff check packages/ai-parrot/src/parrot/conf.py` clean (no new errors).

---

## Test Specification

```python
# packages/ai-parrot/tests/test_conf_aws_constants.py
import importlib

def test_constants_importable():
    from parrot.conf import AWS_SESSION_TOKEN, ANTHROPIC_AWS_WORKSPACE_ID  # noqa: F401

def test_default_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_AWS_WORKSPACE_ID", raising=False)
    import parrot.conf as conf
    importlib.reload(conf)
    assert conf.ANTHROPIC_AWS_WORKSPACE_ID is None
```

---

## Agent Instructions

Standard SDD flow: verify the contract, implement, make tests pass, move this file
to `sdd/tasks/completed/`, set status `done` in the per-spec index, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-10
**Notes**: Added `AWS_SESSION_TOKEN` and `ANTHROPIC_AWS_WORKSPACE_ID` to `conf.py` adjacent to existing AWS constants block, using `fallback=None` as required by navconfig. Pre-existing E402 ruff error in conf.py (line 443) is unrelated to this change.
**Deviations from spec**: none
