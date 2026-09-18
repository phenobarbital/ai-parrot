# TASK-2840: Map `search_tools` onto native `tool_search` (DROPPABLE)

**Feature**: FEAT-526 — Meta Model API (Muse Spark) LLM Client
**Spec**: `sdd/specs/meta-llm-client.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2836
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** — deliberately the **last** task in the feature and
explicitly the **droppable** one. Nothing else depends on it.

**Design decision D2 (resolved, binding)**: map parrot's existing client-side
`search_tools` mechanism onto Meta's native hosted `tool_search`, **with
parrot's client-side path remaining the default** — the user has measured
Meta's hosted `tool_search` as **slower** than parrot's own search.

> The latency comparison is the user's measurement and was **not** independently
> reproduced during research (the one live `tool_search` probe returned HTTP 400
> for a missing deferred tool). Treat it as the governing requirement, not as
> something to re-litigate — but do not present it in code comments as
> independently verified either.

If the phase runs long, **cut this task**. That is the intended safety valve.

---

## Scope

- Add an opt-in path so parrot's `search_tools` can dispatch to Meta's native
  hosted `tool_search` on the Responses path.
- Mark deferred tools with `defer_loading: true` and inject
  `{"type": "tool_search"}`.
- Handle `tool_search_call` / `tool_search_output` output items.
- Keep parrot's client-side path as the **default**.
- Unit tests.

**NOT in scope**: changing parrot's client-side `search_tools` default
behaviour; modifying `base.py`; the `execution: "client"` tool-search mode
(hosted mode only for this phase).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-meta/src/parrot/clients/meta/client.py` | MODIFY | native tool_search opt-in |
| `tests/clients/test_meta_tool_search.py` | CREATE | Unit tests |

> Paths corrected at implementation time (2026-09-15): the client moved to the
> `ai-parrot-client-meta` satellite, and its sibling tests (`test_meta_*.py`)
> live under the repo-root `tests/clients/`.

---

## Codebase Contract (Anti-Hallucination)

### parrot's EXISTING client-side mechanism (read; do NOT modify)
```python
# packages/ai-parrot/src/parrot/clients/base.py  (line numbers re-verified 2026-09-15)
def _check_new_tools(self, tool_name: str,
                     tool_result_content: str) -> List[str]      # :1432
    #  :1443 early-returns unless tool_name == "search_tools"
    #  :1454 warns on unparseable search_tools result
def _prepare_lazy_tools(self, tool_choice: str = "auto") -> List[Dict]  # :1458
    #  :1462 search_tool = self.tool_manager.get_tool("search_tools")
    #  :1474 return self._prepare_tools(filter_names=["search_tools"])
```
`OpenAIBaseClient.ask()` exposes `lazy_loading: bool = False` (`openai_base.py:523`).

