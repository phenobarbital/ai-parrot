# TASK-2857: Dual-emit routing rule in `PandasAgent` and `BaseBot` infographic finalizers

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2856
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 2, §3 Module 1, §7 "Double artefact in A2UI mode". Both bot post-loop
branches currently *switch* the response to `OutputMode.A2UI` whenever the
`InfographicRenderResult` carries an envelope — which, once TASK-2856 makes envelopes the
default, would silently drop the HTML `output` for every infographic turn. The resolved
U1 decision is dual-emit: the requested `output_mode` decides the primary shape and the
other emission rides along.

---

## Scope

Implement this rule in **both** finalizers:

```
if infographic_envelope is not None:
    if output_mode == OutputMode.A2UI:
        # A2UI-primary: envelope in a2ui_envelope; HTML artifact referenced in metadata
        explanation = <capture BEFORE anything overwrites response.output/response.response>
        response.a2ui_envelope = infographic_envelope.a2ui_envelope   # may be None → fall through to HTML rule
        response.artifact_id = infographic_envelope.artifact_id
        finalize_a2ui_response(response)
        response.metadata.update({"html_url": ..., "artifact_id": ..., "template_name": ..., "theme": ..., "enhanced": ...})
        if explanation: response.response = explanation
    else:
        # HTML-primary (default): existing _finalize_infographic_response, plus the envelope
        self._finalize_infographic_response(response, infographic_envelope)
        if infographic_envelope.a2ui_envelope is not None:
            response.a2ui_envelope = infographic_envelope.a2ui_envelope
```

- `packages/ai-parrot/src/parrot/bots/data.py:1886-1898` — replace the A2UI branch with the rule
  (keep `_inject_multi_data_from_variables` at `:1882-1885` before it; keep the early `return response`).
- `packages/ai-parrot/src/parrot/bots/base.py:1425-1435` — same rule (the `output_mode` local is in
  scope; see `:1436`).
- When `output_mode == A2UI` but the envelope build failed (`a2ui_envelope is None`), fall back to
  the HTML rule and log a warning — never return an A2UI response without an envelope.
- Tests in `tests/unit/bots/test_pandasagent_infographic.py` (extend) and a new
  `tests/unit/bots/test_basebot_infographic_dual_emit.py`.

