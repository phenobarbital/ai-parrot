---
type: Wiki Overview
title: 'TASK-1738: Emission wiring: OutputMode.A2UI + AIMessage carrier + bot/handler
  routing'
id: doc:sdd-tasks-completed-task-1738-emission-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 10** of the spec (§3, "Emission wiring"). Everything
  built so
relates_to:
- concept: mod:parrot.handlers.agent
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.outputs.a2ui
  rel: mentions
- concept: mod:parrot.utils
  rel: mentions
---

# TASK-1738: Emission wiring: OutputMode.A2UI + AIMessage carrier + bot/handler routing

**Feature**: FEAT-273 — A2UI Protocol Integration — Rendering Core (parrot.outputs.a2ui)
**Spec**: sdd/specs/a2ui-implementation.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1720, TASK-1723, TASK-1729
**Assigned-to**: unassigned

---

## Context

Implements **Module 10** of the spec (§3, "Emission wiring"). Everything built so
far — envelope models (TASK-1720), catalog, renderer registry — is inert until an
envelope can actually travel from a bot to a client. This task adds the transport
plumbing: a new `OutputMode.A2UI` member, a dedicated `AIMessage.a2ui_envelope`
carrier field (spec decision: `output` stays untouched for legacy consumers), a
routing branch in `bots/base.py` that sends A2UI outputs **around** the legacy
`OutputFormatter`, and emission in both AgentTalk response paths (non-stream and
chunked-stream final envelope dict).

Per the resolved OQ-D (spec §8), delivery is **envelope-complete per output**: one
whole `CreateSurface` envelope per response. No incremental `updateComponents`
streaming (FEAT-B territory).

---

## Scope

- Add an `A2UI = "a2ui"` member to `OutputMode` in
  `packages/ai-parrot/src/parrot/models/outputs.py`.
- Add `a2ui_envelope: Optional[Dict[str, Any]]` field (default `None`) to
  `AIMessage` in `packages/ai-parrot/src/parrot/models/responses.py`.
- In `packages/ai-parrot/src/parrot/bots/base.py`, route `OutputMode.A2UI`
  **around** the legacy formatter at BOTH call sites (`await
  self.formatter.format(` at :487 and :1431): when `output_mode ==
  OutputMode.A2UI`, the response's envelope is placed in
  `response.a2ui_envelope` and `response.output_mode = OutputMode.A2UI` is set;
  `self.formatter.format(...)` must NEVER be entered for this mode.
- In `packages/ai-parrot-server/src/parrot/handlers/agent.py` (AgentTalk):
  - Non-stream path: surface `a2ui_envelope` in the response built via
    `_prepare_response` (:541) / `_format_response` (:2871).
  - Chunked-stream path: add the `a2ui_envelope` key to the final envelope dict
    built in `_handle_stream_response` (:2753-2785, written after separator
    `b'\n\x00'` at :2786). The existing chunked contract — header
    `'X-Parrot-Stream': 'chunked-aimessage'` (:2716), text chunks, separator,
    final JSON dict — must remain byte-compatible for non-A2UI responses and
    structurally unchanged (same header, same separator, one extra key) for A2UI
    responses.
- Write tests for routing-around-formatter and for the envelope-complete stream
  contract.

