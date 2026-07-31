---
type: Wiki Overview
title: 'TASK-1320: Add `OutputMode.INFOGRAPHIC` + system prompt addon + AgentTalk
  hooks'
id: doc:sdd-tasks-completed-task-1320-output-mode-infographic-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 8 from the spec. Introduces the type-safe `OutputMode.INFOGRAPHIC`
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
- concept: mod:parrot.handlers.agent
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1320: Add `OutputMode.INFOGRAPHIC` + system prompt addon + AgentTalk hooks

**Feature**: FEAT-197 — Infographic Toolkit
**Spec**: `sdd/specs/infographictoolkit.spec.md` (Module 8)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1318
**Parallel**: false
**Assigned-to**: unassigned

---

## Context

Module 8 from the spec. Introduces the type-safe `OutputMode.INFOGRAPHIC`
enum value (consumed by `PandasAgent.ask` in TASK-1326 and the HTTP
formatter), the `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` injected when a client
sets `output_mode=infographic` without using a `/skill` trigger, and the
HTTP-layer plumbing: a new `_format_response` branch and a
`force-disable-streaming` rule for this mode.

The branch surfaces `AIMessage.artifact_id` (added in TASK-1318) so this
task depends on that one.

---

## Scope

- Add `INFOGRAPHIC = "infographic"` to `OutputMode` (`parrot/models/outputs.py`).
- Add `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` as a string constant in
  `parrot/bots/prompts/__init__.py`. It instructs the LLM to (a) fetch /
  compute DataFrames, (b) close the turn with `infographic_render(...)`.
  Final wording is in *Implementation Notes* below.
- In `parrot/handlers/agent.py`:
  - `AgentTalk.post()`: when the parsed request's `output_mode ==
    "infographic"`, inject `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` into the
    system prompt composition path the file already uses for other
    `OutputMode` cases. Force `stream=False` for the duration of that
    request.
  - `AgentTalk._format_response`: add an `OutputMode.INFOGRAPHIC` branch
    that emits the documented JSON envelope:
    ```json
    {
      "input": "...",
      "output": "<html_url or html_inline>",
      "output_mode": "infographic",
      "artifact_id": "...",
      "data": [ ... List[DatasetResult] ... ],
      "metadata": { "html_url": "...", "html_inline_omitted": false }
    }
    ```
    AND honour `Accept: text/html` / `?format=html` by returning the
    artifact HTML via `ArtifactStore.get_artifact(...).definition.html`
    (or a redirect to the public URL — pick redirect for simpler CSP).
- Unit tests covering the enum, the addon injection, the streaming
  force-disable, and the formatter branch JSON shape.

**NOT in scope**:
- `ArtifactStore.get_public_url` (TASK-1321) or the public route
  (TASK-1322). The formatter branch can call `get_public_url` once those
  land — for this task, mock it.
- `PandasAgent.ask` post-loop branch (TASK-1326).
- The enhance prompt template — TASK-1325 owns
  `INFOGRAPHIC_ENHANCE_PROMPT`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/outputs.py` | MODIFY | Add `INFOGRAPHIC = "infographic"` enum value. |
| `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` | MODIFY | Add `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` constant. |
| `packages/ai-parrot/src/parrot/handlers/agent.py` | MODIFY | Inject addon in `post()`; new `_format_response` branch; force-disable streaming. |
| `packages/ai-parrot/tests/unit/models/test_output_mode_infographic.py` | CREATE | Enum test. |
| `packages/ai-parrot/tests/unit/handlers/test_agent_format_infographic.py` | CREATE | Formatter branch + streaming + addon injection. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.outputs import OutputMode
# verified: packages/ai-parrot/src/parrot/models/outputs.py:39
# Existing values include: DEFAULT, JSON, TERMINAL, MARKDOWN, YAML, HTML,
# JINJA2, JUPYTER, NOTEBOOK, TEMPLATE_REPORT, APPLICATION, CHART, ALTAIR,
# PLOTLY, MATPLOTLIB, BOKEH, SEABORN, CODE, MAP, IMAGE, D3, ECHARTS, TABLE,
# HOLOVIEWS, CARD, TELEGRAM, MSTEAMS, WHATSAPP.

from parrot.bots.prompts import OUTPUT_SYSTEM_PROMPT
# verified: imported wherever output-mode-aware system prompts are composed
# (grep `OUTPUT_SYSTEM_PROMPT` to find composition sites). Add
# INFOGRAPHIC_SYSTEM_PROMPT_ADDON as a sibling constant.

from parrot.handlers.agent import AgentTalk
# verified: packages/ai-parrot/src/parrot/handlers/agent.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/agent.py
class AgentTalk(BaseView):
    async def post(self) -> web.Response: ...
    async def _format_response(
        self, response, output_format, format_kwargs,
        user_id, user_session, response_time_ms,
        agent_name, session_id, client_message_id,
    ) -> web.Response: ...
```

```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                  # line 72
    # ... existing fields ...
    artifact_id: Optional[str] = None    # added by TASK-1318