> `_prepare_lazy_tools` carries an in-code note (*"I will hack specific getting
> for now"*) — **pre-existing debt, explicitly out of scope.** Do not refactor it.

### Meta's native mechanism — LIVE-VERIFIED + documented
```
Add {"type": "tool_search"} to `tools`, AND set defer_loading: true on the
individual function tools to defer.

LIVE PROBE (2026-09-04):
  tools=[{"type":"tool_search"}] with no deferred tool
    -> HTTP 400 {"error":{"message":"tools.tool_search requires at least one
                 deferred tool.","param":"tools.tool_search",
                 "type":"invalid_request_error"}}

Behaviour (docs):
  - A deferred tool's name and description stay visible; only its parameter
    schema is withheld until loaded.
  - Loaded definitions are appended at the END of context, preserving the
    cache prefix.
  - Response adds output items: `tool_search_call` (records `paths` searched)
    and `tool_search_output` (the loaded definitions).
  - Hosted mode = API searches and loads in the same response.
```

### Does NOT Exist
- ~~`from .openai_base import ...`~~ inside `clients/meta/client.py` — the module
  is one level deeper under the FEAT-523 folder convention; use
  `from ..openai_base import OpenAIBaseClient`. A single-dot import will fail.
- ~~`tool_search` on Chat Completions~~ — **Responses API only**. This task
  depends on TASK-2836 for that reason.
- ~~A bare `{"type":"tool_search"}` that works alone~~ — HTTP 400 without at
  least one `defer_loading: true` tool.
- ~~`ToolFormat.META`~~ — does not exist and is **not needed**. Meta accepts
  `ToolFormat.OPENAI` including `strict: true` (verified live 200). Do not add
  a new `ToolFormat` member.
- ~~`execution: "client"` mode~~ — out of scope for this phase.
- ~~`tool_choice` values other than `"auto"`~~ — HTTP 400.

---

## Implementation Notes

### Key Constraints

1. **Parrot's client-side path stays the default.** The native mode must be
   explicitly opted into (e.g. `native_tool_search: bool = False`). Do not flip
   the default, and do not change `lazy_loading`'s existing meaning.
2. **Guard the 400.** If native mode is requested with no deferred tool, either
   fall back to parrot's path or raise a clear error — never send a request that
   is guaranteed to 400.
3. **Responses path only.** Requesting native tool search with
   `use_responses=False` must raise a clear `ValueError`.
4. **Do not modify `base.py`.** Both mechanisms coexist; this task adds a
   dispatch option in `meta.py` only.
5. Document the latency rationale in the docstring, attributed as an operator
   measurement rather than an independently verified benchmark.

---

## Acceptance Criteria

- [x] `native_tool_search` defaults to `False`; parrot's path is unchanged by default.
- [x] When enabled, `{"type": "tool_search"}` is injected and deferred tools
      carry `defer_loading: true`.
- [x] Enabling it with no deferred tool does not produce a guaranteed-400 request.
- [x] Enabling it with `use_responses=False` raises `ValueError`.
- [x] `tool_search_call` / `tool_search_output` items are handled without
      corrupting the folded visible text.
- [x] `base.py` is **unmodified** (`git diff` clean).
- [x] No new `ToolFormat` member added.
- [x] Tests pass: `pytest tests/clients/test_meta_tool_search.py -v`
- [x] `ruff check packages/ai-parrot-client-meta/src/parrot/clients/meta/client.py` clean.

---

## Test Specification

```python
import pytest
from parrot.clients.meta import MetaClient


class TestNativeToolSearch:
    def test_defaults_to_off(self):
        assert MetaClient(api_key="k").native_tool_search is False

    async def test_raises_when_responses_disabled(self):
        client = MetaClient(api_key="k", use_responses=False,
                            native_tool_search=True)
        with pytest.raises(ValueError, match="[Rr]esponses"):
            await client.ask("q", tools=[...])

    async def test_injects_tool_search_and_defer_loading(self, monkeypatch): ...

    async def test_no_deferred_tool_does_not_send_guaranteed_400(self, monkeypatch):
        """Meta 400s on tool_search with no deferred tool — never send that."""
        ...

    async def test_tool_search_output_items_do_not_corrupt_text(self): ...
```

---

## Agent Instructions

1. Read the spec (§3 Module 6, §8 D2) and `base.py:1298-1338` (read only).
2. Confirm TASK-2836 is in `sdd/tasks/completed/`.
3. **Check with the operator before starting** — this task is explicitly
   droppable and is the intended cut if the phase is running long.
4. Implement, test, verify acceptance criteria including that `base.py` is untouched.
5. Move to `sdd/tasks/completed/`, set `done` in the index, fill the note.

---

## Completion Note

**Completed by**: Claude Code (/sdd-start, Opus 5)
**Date**: 2026-09-15
**Notes**:
- `MetaClient(native_tool_search: bool = False)` — instance-level opt-in (not an
  `ask()` kwarg, so the funnel-parity signature sweep stays green).
- When on (Responses path), `ask()`/`ask_stream()` send every function tool
  flattened with `defer_loading: true` plus `{"type": "tool_search"}`, and drop
  parrot's own `search_tools` tool (hosted search replaces it for that call).
  Non-function tools (`web_search`) pass through undeferred. Applies whether
  or not `lazy_loading` is set; `lazy_loading`'s meaning is unchanged when off.
- 400 guard: with no deferrable function tool, `tool_search` is never sent and
  the call falls back to parrot's client-side path (lazy or eager).
- Tool loop: parrot's lazy re-preparation is disabled in native mode (it would
  rewrite `args["tools"]` and strip `defer_loading`). Tools the model called are
  sent undeferred on later rounds, because the follow-up input replays the
  `function_call` but not the `tool_search_output`; `tool_search` is dropped
  once nothing stays deferred. This is defensive — the follow-up-round
  behaviour was NOT verified live.
- `tool_search_call`/`tool_search_output` items are ignored by text folding and
  tool-call extraction; ids are surfaced in `metadata["tool_search_calls"]`,
  plus `metadata["native_tool_search"] = True`.
- `use_responses=False` + `native_tool_search=True` raises `ValueError` from
  `ask()` and on first iteration of `ask_stream()`.
- Evidence: 164 passed across the Meta/parity client suites + 1 satellite test
  (`artifacts/logs/TASK-2840-pytest.log`, gitignored); ruff + black clean;
  `base.py` diff empty; no `ToolFormat` change. No live Meta API call was made.
**Deviations from spec**: file paths in the task were stale (client now in the
`ai-parrot-client-meta` satellite; tests in repo-root `tests/clients/`) —
corrected above. `ask_stream()` also honours the flag (scope said Responses
path; the task's tests only named `ask()`).
