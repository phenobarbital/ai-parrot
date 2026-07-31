---
type: Wiki Overview
title: 'TASK-947: Migrate hard-coded model strings in handlers/chat.py and loaders/abstract.py'
id: doc:sdd-tasks-completed-task-947-migrate-chat-handler-and-loaders-defaults-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Two consumers in the codebase still hard-code soon-to-shutoff model IDs:'
relates_to:
- concept: mod:parrot.handlers.chat
  rel: mentions
- concept: mod:parrot.loaders.abstract
  rel: mentions
- concept: mod:parrot.models.openai
  rel: mentions
---

# TASK-947: Migrate hard-coded model strings in handlers/chat.py and loaders/abstract.py

**Feature**: FEAT-138 — OpenAI Model Deprecation Refresh
**Spec**: `sdd/specs/openai-model-deprecation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-944
**Assigned-to**: unassigned

---

## Context

Two consumers in the codebase still hard-code soon-to-shutoff model IDs:

- `parrot/handlers/chat.py:245,294,357` — `"gpt-4-turbo"` (shutoff
  2026-10-23).
- `parrot/loaders/abstract.py:156` — `model_name: str = "gpt-3.5-turbo"`
  (shutoff 2026-10-23).

Spec §3 Module 5 mandates migrating both as part of FEAT-138. The user
explicitly confirmed this in the /sdd-spec interview (item 3: "yes,
migrated").

Implements Module 5 of §3.

---

## Scope

- In `parrot/handlers/chat.py`: replace each occurrence of the literal
  `"gpt-4-turbo"` (3 sites) with `OpenAIModel.GPT5_MINI.value` (or
  the equivalent imported constant). Add the import if missing.
  **Two of the three sites are example payloads in docstrings** — keep
  the example syntactically valid; the lint check below catches issues.
- In `parrot/loaders/abstract.py:156`: change the default
  `model_name: str = "gpt-3.5-turbo"` to `model_name: str = "gpt-4.1-mini"`
  (per spec Module 5 rationale: cheap chat model still in current
  catalog, used only for token-counting / titling).

**NOT in scope**:
- Editing `pageindex/md_builder.py` or `pageindex/utils.py` — those use
  `"gpt-4o"` which is NOT on the deprecation table (spec §2 Integration
  Points marks them "review only").
- Editing `setup/providers/openai.py` — also "review only".
- Touching `parrot/clients/gpt.py` (TASK-945 / TASK-946).
- Touching `parrot/handlers/llm.py` (TASK-948).
- Writing tests (TASK-949).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/chat.py` | MODIFY | Replace 3 hard-coded `"gpt-4-turbo"` literals; add `OpenAIModel` import if needed. |
| `packages/ai-parrot/src/parrot/loaders/abstract.py` | MODIFY | Default `model_name="gpt-3.5-turbo"` → `"gpt-4.1-mini"`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Available after TASK-944:
from parrot.models.openai import OpenAIModel

# Verify whether handlers/chat.py already imports OpenAIModel:
#   grep -n "OpenAIModel" packages/ai-parrot/src/parrot/handlers/chat.py
# As of pre-task: NO occurrence — add the import.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/chat.py:245
"model": "gpt-4-turbo",            # in a payload-construction dict

# line 294 — inside a docstring example:
#   model: "gpt-4-turbo"

# line 357 — inside another docstring example:
#   model: "gpt-4-turbo"
```

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py:156
model_name: str = "gpt-3.5-turbo",
```

### Replacement Rules

| Site | Replace with |
|---|---|
| `chat.py:245` (executable code) | `OpenAIModel.GPT5_MINI.value` |
| `chat.py:294` (docstring example) | literal `"gpt-5-mini"` (keep it as a string for the example to parse) |
| `chat.py:357` (docstring example) | literal `"gpt-5-mini"` |
| `loaders/abstract.py:156` | `model_name: str = "gpt-4.1-mini"` |

### Does NOT Exist

- ~~`parrot.handlers.chat.DEFAULT_MODEL`~~ — no module-level constant; the literal lives inline at the call site.
- ~~`parrot.loaders.abstract.DEFAULT_MODEL_NAME`~~ — no constant.
- ~~`parrot.models.openai.GPT5_MINI`~~ — the bare module-level alias does not exist; access via `OpenAIModel.GPT5_MINI.value`.

### Pre-edit verification command

```bash
grep -n '"gpt-4-turbo"\|"gpt-3.5-turbo"' \
  packages/ai-parrot/src/parrot/handlers/chat.py \
  packages/ai-parrot/src/parrot/loaders/abstract.py
```

Expected output: 4 lines (chat.py:245, chat.py:294, chat.py:357,
loaders/abstract.py:156). After this task: 0 lines.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/src/parrot/handlers/chat.py — top of file
from parrot.models.openai import OpenAIModel   # NEW import

# line ~245 (executable):
payload = {
    "model": OpenAIModel.GPT5_MINI.value,
    ...
}
```

### Key Constraints

- Do NOT change the surrounding logic — this is a literal-swap task.
- Keep docstring examples valid by using the string `"gpt-5-mini"` (not
  `OpenAIModel.GPT5_MINI.value` — docstrings are inert text).
- For `loaders/abstract.py`, do NOT add an import; the value is just a
  string default.

### References in Codebase

- `packages/ai-parrot/src/parrot/handlers/chat.py:245,294,357` — call sites.
- `packages/ai-parrot/src/parrot/loaders/abstract.py:156` — call site.

---

## Acceptance Criteria

- [ ] `grep -n '"gpt-4-turbo"' packages/ai-parrot/src/parrot/handlers/chat.py`
      returns no hits.
- [ ] `grep -n '"gpt-3.5-turbo"' packages/ai-parrot/src/parrot/loaders/abstract.py`
      returns no hits.
- [ ] `from parrot.models.openai import OpenAIModel` is present at the
      top of `chat.py` (only if a new occurrence is needed).
- [ ] Both files import cleanly.
- [ ] No linting errors:
      `ruff check packages/ai-parrot/src/parrot/handlers/chat.py packages/ai-parrot/src/parrot/loaders/abstract.py`.

---

## Test Specification

Tests live in TASK-949. Smoke check:

```bash
source .venv/bin/activate
python -c "
from parrot.handlers.chat import *  # noqa
from parrot.loaders.abstract import *  # noqa
print('imports OK')
"
grep -c '"gpt-4-turbo"\|"gpt-3.5-turbo"' \
  packages/ai-parrot/src/parrot/handlers/chat.py \
  packages/ai-parrot/src/parrot/loaders/abstract.py
# expect: 0:0
```

---

## Agent Instructions

1. Verify TASK-944 in `sdd/tasks/completed/`.
2. Run the pre-edit verification command; confirm 4 hits.
3. Update `.index.json` → `"in-progress"`.
4. Apply the replacement table.
5. Re-run grep; confirm 0 hits.
6. Move file to `sdd/tasks/completed/`, update index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