**NOT in scope**:
- Concrete renderers, baking, `RenderedArtifact` (Modules 5-6 / other tasks).
- LLM producer / validate-retry loop (Module 9).
- Tool builders migration (TASK-1739).
- Deprecation warnings on legacy modes (TASK-1740).
- A2A extension emit (TASK-1741).
- Incremental `updateComponents` streaming — explicitly excluded in v1 (OQ-D).
- Any change to how legacy `OutputMode` values are formatted or streamed.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/outputs.py` | MODIFY | Add `A2UI` member to `OutputMode` |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | Add `a2ui_envelope` field to `AIMessage` |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | A2UI branch before both formatter call sites |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | Emit envelope in non-stream + chunked-stream final dict |
| `packages/ai-parrot/tests/outputs/a2ui/test_emission_wiring.py` | CREATE | Unit tests (routing, AIMessage field) |
| `packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py` | CREATE | Stream-contract integration test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified 2026-07-10 against `dev`. Use these exact references.
> If anything drifted, re-verify with `grep` before implementing.

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredOutputConfig  # models/outputs.py
from parrot.models.responses import AIMessage                          # models/responses.py:72
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/outputs.py:36
class OutputMode(str, Enum):
    # existing members DEFAULT ... STRUCTURED_MAP (:69, last member); add A2UI here
    ...

# packages/ai-parrot/src/parrot/models/responses.py:72 — class AIMessage(BaseModel)
#   output: Any                       (:79)
#   response: Optional[str]           (:82)
#   files: Optional[List[Path]]       (:102)
#   artifacts: List[Dict[str, Any]]   (:206)
#   output_mode: OutputMode           (:210)
#   artifact_id: Optional[str]        (:214)
#   → new field a2ui_envelope: Optional[Dict[str, Any]] goes alongside these

# packages/ai-parrot/src/parrot/bots/base.py — the two legacy formatter call sites
#   :481  if output_mode != OutputMode.DEFAULT:            (ask path)
#   :487      content, wrapped = await self.formatter.format(output_mode, response, **format_kwargs)
#   :1425 elif output_mode != OutputMode.DEFAULT:          (second path; preceded by a
#         channel-egress branch for TELEGRAM/MSTEAMS/SLACK/WHATSAPP ~:1414-1423)
#   :1431     content, wrapped = await self.formatter.format(output_mode, response, **format_kwargs)
# The A2UI branch must be evaluated BEFORE these `!= DEFAULT` fallthroughs at both sites.

# packages/ai-parrot-server/src/parrot/handlers/agent.py
#   class AgentTalk(BaseView)                     (:102)
#   def _prepare_response(...)                    (:541)   — non-stream shaping
#   def _format_response(...)                     (:2871)  — non-stream serialization
#   async def _handle_stream_response(...)        (:2674)  — chunked streaming
#   'X-Parrot-Stream': 'chunked-aimessage'        (:2716)  — response header, MUST NOT change
#   final envelope dict built                     (:2753-2785) — keys: input, output,
#       metadata{model, provider, session_id, turn_id, user_id, response_time,
#       usage, finish_reason, stop_reason}, sources, tool_calls
#   separator = b'\n\x00'                         (:2786)  — MUST NOT change
```

### Does NOT Exist
- ~~`OutputMode.A2UI`~~ — does not exist yet; this task creates it.
- ~~`AIMessage.a2ui_envelope`~~ — does not exist yet; this task creates it.
- ~~SSE in AgentTalk~~ — chunked HTTP only; the WS loop lives in `handlers/stream.py`. Do not add SSE.
- ~~A renderer for `OutputMode.CHART`~~ — `_MODULE_MAP` maps it but nothing registers; `INTERACTIVE`, `CODE`, `IMAGE`, `SQL_ANALYSIS`, `TELEGRAM`, `MSTEAMS`, `JUPYTER`, `NOTEBOOK` have no renderer entries. Do not "fix" these while touching routing.
- ~~Incremental `updateComponents` dispatch~~ — schema exists (TASK-1720) but no dispatch in v1.

---

## Implementation Notes

### Pattern to Follow
- Mirror how the existing channel-egress branch (`bots/base.py` ~:1414) short-
  circuits specific modes before the generic `elif output_mode !=
  OutputMode.DEFAULT` formatter fallthrough — A2UI is another explicit branch
  that bypasses `self.formatter`.
- In `_handle_stream_response`, the envelope dict fields are read defensively
  with `getattr(ai_message, ..., None)`; follow the same defensive style for
  `a2ui_envelope` so older `AIMessage` instances (e.g. cached/deserialized) do
  not break streaming.

### Key Constraints
- **G1 survives here**: the A2UI path carries a validated envelope dict as
  data — never HTML, never code. No call into `OutputFormatter`,
  `get_renderer`, or `BaseRenderer.execute_code`.
- **Envelope-complete per output**: exactly one envelope per response; it rides
  only the final stream dict, never intermediate text chunks.
- Chunked contract is a public wire contract: header name/value, separator
  bytes, and all existing envelope keys unchanged. Adding `a2ui_envelope`
  (null for legacy modes is acceptable; omitting the key for legacy responses
  is also acceptable — pick one and test it).
- `AIMessage.output` / `.response` semantics for legacy consumers are
  untouched; for A2UI responses populate a human-readable fallback in
  `response` (e.g. surface title/summary) rather than leaving it `None`, but
  do NOT serialize the envelope into `output`.
