---
type: Wiki Overview
title: 'TASK-1613: `_resolve_final_response` chokepoint in the Gemini client (WS2)'
id: doc:sdd-tasks-active-task-1613-gemini-resolve-final-response-chokepoint-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: WS2 — the **primary containment** (spec §3 Module 3, G3). Today there is
  no single
relates_to:
- concept: mod:parrot.clients.google.client
  rel: mentions
- concept: mod:parrot.security.redaction
  rel: mentions
---

# TASK-1613: `_resolve_final_response` chokepoint in the Gemini client (WS2)

**Feature**: FEAT-252 — REPL Sandbox + Gemini Response Contract + Secret Scrubber
**Spec**: `sdd/specs/repl-sandbox-response-contract-scrubber.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1612
**Assigned-to**: unassigned

---

## Context

WS2 — the **primary containment** (spec §3 Module 3, G3). Today there is no single
response gate: redaction is sprinkled across ~14 sites and the response that reaches
the user can be a genuine synthesis, a verbatim **echo of a tool result** (the
incident), raw **code-exec stdout** (a fallback), or `default_api`/`tool_code`
scaffolding. This task introduces one deterministic `_resolve_final_response`
chokepoint that all 6 `AIMessageFactory.from_gemini(...)` terminal sites funnel
through, removes the scattered `redact_*` calls (now covered by the chokepoint +
the TASK-1612 seam), gates `default_api` hunting, returns a typed "no answer
produced" on empty-after-tools, and adds the **closed tool manifest** to the prompt.

**Hard precondition:** TASK-1612 (single seam) must be merged first so removing the
scattered calls never opens a redaction gap (Risk R1 / G5).

---

## Scope

- Add `GoogleClient._resolve_final_response(candidate_text, all_tool_calls,
  code_exec_output) -> str`:
  1. classify provenance: synthesis vs `tool_echo` vs `code_exec_stdout`.
  2. if `tool_echo` → suppress (do not ship verbatim/near-verbatim tool result).
  3. never promote raw code-exec stdout without scrub + framing.
  4. run `OutputScrubber.scrub` **last**, always.
  5. on empty-after-tools → return a typed "no answer produced" sentinel the handler
     renders safely (do NOT fall back to raw output; do NOT revive forced synthesis).
- Route all **6** terminal `from_gemini` sites (and the multiturn loop tail) through it.
- **Remove the ~14 scattered `redact_text`/`redact_secrets` calls** in
  `google/client.py` (listed in the contract). Scrubbing now happens once in the
  chokepoint (egress) + once at `AbstractTool.execute()` (in-bound, TASK-1612).
- Gate `default_api`/`tool_code` hunting: detect and drop `default_api` import
  attempts and `tool_code` targeting non-existent tools → surface a typed
  "tool not available" rather than improvising.
- Add the **closed tool manifest** to the system prompt / per-call instruction:
  "these are all the tools available; there is no `default_api`; do not write code
  to discover or import anything else."

**NOT in scope**: the Python AST gate (TASK-1614); the scrubber implementation
itself (TASK-1612 owns it); echo-threshold final tuning (Open Q O2 — implement a
sane default + make it configurable).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | Add chokepoint; route 6 terminals; remove scatter; gate default_api; manifest |
| `packages/ai-parrot/tests/test_google_client.py` | MODIFY | Extend with chokepoint/echo/empty/default_api tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# available after TASK-1612
from parrot.security.redaction import OutputScrubber, ScrubPolicy
# already present in client.py (line 74) — to be REMOVED/replaced by the chokepoint:
from ...security.redaction import redact_secrets, redact_text
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/google/client.py
async def _handle_multiturn_function_calls(...)              # line 1580
    #   line 1612: function_calls = self._get_function_calls_from_response(current_response)
    #   line 1652: "Skipping forced synthesis to avoid unnecessary delays." (do NOT revive)
def _get_function_calls_from_response(self, response) -> List # line 2066
def _safe_extract_text(self, response) -> str               # line 2107
def _parse_tool_code_blocks(self, text: str) -> List         # line 1958
    #   line 1966: regex r"```tool_code\s*\n\s*print\(default_api\.(\w+)\((.*?)\)\)\s*\n\s*```"
async def ask(...)                                           # line 2391
async def ask_stream(...)                                    # line 3294
async def resume(self, session_id, user_input, state) -> AIMessage  # line 4816
async def invoke(...)                                        # line 4929

# 6 TERMINAL from_gemini sites to route through _resolve_final_response:
#   client.py:3146, 3796, 4323, 4505, 4802, 4917   ->  AIMessageFactory.from_gemini(...)

# ~14 SCATTERED redact_* call sites to REMOVE (verified line numbers):
#   redact_text:   1301, 1354, 1397, 1775, 3206, 3208, 3221, 3223
#   redact_secrets:1335, 1754, 3618, 4790
```