**NOT in scope**: the toolkit default (TASK-2856), AgentTalk JSON envelope (TASK-2858),
`AbstractBot.get_infographic()` (spec Non-Goal), `interactive_envelope` handling (`data.py:1912+`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | post-loop rule `:1876-1910` |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | finalizer rule `:1425-1435` |
| `packages/ai-parrot/tests/unit/bots/test_pandasagent_infographic.py` | MODIFY | dual-emit default + A2UI-mode metadata tests |
| `packages/ai-parrot/tests/unit/bots/test_basebot_infographic_dual_emit.py` | CREATE | same two rules on `BaseBot` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.infographic_toolkit import InfographicRenderResult   # infographic_toolkit.py:159
from parrot.models.outputs import OutputMode                           # models/outputs.py:58,:64
from parrot.outputs.a2ui.emission import finalize_a2ui_response        # emission.py:18
from parrot.models.responses import AIMessage                          # models/responses.py:72
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py  (PandasAgent)
_InfographicRenderResult lazy import helper                                        # :49-61
def _extract_last_infographic_result(self, tool_calls) -> Optional[InfographicRenderResult]  # :977
def _finalize_infographic_response(self, response: Any, envelope: Any) -> Optional[str]      # :1000-1004 ; sets output/output_mode/artifact_id; returns explanation
# post-loop:
infographic_envelope = self._extract_last_infographic_result(response.tool_calls)  # :1880
await self._inject_multi_data_from_variables(response, infographic_envelope.data_variables)  # :1882-1885
if getattr(infographic_envelope, "a2ui_envelope", None) is not None: ... finalize_a2ui_response(response); return response  # :1890-1898 ← REPLACE
explanation = self._finalize_infographic_response(response, infographic_envelope)  # :1899 ; return response :1910
# `output_mode` local variable is in scope in this method (used at :1731-1733, :1805, :1942)

# packages/ai-parrot/src/parrot/bots/base.py  (BaseBot)
def _finalize_infographic_response(self, response, envelope) -> None   # :890 ; docstring :895-902 (aliasing gotcha) ; body :903-915
infographic_envelope = self._extract_last_infographic_result(getattr(response, "tool_calls", None))  # :1424
if getattr(infographic_envelope, "a2ui_envelope", None) is not None: response.a2ui_envelope = ...; finalize_a2ui_response(response)  # :1426-1428 ← REPLACE
else: self._finalize_infographic_response(response, infographic_envelope)   # :1429-1430
elif output_mode == OutputMode.INFOGRAPHIC: warning + output_mode = DEFAULT   # :1436-1442 (KEEP)
if interactive_envelope is not None or infographic_envelope is not None: pass  # skip formatter :1446-1447 (KEEP)

# packages/ai-parrot/src/parrot/outputs/a2ui/emission.py
def finalize_a2ui_response(response: Any) -> None   # :18 ; sets response.a2ui_envelope (from attr or output dict), output_mode=A2UI, and response.response ONLY if empty :43-45

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage: output_mode: OutputMode :220 ; artifact_id: Optional[str] :224 ; a2ui_envelope: Optional[Dict[str, Any]] :232 ; metadata dict (may be None — guard as base.py:912 does)

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicRenderResult(BaseModel): artifact_id, html_url, html_inline, template_name, theme, data_variables, enhanced, a2ui_envelope  # :159-172
```

### Does NOT Exist
- ~~`response.html_url`~~ on `AIMessage` — put it under `response.metadata["html_url"]`.
- ~~`finalize_infographic_response`~~ module-level function — it is a method on each bot class.
- ~~an `OutputMode.A2UI` streaming gate~~ — none; not this task's concern.
- ~~`AIMessage.explanation`~~ — the explanation lives on `response.response` (see `data.py:1000` docstring and `agent.py:3023`).

---

## Implementation Notes

### Pattern to Follow
`base.py:895-915` — capture `explanation` **before** overwriting `response.output`, because
`AIMessage.content` aliases `output`. Apply the same ordering in the A2UI-primary branch:
`finalize_a2ui_response` only fills `response.response` when empty, so set the captured
explanation afterwards.

### Key Constraints
- Keep the log lines' shape (`"InfographicRenderResult detected ... artifact_id=%s a2ui=%s"`), add
  the chosen primary mode to the message.
- `response.metadata` may be `None` — copy the `meta = dict(getattr(response, "metadata", None) or {})`
  idiom from `base.py:912`.
- Tests build `InfographicRenderResult(...)` directly and a `SimpleNamespace`/`MagicMock` response, as
  `test_pandasagent_infographic.py:8-43` already does; exercise both `output_mode=OutputMode.DEFAULT`
  and `OutputMode.A2UI`, plus the "A2UI requested but envelope None" fallback.

### References in Codebase
- `packages/ai-parrot/tests/unit/bots/test_pandasagent_infographic.py` — fixture style (module stubs, `SimpleNamespace`).
- `packages/ai-parrot/src/parrot/bots/data.py:1912-1930` — sibling `interactive_envelope` branch (do not modify).

---

## Acceptance Criteria

- [ ] Default mode: `output_mode == INFOGRAPHIC`, `output` is HTML/URL, `artifact_id` set, `a2ui_envelope` set (both bots)
- [ ] `output_mode=A2UI`: `finalize_a2ui_response` applied, `metadata.html_url` / `artifact_id` / `template_name` / `theme` present, explanation preserved on `response.response`
- [ ] `output_mode=A2UI` with `a2ui_envelope=None` → HTML rule + warning, never an envelope-less A2UI response
- [ ] Existing `test_pandasagent_infographic.py` tests still pass
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot/tests/unit/bots -q -k "infographic"` green; `ruff check packages/ai-parrot/src/parrot/bots/data.py packages/ai-parrot/src/parrot/bots/base.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_pandasagent_infographic.py (add)
def _render_result(with_envelope=True):
    return InfographicRenderResult(
        artifact_id="infographic-abc123def456", html_url="https://x/infographic-abc123def456.html",
        html_inline="<html>..</html>", template_name="basic", theme="light",
        a2ui_envelope={"version": "v1.0", "createSurface": {"surfaceId": "infographic-abc123def456", "components": []}} if with_envelope else None,
    )

def test_dual_emit_default_mode_keeps_html_primary(agent, response):
    # arrange post-loop with output_mode=OutputMode.DEFAULT and tool result _render_result()
    assert response.output_mode == OutputMode.INFOGRAPHIC
    assert response.output == "<html>..</html>"
    assert response.a2ui_envelope["createSurface"]["surfaceId"] == "infographic-abc123def456"

def test_dual_emit_a2ui_mode_adds_html_metadata(agent, response):
    # output_mode=OutputMode.A2UI
    assert response.output_mode == OutputMode.A2UI
    assert response.metadata["html_url"].endswith(".html")
    assert response.response  # explanation preserved

def test_a2ui_mode_without_envelope_falls_back_to_html(agent, response, caplog):
    assert response.output_mode == OutputMode.INFOGRAPHIC
    assert "falling back" in caplog.text.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2856 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `data.py:1876-1910` and `base.py:1424-1447` still match
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2857-bots-dual-emit-routing.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