- Async throughout; `self.logger` for diagnostics; no prints.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/base.py:481-497, 1414-1440` — routing seams
- `packages/ai-parrot-server/src/parrot/handlers/agent.py:2674-2790` — stream seam
- `packages/ai-parrot/src/parrot/outputs/a2ui/models.py` — envelope models (TASK-1720)

---

## Acceptance Criteria

- [ ] `OutputMode.A2UI` exists and round-trips as `"a2ui"` (str enum).
- [ ] `AIMessage` accepts and serializes `a2ui_envelope`; default is `None` and
      legacy construction paths are unaffected.
- [ ] With `output_mode=OutputMode.A2UI`, `OutputFormatter.format` is never
      invoked at either `bots/base.py` call site.
- [ ] Non-stream AgentTalk response includes the envelope for A2UI outputs.
- [ ] Chunked-stream final dict includes `a2ui_envelope`; header
      `X-Parrot-Stream: chunked-aimessage` and separator `b'\n\x00'` unchanged.
- [ ] Legacy modes stream/format byte-identically to before (regression tests pass).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_emission_wiring.py packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models packages/ai-parrot/src/parrot/bots/base.py`
- [ ] Full legacy test suite still green (G7).

---

## Test Specification

> Minimal scaffold — names and intent only; the agent writes the bodies.

```python
# packages/ai-parrot/tests/outputs/a2ui/test_emission_wiring.py

class TestOutputModeA2UI:
    def test_output_mode_a2ui_member(self):
        """OutputMode.A2UI exists with value 'a2ui' and is a str enum member."""

    def test_aimessage_a2ui_envelope_field(self):
        """AIMessage accepts a2ui_envelope dict; defaults to None; model_dump includes it."""

class TestA2UIRouting:
    async def test_output_mode_a2ui_routes_around_formatter(self):
        """OutputMode.A2UI never enters OutputFormatter.format (spy on formatter at
        both bots/base.py call-site paths); envelope lands in response.a2ui_envelope."""

    async def test_legacy_mode_still_uses_formatter(self):
        """A non-A2UI mode (e.g. OutputMode.JSON) still calls formatter.format —
        routing regression guard."""


# packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py

class TestA2UIStreamContract:
    async def test_e2e_ask_stream_envelope_complete(self):
        """ask_stream emits one complete envelope in the final chunk dict under
        'a2ui_envelope'; chunked contract unchanged: X-Parrot-Stream header value
        'chunked-aimessage' and b'\\n\\x00' separator preserved; no envelope
        fragments in intermediate text chunks."""

    async def test_non_stream_response_carries_envelope(self):
        """Non-stream AgentTalk response includes a2ui_envelope for A2UI output_mode."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1738-emission-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-11
**Notes**: Added `OutputMode.A2UI = "a2ui"` (outputs.py) and
`AIMessage.a2ui_envelope: Optional[Dict[str, Any]] = None` (responses.py). In
`bots/base.py`, added an A2UI branch BEFORE both `self.formatter.format(...)` call
sites (:484 ask path, :1431 second path) that calls `finalize_a2ui_response(response)`
and never enters the formatter. In `handlers/agent.py`: the chunked-stream final dict
gains `a2ui_envelope` via `getattr(ai_message, 'a2ui_envelope', None)` (defensive; only
added when non-null) with the `X-Parrot-Stream: chunked-aimessage` header and `b'\n\x00'`
separator untouched; the non-stream `_format_response` gains an `OutputMode.A2UI` branch
returning the envelope as JSON. 80 core a2ui tests pass (incl. new emission-wiring unit
tests); 4 server contract tests pass; ruff clean on changed files.

**Deviations from spec**: (1) The pure routing helper lives in a new core module
`parrot/outputs/a2ui/emission.py` (`finalize_a2ui_response`) rather than as a private
function inside `bots/base.py`. Reason: `bots/base.py` transitively imports a Cython
extension (`parrot.utils.types`) that is not built in the SDD worktree, so a helper
defined there is not unit-testable in isolation. Keeping the pure logic in the a2ui
package makes it directly testable and is arguably cleaner (a2ui logic in the a2ui
package); `bots/base.py` still owns the routing branch and imports the helper.
(2) The server stream integration test uses `pytest.importorskip` for the heavy
`parrot.handlers.agent` import (unbuilt Cython in the worktree) plus source-level
wire-contract regression assertions that run everywhere — the real handler import runs
in a built environment (CI).