### Does NOT Exist
- ~~`GoogleClient._resolve_final_response`~~ — this task CREATES it (grep: absent).
- ~~`classify_provenance` / `_synthesize_or_safe_fallback`~~ — design names; create as helpers.
- ~~a forced-synthesis block~~ — commented out/skipped at line 1652; do NOT revive (decision: typed empty).
- ~~`AIMessageFactory.from_gemini` doing redaction~~ — it does not; scrub before constructing it.

---

## Implementation Notes

### Pattern to Follow
```python
def _resolve_final_response(self, candidate_text, all_tool_calls, code_exec_output):
    provenance = self._classify_provenance(candidate_text, all_tool_calls, code_exec_output)
    if provenance == "tool_echo":
        candidate_text = self._no_answer_sentinel()      # typed empty, NOT raw fallback
    elif provenance == "code_exec_stdout":
        candidate_text = self._frame_code_output(candidate_text)
    return self._scrubber.scrub(candidate_text)          # ALWAYS last
```
- Instantiate one `OutputScrubber` on the client (e.g. in `__init__`) and reuse it.
- Echo detection: normalized similarity vs the last N `tool_result`s; default cutoff
  conservative, exposed as a config attribute (O2).

### Key Constraints
- **Land TASK-1612 first.** Do not remove a scattered `redact_*` call until the
  chokepoint covers that path — keep them until the funnel is wired, then delete in
  the same task once `_resolve_final_response` is proven (G5 / `test_no_redaction_gap`).
- Preserve streaming semantics in `ask_stream` — the chokepoint runs on the final
  assembled text, not per-chunk, to avoid latency regression (Risk R3).
- Keep all 4 public entry points (`ask`/`ask_stream`/`resume`/`invoke`) behavior-compatible
  except for the now-guaranteed scrub + echo-suppression.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/google/client.py:1580-2107` — loop + extractors.
- Provenance/echo design: spec §2 Overview + proposal §4.3-4.4.

---

## Acceptance Criteria

- [ ] `_resolve_final_response` exists; all 6 `from_gemini` terminals route through it (assert via test/grep).
- [ ] `grep -nE "redact_text|redact_secrets" client.py` returns **zero** scattered call sites (only the chokepoint's single `OutputScrubber.scrub`).
- [ ] Verbatim/near-verbatim tool-result echo is never shipped as the answer.
- [ ] Empty-after-tools returns the typed "no answer produced" sentinel (no raw stdout fallback).
- [ ] `default_api` import attempt / non-existent-tool `tool_code` → typed "tool not available"; system prompt contains the closed tool manifest.
- [ ] `pytest packages/ai-parrot/tests/test_google_client.py -v` passes (incl. the `0f76129b1` cases).
- [ ] `ruff check` clean on `client.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/test_google_client.py (extend)
class TestResolveFinalResponse:
    def test_suppresses_tool_echo(self, client):
        tool_calls = [_tc(result="KeysView(environ({'PWD':'x'}))")]
        out = client._resolve_final_response("KeysView(environ({'PWD':'x'}))", tool_calls, None)
        assert "no answer" in out.lower() or "PWD" not in out

    def test_empty_after_tools_typed(self, client):
        out = client._resolve_final_response("", [_tc(result="42")], None)
        assert client._is_no_answer(out)

    def test_default_api_gated(self, client):
        calls = client._get_function_calls_from_response(_resp_with_default_api())
        assert calls == [] or all(c.name != "default_api" for c in calls)

    def test_no_scattered_redact_calls(self):
        import inspect, parrot.clients.google.client as m
        src = inspect.getsource(m)
        assert src.count("redact_text(") + src.count("redact_secrets(") <= 1
```

---

## Agent Instructions
(standard — verify TASK-1612 is in `completed/` first; verify contract; update index.)

## Completion Note
*(Agent fills this in when done)*
