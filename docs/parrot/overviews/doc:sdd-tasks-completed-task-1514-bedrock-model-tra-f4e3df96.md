---
type: Wiki Overview
title: 'TASK-1514: Bedrock model-ID translator'
id: doc:sdd-tasks-completed-task-1514-bedrock-model-translator-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of the spec. Bedrock requires prefixed / inference-profile
relates_to:
- concept: mod:parrot.models.bedrock_models
  rel: mentions
- concept: mod:parrot.models.claude
  rel: mentions
---

# TASK-1514: Bedrock model-ID translator

**Feature**: FEAT-232 — Enable Anthropic AWS Bedrock & AWS-native Backends
**Spec**: `sdd/specs/enable-anthropic-aws-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. Bedrock requires prefixed / inference-profile
model IDs (e.g. `us.anthropic.claude-sonnet-4-5-20250929-v1:0`) while AI-Parrot
uses public IDs (`claude-sonnet-4-6`). This module is the standalone translator
the Bedrock backend (TASK-1517) will call. It does NOT touch `AnthropicClient`.

---

## Scope

- Implement a `translate(public_id: str, region_prefix: str | None = None) -> str`
  function (and any helper map) implementing **map + region-prefix + pass-through**:
  1. **Pass-through**: if `public_id` already looks like a Bedrock ID/ARN — starts
     with `arn:`, contains `anthropic.`, or begins with a known region prefix
     (`us.`/`eu.`/`apac.`) — return it verbatim.
  2. **Map**: look up the public ID in a static `dict[str, str]` mapping public →
     Bedrock base ID (`anthropic.<id>-v1:0` form).
  3. **Region prefix**: if `region_prefix` is provided (e.g. `"us"`), prepend
     `"<prefix>."` to the mapped base ID to form the cross-region inference profile.
  - On an unknown public ID (not in the map, not Bedrock-shaped): return it
    unchanged (best-effort pass-through) and log a warning — do NOT raise.
- Write unit tests for all three branches.

**NOT in scope**: backend objects, `AnthropicClient`, factory, conf, packaging.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/bedrock_models.py` | CREATE | translator + static map |
| `packages/ai-parrot/tests/test_bedrock_models.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.claude import ClaudeModel   # verified: packages/ai-parrot/src/parrot/models/claude.py:4
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/claude.py:4
class ClaudeModel(Enum):                        # line 4
    OPUS_4_6 = "claude-opus-4-6"                # line 13 — .value is the public ID string
    SONNET_4_6 = "claude-sonnet-4-6"            # line 14
    HAIKU_4_5 = "claude-haiku-4-5-20251001"     # line 18
    # ...committed members; build the map keyed on the .value strings.
```

### Does NOT Exist
- ~~`parrot.models.bedrock_models`~~ — this task CREATES it.
- ~~A pre-existing public→Bedrock map anywhere in the repo~~ — none exists (grep clean).
- Note: enum members `FABLE_5`, `OPUS_4_8`, `OPUS_4_7` may exist in uncommitted WIP
  and are NOT on this worktree's `claude.py`. Do not rely on them; the unknown-ID
  pass-through branch covers any not-yet-mapped IDs.

---

## Implementation Notes

### Key Constraints
- Pure functions; no async needed (no I/O). Module-level logger via `logging.getLogger(__name__)`.
- Keep the map explicit and documented; do not auto-derive from regex tricks.
- Bedrock base ID convention: `anthropic.<public-id>-v1:0` (e.g.
  `anthropic.claude-sonnet-4-5-20250929-v1:0`). The exact `-vN:0` suffixes are
  per-model — encode them in the map values, not by string-munging.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/claude.py` — source of public IDs (`.value`).

---

## Acceptance Criteria

- [ ] `translate("claude-sonnet-4-6")` returns the mapped Bedrock base ID.
- [ ] `translate("claude-sonnet-4-6", region_prefix="us")` prepends `us.`.
- [ ] `translate("us.anthropic.claude-...-v1:0")` and `translate("arn:aws:...")` return verbatim.
- [ ] Unknown public ID returns unchanged + logs a warning (no exception).
- [ ] `pytest packages/ai-parrot/tests/test_bedrock_models.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/models/bedrock_models.py` clean.
- [ ] `from parrot.models.bedrock_models import translate` works.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_bedrock_models.py
from parrot.models.bedrock_models import translate


def test_map_public_to_bedrock():
    out = translate("claude-sonnet-4-6")
    assert "anthropic." in out and out.endswith(":0")

def test_region_prefix():
    assert translate("claude-sonnet-4-6", region_prefix="us").startswith("us.anthropic.")

def test_passthrough_bedrock_id():
    bid = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert translate(bid) == bid

def test_passthrough_arn():
    arn = "arn:aws:bedrock:us-east-1::inference-profile/us.anthropic.claude-x"
    assert translate(arn) == arn

def test_unknown_passthrough(caplog):
    assert translate("claude-made-up-99") == "claude-made-up-99"
```

---

## Agent Instructions

Standard SDD flow: verify the contract, implement, make tests pass, move this file
to `sdd/tasks/completed/`, set status `done` in the per-spec index, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-10
**Notes**: Created `bedrock_models.py` with `PUBLIC_TO_BEDROCK` static map and `translate()` function implementing all three branches (pass-through, map, region-prefix). 11 unit tests pass, ruff clean.
**Deviations from spec**: none