```

### Does NOT Exist
- ~~`OutputMode.INFOGRAPHIC`~~ — created by this task.
- ~~`INFOGRAPHIC_SYSTEM_PROMPT_ADDON`~~ — created by this task.
- ~~`AgentTalk._build_infographic_response`~~ — name the branch helper
  whatever you like, but the spec doesn't prescribe one. Keep it private.
- ~~A separate "infographic streaming" flag~~ — there is no flag; streaming
  is disabled by overriding the request's `stream` parameter in
  `post()` for this mode only.

---

## Implementation Notes

### `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` wording

Final wording is up to the implementer but MUST:
1. Tell the LLM to compute the DataFrames it needs via `python_repl_pandas`
   or `fetch_dataset`.
2. Tell the LLM the final tool call of the turn MUST be
   `infographic_render(template_name=..., theme=..., mode=..., blocks=[...],
   data_variables=[...])`.
3. Tell the LLM to use `infographic_list_templates` /
   `infographic_get_template_contract` first when uncertain about the
   positional block contract.
4. Tell the LLM that the result of `infographic_render` is returned
   verbatim — do NOT summarise.

Keep the addon ~250-400 tokens. It is appended *after* `OUTPUT_SYSTEM_PROMPT`
(or composed alongside it — look at how the other modes are stitched in
the same file).

### Streaming force-disable

In `AgentTalk.post()`, when `output_mode == OutputMode.INFOGRAPHIC`:

```python
if output_mode == OutputMode.INFOGRAPHIC:
    # Streaming is unsupported for this mode — the final envelope
    # must carry the signed URL.
    stream = False
```

Keep this near the existing parameter parsing block. Document the
override in a one-line comment.

### `_format_response` branch

Reuse the JSON branch's helpers. Emit `Content-Type: text/html` and the
artifact HTML body when `request.headers.get("Accept", "").startswith(
"text/html")` OR `request.query.get("format") == "html"`. For now,
return the inline HTML if `response.output` is HTML (length-checked) or
the `html_url` from `response.metadata` (populated by TASK-1326).

### Key Constraints
- DO NOT modify any other `OutputMode` branch's behaviour.
- DO NOT alter `OUTPUT_SYSTEM_PROMPT` itself.
- Keep `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` as a module-level string,
  exported in `__all__` if the module uses one.

---

## Acceptance Criteria

- [ ] `OutputMode("infographic") == OutputMode.INFOGRAPHIC`.
- [ ] `INFOGRAPHIC_SYSTEM_PROMPT_ADDON` is importable from
      `parrot.bots.prompts`.
- [ ] When `output_mode=infographic` and `stream=true`, the request is
      served non-streamed.
- [ ] `_format_response` returns the documented JSON shape with
      `output_mode == "infographic"` and surfaces `artifact_id`.
- [ ] `Accept: text/html` returns `Content-Type: text/html` with the HTML body.
- [ ] `pytest packages/ai-parrot/tests/unit/models/test_output_mode_infographic.py packages/ai-parrot/tests/unit/handlers/test_agent_format_infographic.py -v` passes.
- [ ] `ruff check` clean on all three modified files.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/models/test_output_mode_infographic.py
from parrot.models.outputs import OutputMode


def test_infographic_value():
    assert OutputMode("infographic") is OutputMode.INFOGRAPHIC
    assert OutputMode.INFOGRAPHIC.value == "infographic"


def test_existing_values_untouched():
    # spot-check a handful of pre-existing values to guard against
    # accidental deletion.
    for v in ("default", "json", "html", "map", "table", "telegram"):
        assert OutputMode(v) is not None
```

```python
# packages/ai-parrot/tests/unit/handlers/test_agent_format_infographic.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.models.outputs import OutputMode
from parrot.models.responses import AIMessage

# Pseudo-test outline; concrete fixtures depend on AgentTalk test harness.

@pytest.mark.asyncio
async def test_format_response_infographic_branch_json_shape():
    # Arrange a fake AIMessage with artifact_id, output=html_url, metadata.html_url.
    # Call AgentTalk._format_response with OutputMode.INFOGRAPHIC.
    # Assert the JSON body contains 'output_mode': 'infographic' and 'artifact_id'.
    ...


@pytest.mark.asyncio
async def test_format_response_infographic_accept_text_html():
    # Same fixture, set Accept: text/html → response Content-Type is text/html.
    ...


@pytest.mark.asyncio
async def test_post_forces_stream_false_for_infographic():
    # Send POST /api/v1/agents/talk/... with output_mode=infographic & stream=true.
    # Assert the agent.ask wrapper sees stream=False.
    ...


def test_system_prompt_addon_injected():
    from parrot.bots.prompts import INFOGRAPHIC_SYSTEM_PROMPT_ADDON
    assert "infographic_render" in INFOGRAPHIC_SYSTEM_PROMPT_ADDON
```

---

## Agent Instructions

1. Add the enum value first — many downstream tests depend on it.
2. Add the addon constant; confirm it imports cleanly.
3. Locate the existing `OutputMode.MAP` branch in `_format_response` and
   pattern-match the new INFOGRAPHIC branch after it.
4. Add the `stream` override in `post()` near the request parsing.
5. Run the new unit tests + the broader handler tests:
   `pytest packages/ai-parrot/tests/unit/handlers/ -v`.
6. Move to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*
