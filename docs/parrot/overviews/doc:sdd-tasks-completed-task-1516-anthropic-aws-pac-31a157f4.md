---
type: Wiki Overview
title: 'TASK-1516: Fold `aws` into the `[anthropic]` packaging extra'
id: doc:sdd-tasks-completed-task-1516-anthropic-aws-packaging-extra-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 6** of the spec. The Bedrock and AWS-workspace clients
  require
---

# TASK-1516: Fold `aws` into the `[anthropic]` packaging extra

**Feature**: FEAT-232 — Enable Anthropic AWS Bedrock & AWS-native Backends
**Spec**: `sdd/specs/enable-anthropic-aws-bedrock.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec. The Bedrock and AWS-workspace clients require
the AWS extra of the `anthropic` SDK (`anthropic[aws]`). Per the resolved
packaging decision (proposal §5), fold it into the existing `[anthropic]` extra
rather than creating a new install target. Imports stay lazy in `get_client()`.

---

## Scope

- In `packages/ai-parrot/pyproject.toml`, change the `anthropic` extra dependency
  from `anthropic[aiohttp]>=…` to `anthropic[aiohttp,aws]>=0.109.0,<1.0.0`.
- Apply the same change to the aggregate `llms` extra entry for anthropic.
- Ensure the version floor is `>=0.109.0` (AWS clients require it).

**NOT in scope**: code changes, conf, backends, factory.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | add `aws` to anthropic extra(s); floor `>=0.109.0` |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```toml
# packages/ai-parrot/pyproject.toml — COMMITTED state (worktree HEAD):
# line ~331:
anthropic = [
    "anthropic[aiohttp]>=0.105.0,<1.0.0",
]
# line ~360-363 (inside `llms`):
    "anthropic[aiohttp]>=0.105.0,<1.0.0",
```

### Does NOT Exist
- ~~A separate `[anthropic-aws]` extra~~ — do NOT create one (decision: fold into `[anthropic]`).

---

## Implementation Notes

### Key Constraints / Gotcha
- **Heads-up**: uncommitted WIP on `dev` already bumps these two lines to
  `>=0.109.0` (but does NOT add `,aws`). This worktree branches from the COMMITTED
  HEAD, so it still shows `>=0.105.0`. Make the edit to `anthropic[aiohttp,aws]>=0.109.0,<1.0.0`
  — this both adds the extra and converges on the WIP version. Expect a trivial
  merge with that WIP when it lands; the resolution is the line written here.
- Target string: `anthropic[aiohttp,aws]>=0.109.0,<1.0.0` in BOTH locations.

### References in Codebase
- `packages/ai-parrot/pyproject.toml:329-333` and `:355-365`.

---

## Acceptance Criteria

- [ ] Both anthropic dependency lines read `anthropic[aiohttp,aws]>=0.109.0,<1.0.0`.
- [ ] `pyproject.toml` parses (e.g. `python -c "import tomllib,pathlib; tomllib.loads(pathlib.Path('packages/ai-parrot/pyproject.toml').read_text())"`).
- [ ] No other extras altered.

---

## Test Specification

```python
# manual / CI check
import tomllib, pathlib
data = tomllib.loads(pathlib.Path("packages/ai-parrot/pyproject.toml").read_text())
opt = data["project"]["optional-dependencies"]
assert any("aws" in d and d.startswith("anthropic[") for d in opt["anthropic"])
```

---

## Agent Instructions

Standard SDD flow: verify the contract, implement, validate the toml parses, move
this file to `sdd/tasks/completed/`, set status `done` in the per-spec index, fill
the note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-10
**Notes**: Both `anthropic` and `llms` extra entries updated to `anthropic[aiohttp,aws]>=0.109.0,<1.0.0`. TOML validated.
**Deviations from spec**: none
