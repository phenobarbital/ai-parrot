# TASK-2590: Chat envelope Pydantic models + TypeScript codegen registration

**Feature**: FEAT-476 — AgentChat Migration
**Spec**: `sdd/specs/agentchat-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Envelope codegen" / §2 Data Models / §3 Module 0. `AgentTalk`
builds its response envelope as a plain dict in two places (stream
finaliser and JSON formatter). The Admin UI must consume that envelope
through **generated** TypeScript types instead of the hand-copied
`types/agent.ts` shapes from navigator. This task adds the Pydantic
models, registers them in the FEAT-468 codegen script, regenerates the
committed schemas/types, and adds a contract test so drift between the
dict builders and the model fails CI. `AgentTalk` is **not** modified.

Python-only; can run before (and in parallel with) every UI task.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/server/ui/chat_models.py`
  with `AgentToolCall`, `AgentChatMetadata`, `AgentChatResponse` exactly
  as in spec §2 Data Models (`extra="allow"`, all non-core fields
  optional; `metadata` required).
- Register the three models in `scripts/generate_ts_types.py::_models()`
  under the names `"AgentChatResponse"`, `"AgentChatMetadata"`,
  `"AgentToolCall"`.
- Regenerate `packages/ai-parrot-server/ui/schemas/*.json` (`python
  scripts/generate_ts_types.py`) and `ui/src/lib/types/generated/*.d.ts`
  (`pnpm generate` inside `packages/ai-parrot-server/ui`); commit both.
- Add `packages/ai-parrot-server/tests/test_chat_models.py` (see Test
  Specification).
- Google-style docstrings on every model; module docstring pointing at
  the two builder sites in `agent.py`.

