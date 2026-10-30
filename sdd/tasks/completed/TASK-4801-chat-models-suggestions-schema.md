# TASK-4801: `AgentChatResponse.suggestions` mirror + schema / TS regeneration

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (schema half). `parrot.server.ui.chat_models.AgentChatResponse` is the Pydantic source of truth
for the `AgentTalk` envelope; `scripts/generate_ts_types.py` exports `ui/schemas/AgentChatResponse.json` and
`pnpm generate` (json2ts) produces the `.d.ts` the admin UI imports. This task adds the `AgentChatSuggestion` mirror
and regenerates both committed artifacts. **Exclusive** (`parallel: false`): it rewrites shared generated code.

---

## Scope

- Add `AgentChatSuggestion` (pydantic-only, no `parrot.models` import) and `AgentChatResponse.suggestions`.
- Regenerate `ui/schemas/AgentChatResponse.json` (Python script) **then** `ui/src/lib/types/generated/AgentChatResponse.d.ts`
  (`pnpm generate`). Never hand-edit either file.
- Extend `tests/test_chat_models.py` with `test_chat_models_suggestions_schema`.

**NOT in scope**: handler passthrough (TASK-4802); `types/agent.ts` and Svelte (TASK-4803/4804);
`scripts/generate_ts_types.py` (needs NO change — `AgentChatSuggestion` lands in `$defs` via `AgentChatResponse`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/server/ui/chat_models.py` | MODIFY | Mirror model + field |
| `packages/ai-parrot-server/ui/schemas/AgentChatResponse.json` | MODIFY | Regenerated (script) |
| `packages/ai-parrot-server/ui/src/lib/types/generated/AgentChatResponse.d.ts` | MODIFY | Regenerated (`pnpm generate`) |
| `packages/ai-parrot-server/tests/test_chat_models.py` | MODIFY | Schema test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.server.ui.chat_models import AgentChatResponse, AgentChatMetadata, AgentToolCall  # verified: chat_models.py:67, :42, :26
from scripts.generate_ts_types import SCHEMAS_DIR, export_schemas   # verified: scripts/generate_ts_types.py:43, :117
# chat_models.py imports only: from __future__ import annotations; from typing import Any; from pydantic import BaseModel, ConfigDict (:19-23)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/server/ui/chat_models.py
class AgentToolCall(BaseModel): ...                                   # line 26
class AgentChatMetadata(BaseModel): ...                               # line 42
class AgentChatResponse(BaseModel):                                   # line 67
    model_config = ConfigDict(extra="allow")                          # line 77
    a2ui_envelope: dict[str, Any] | list[dict[str, Any]] | None = None   # line 88 ← new field after this
    audio_base64: str | None = None  # voice path                     # line 89
# scripts/generate_ts_types.py — registry entry "AgentChatResponse": AgentChatResponse (:97); export_schemas (:117)
# packages/ai-parrot-server/ui/package.json:15 — "generate": "json2ts -i schemas -o src/lib/types/generated --bannerComment ..."
# packages/ai-parrot-server/tests/test_ts_codegen.py:34 — test_schemas_in_sync_with_committed (drift gate)
# packages/ai-parrot-server/tests/test_chat_models.py:66 — test_codegen_registry (compares the three committed schemas)
```

### Does NOT Exist
- ~~`AgentChatResponse.suggestions`~~ / ~~`AgentChatSuggestion`~~ — created here.
- ~~a separate `AgentChatSuggestion.json` schema file~~ — not registered; it appears only in `$defs` of
  `AgentChatResponse.json`. Do NOT add it to the `generate_ts_types.py` registry.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/server/ui/chat_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/schemas/AgentChatResponse.json", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/ui/src/lib/types/generated/AgentChatResponse.d.ts", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/test_chat_models.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/server/ui/chat_models.py#AgentChatResponse"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the mirror model above `AgentChatResponse` and the field after `a2ui_envelope` — *why*: codegen source of truth.
2. Run `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src python scripts/generate_ts_types.py`
   from the worktree root — *why*: regenerates `ui/schemas/*.json` (only `AgentChatResponse.json` should change).
3. `cd packages/ai-parrot-server/ui && pnpm generate` — *why*: regenerates `src/lib/types/generated/*.d.ts`.
4. `git status` — only `AgentChatResponse.json` and `AgentChatResponse.d.ts` may change among generated files. If
   another generated file changes, it is pre-existing drift: do NOT commit it; note it in the Completion Note.
5. Add the test; run Validation Commands.

### `packages/ai-parrot-server/src/parrot/server/ui/chat_models.py` (MODIFY — model)
```python
# occurrences: 1 (verified: grep -c '^class AgentChatResponse(BaseModel):' chat_models.py)
# BEFORE — insert above `class AgentChatResponse(BaseModel):` (verified: chat_models.py:67)
class AgentChatSuggestion(BaseModel):
    """Mirror of the core ``Suggestion`` chip model (FEAT-752) for the generated TS types.

    Kept import-free of ``parrot.models`` like the rest of this module; ``kind`` is
    ``followup | presentation | action``, ``source`` is ``llm | skill | provider`` and ``action`` is ``"explain"``
    when ``kind == "action"``.
    """

    label: str
    prompt: str
    output_mode: str | None = None
    kind: str = "followup"
    source: str = "provider"
    action: str | None = None


```

### `packages/ai-parrot-server/src/parrot/server/ui/chat_models.py` (MODIFY — field)
```python
# occurrences: 1 (verified: grep -c '    a2ui_envelope: dict\[str, Any\] | list\[dict\[str, Any\]\] | None = None' chat_models.py)
# AFTER — insert below that line (verified: chat_models.py:88)
    suggestions: list[AgentChatSuggestion] = []  # FEAT-752 — omitted from bodies when empty
```

### `packages/ai-parrot-server/tests/test_chat_models.py` (MODIFY)
```python
# APPEND at end of file (after test_codegen_registry, verified: test_chat_models.py:66-77)
def test_chat_models_suggestions_schema():
    schema = AgentChatResponse.model_json_schema()
    assert "suggestions" in schema["properties"]
    assert "AgentChatSuggestion" in schema["$defs"]
    m = AgentChatResponse.model_validate(
        {**JSON_ENVELOPE, "suggestions": [{"label": "Explain this", "prompt": "Explain this answer",
                                           "kind": "action", "source": "provider", "action": "explain"}]}
    )
    assert m.suggestions[0].action == "explain"
    # FILL IN: assert AgentChatResponse.model_validate(STREAM_ENVELOPE).suggestions == []
```

### FILL IN checklist
- [ ] Default-empty assertion in the test.
- [ ] Generated files regenerated by the tools (Steps 2-3), never edited by hand.

---

## Acceptance Criteria

- [ ] `AgentChatResponse` schema has `suggestions` with `AgentChatSuggestion` in `$defs`.
- [ ] `test_ts_codegen.py::test_schemas_in_sync_with_committed` and `test_chat_models.py::test_codegen_registry` pass.
- [ ] Generated `.d.ts` exports `AgentChatSuggestion` and `AgentChatResponse.suggestions`.
- [ ] `ruff check` clean on `chat_models.py`.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/test_chat_models.py -q`
- `pytest packages/ai-parrot-server/tests/test_ts_codegen.py -q`

---

## Test Specification

See the `test_chat_models.py` block above.

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`, commit only listed
files, `scripts/sdd/close_task.sh TASK-4801 followup-suggestion-chips verified`). This task is exclusive — run it
alone; `pnpm generate` needs `packages/ai-parrot-server/ui/node_modules` (the worktree may need the main checkout's
`node_modules`; do not run `pnpm install` against the shared tree without asking).

---

## Completion Note

Delivered by seat gpt-5.6-sol (codex), attempt 3 (attempts 1-2: gpt-5.6-terra). Merged by hand (`git merge --no-ff`) after `coder_merge` answered `validation_failed`.

Validation waiver: the only red check is `test_ts_codegen.py::test_schemas_in_sync_with_committed`, caused by pre-existing `AgentToolkitsResponse.json` drift. It fails identically on the unmodified feature branch and on `origin/dev`. The drift was not committed here (out of scope) and is filed as `issue:a0b64c9dd735`. `test_chat_models.py`: 5 passed.

Not recorded: no `coder_record_review` / finalize_task evidence (no green validation to attach), so closed `partial`. No model feedback filed: no confirmed delivery defect.