**NOT in scope**: touching `handlers/agent.py`; any `ui/src` file other
than `types/generated/` (TASK-2592 rewires `types/agent.ts`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/server/ui/chat_models.py` | CREATE | three Pydantic models |
| `scripts/generate_ts_types.py` | MODIFY | add three entries to `_models()` |
| `packages/ai-parrot-server/ui/schemas/AgentChatResponse.json`, `AgentChatMetadata.json`, `AgentToolCall.json` | CREATE (generated) | committed JSON Schema |
| `packages/ai-parrot-server/ui/src/lib/types/generated/AgentChatResponse.d.ts` (+ nested) | CREATE (generated) | `pnpm generate` output |
| `packages/ai-parrot-server/tests/test_chat_models.py` | CREATE | contract tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict          # as used in packages/ai-parrot-server/src/parrot/server/ui/models.py:17
from parrot.server.ui.models import BotAgentItem, BotsListResponse   # models.py:20,39 (pattern to copy)
from parrot.server.ui.status import AdminStatus, AgentCounts, DependencyHealth  # scripts/generate_ts_types.py:55
from parrot.server.ui.chat_models import AgentToolCall, AgentChatMetadata, AgentChatResponse  # CREATED BY THIS TASK
```

### Existing Signatures to Use
```python
# scripts/generate_ts_types.py
SCHEMAS_DIR = REPO_ROOT / "packages" / "ai-parrot-server" / "ui" / "schemas"        # line 42
def _models() -> dict[str, type[BaseModel]]:                                       # line 45 — lazy imports at 54-55, registry dict at 57-63
def export_schemas(output_dir: Path = SCHEMAS_DIR) -> dict[str, Path]:             # line 66 — model.model_json_schema() at 79
def main() -> int:                                                                 # line 90

# packages/ai-parrot-server/src/parrot/server/ui/models.py:20-36 — pattern
class BotAgentItem(BaseModel):
    model_config = ConfigDict(extra="allow")   # 33
    name: str                                  # 35
    source: Literal["database", "registry"]    # 36

# packages/ai-parrot-server/src/parrot/handlers/agent.py — the two dict builders the models MUST mirror (read them before coding)
#   stream finaliser 2556-2600:  envelope = {"input", "output", "metadata": {model, provider, session_id, turn_id, user_id,
#     response_time, usage, finish_reason, stop_reason}, "sources": [dict…], "tool_calls": [{name,status,output,arguments}]}
#     + optional envelope["a2ui_envelope"] (2596-2598); written after b"\n\x00" (2599-2600)
#   JSON formatter (_format_response, def at 2685) 2777-2823: obj_response = {"input","output","data","response","output_mode",
#     "code","metadata": {… + "created_at"}, "sources", "tool_calls"} + optional "a2ui_envelope" (2819-2823)
#   voice path adds "audio_base64"/"audio_format" (handlers/agent_voice.py — AgentVoiceTalk(AgentTalk) at 57)

# packages/ai-parrot-server/ui/package.json — "generate": json2ts -i schemas -o src/lib/types/generated --bannerComment "// GENERATED …"
```

### Does NOT Exist
- ~~`parrot.server.ui.chat_models`~~ — created by this task.
- ~~A Pydantic envelope in `handlers/agent.py`~~ — only `PausedEnvelope(BaseModel)` (line 74) exists there; do not import or reuse it.
- ~~`AgentTalk.response_model` / any builder returning a model~~ — the builders return dicts; do not refactor them.
- ~~`ui/src/lib/types/generated/AgentChatResponse.d.ts` on `dev`~~ — produced by `pnpm generate` in this task.

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot-server/src/parrot/server/ui/models.py:20-36 — permissive model with pinned core fields
class BotAgentItem(BaseModel):
    """…"""
    model_config = ConfigDict(extra="allow")
    name: str
    source: Literal["database", "registry"]
```

### Key Constraints
- `AgentChatResponse.metadata` is required; every other field optional
  with the defaults from spec §2 Data Models (`sources: list[dict] =
  []`, `tool_calls: list[AgentToolCall] = []`, `a2ui_envelope: dict |
  list[dict] | None`).
- `AgentChatMetadata.session_id`/`turn_id` default `""` (builders emit
  `str(... or "")`).
- Do not add validators that would reject today's builder output (e.g.
  `output` may be `str | dict | list | None`).
- Run codegen from the repo root with `PYTHONPATH` per the script's
  own header comment (lines 10-28), then `pnpm generate` in `ui/`.
- `ruff check` clean; type hints strict.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/server/ui/models.py` — model style
- `packages/ai-parrot-server/src/parrot/server/ui/status.py` — second registered model set
- `scripts/generate_ts_types.py` — registry
- `docs/admin-ui.md` §"Codegen (`pnpm generate`)" (line 107)

---

## Acceptance Criteria

- [ ] `from parrot.server.ui.chat_models import AgentChatResponse, AgentChatMetadata, AgentToolCall` works
- [ ] `python scripts/generate_ts_types.py` writes the three schema files; `pnpm generate` emits the `.d.ts`; both committed
- [ ] `pytest packages/ai-parrot-server/tests/test_chat_models.py -v` passes
- [ ] `git diff --stat packages/ai-parrot-server/src/parrot/handlers/agent.py` is empty
- [ ] `ruff check packages/ai-parrot-server/src/parrot/server/ui/chat_models.py scripts/generate_ts_types.py` clean

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_chat_models.py
import json
from pathlib import Path
import pytest
from parrot.server.ui.chat_models import AgentChatResponse, AgentChatMetadata, AgentToolCall

STREAM_ENVELOPE = {  # mirrors handlers/agent.py:2556-2600
    "input": "hi", "output": "hello",
    "metadata": {"model": "m", "provider": "p", "session_id": "s", "turn_id": "t", "user_id": None,
                 "response_time": 12, "usage": None, "finish_reason": None, "stop_reason": None},
    "sources": [], "tool_calls": [{"name": "x", "status": "completed", "output": None, "arguments": None}],
}
JSON_ENVELOPE = {**STREAM_ENVELOPE, "data": None, "response": "hello", "output_mode": "json", "code": None,
                 "metadata": {**STREAM_ENVELOPE["metadata"], "created_at": "2026-08-30T00:00:00"},
                 "a2ui_envelope": {"version": "v1.0"}}

def test_stream_envelope_validates():
    m = AgentChatResponse.model_validate(STREAM_ENVELOPE)
    assert m.response is None and m.tool_calls[0].name == "x"

def test_json_envelope_validates():
    m = AgentChatResponse.model_validate(JSON_ENVELOPE)
    assert m.metadata.created_at and m.a2ui_envelope == {"version": "v1.0"}

def test_voice_fields_and_extras():
    m = AgentChatResponse.model_validate({**JSON_ENVELOPE, "audio_base64": "AAA", "audio_format": "audio/wav",
                                          "metadata": {**JSON_ENVELOPE["metadata"], "explanation": "e", "html_url": "u"}})
    assert m.audio_format == "audio/wav" and m.metadata.model_extra["html_url"] == "u"

def test_codegen_registry(tmp_path: Path):
    import importlib, sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    gen = importlib.import_module("scripts.generate_ts_types")
    names = set(gen._models())
    assert {"AgentChatResponse", "AgentChatMetadata", "AgentToolCall"} <= names
    written = gen.export_schemas(tmp_path)
    committed = Path(gen.SCHEMAS_DIR)
    for name in ("AgentChatResponse", "AgentChatMetadata", "AgentToolCall"):
        assert json.loads(written[name].read_text()) == json.loads((committed / f"{name}.json").read_text())
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — read `agent.py:2556-2600` and `2777-2823` before writing the models
4. **Update status** in `sdd/tasks/index/agentchat-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2590-chat-envelope-models-codegen.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
