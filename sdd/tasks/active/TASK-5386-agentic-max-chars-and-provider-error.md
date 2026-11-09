# TASK-5386: Agentic retrieval — `max_chars=None` coercion and a `provider_error` stop reason

**Feature**: FEAT-849 — PageIndex Toolkit Tech Debt
**Spec**: `sdd/specs/pageindex-toolkit-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:2e4dfac0d686`

---

## Context

Implements spec §4 FR-2, FR-4 and FR-5.1, and §3 decisions D-2 and D-3. Part of the work
that closes `issue:2e4dfac0d686` (items 1, 3 and 4).

Two defects in `AgenticRetriever`:

1. **`max_chars=None` crashes a read** (`agentic.py:197`). The read wrapper charges
   `ledger.charge(kwargs.get("max_chars", 12000))`. A `dict.get` default only applies when
   the key is *absent*; a model that passes `max_chars: null` — well-formed against the
   tool schema — yields `None`, and `ReadLedger.charge` raises `TypeError`, aborting the
   whole agentic request instead of degrading to the documented default.
2. **A provider exception discards paid-for reads** (`agentic.py:319`,
   `response = await provider_task`). The exception propagates out of `run()`. By then the
   `ReadLedger` has already charged the budget and recorded `reads`, and all of it is lost:
   the caller gets a traceback instead of a partial `EvidenceBundle`.

Spec D-2 resolves the open question the ledger issue left (`"needs a spec decision on a
stopped value"`): a provider failure gets its **own** `StopReason`, `"provider_error"` —
not a reused `"parse_error"`, which would conflate "the model answered unparseably" with
"the provider call blew up".

Item (4) of the same issue is documentation: cap-fill ends the loop immediately, so a model
using exactly `max_tool_calls` always gets `stopped="max_tool_calls"` with no answer, and a
same-tick provider-done/stop tie discards a completed answer. That goes in this task's
docstring; the wiki side is TASK-5388.

---

## Scope

- Coerce `max_chars` in `AgenticRetriever._wrap`'s read path.
- Add `"provider_error"` to `StopReason`.
- Catch the provider task's exception in `AgenticRetriever.run`, log it, and fall through to
  the normal `EvidenceBundle` build; add `"provider_error"` to the two existing guard sets.
- Document the cap-fill / tie semantics in `AgenticRetriever.run`'s docstring.
- Write tests in `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py`.

**NOT in scope**:
- `toolkit.py` — the `agentic_retrieve` snapshot fix and the `_agentic_lock` docstring are
  TASK-5387; the re-import fix is TASK-5385. **Do not touch `toolkit.py`.**
- `wiki/knowledge/pageindex-agentic-retrieval.md` — TASK-5388.
- Changing the cap-fill *behaviour*. Item (4) is documentation only; the loop keeps
  terminating on cap-fill exactly as it does today.
- Lock granularity. `_agentic_lock` is unchanged.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` | MODIFY | `max_chars` coercion, `provider_error` literal + handling, `run` docstring |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` | MODIFY | Tests for AC-6 and AC-8 |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase at `dev`.
> Do NOT invent any import, attribute, or method not listed here.

### Verified Imports

All already present at the top of `agentic.py` — add no new import:

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py:5-27 (verified)
import asyncio
import logging
from typing import Any, Callable, Literal, Optional, Sequence
from parrot.knowledge.pageindex.read_ledger import BudgetExhausted, LedgerEntry, ReadLedger
from parrot.knowledge.pageindex.segments import DocumentRevision, ReadResult, SegmentRead, format_cursor
from parrot.tools.toolkit import AbstractTool, ToolkitTool
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py:42
StopReason = Literal["answered", "budget", "max_tool_calls", "timeout", "no_tool_calls", "parse_error"]

# agentic.py:63
class EvidenceBundle(BaseModel):
    tree_name: str
    query: str
    generation: Optional[int] = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    reads: list[LedgerEntry] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    rejected: list[RejectedCitation] = Field(default_factory=list)
    answer: Optional[str] = None
    grounded: bool = False
    tool_calls: int = 0
    chars_read: int = 0
    stopped: StopReason = "answered"
    usage: dict[str, int] = Field(default_factory=dict)
    rendered_citations: str = ""

# agentic.py:188 — AgenticRetriever._wrap, inner `async def call`
#   line 197: grant = ledger.charge(kwargs.get("max_chars", 12000))
#   line 198-200: except BudgetExhausted: flags["budget"] = True; return BUDGET_MESSAGE
#   line 201: raw = await inner(**{**kwargs, "max_chars": max(grant, 500)})

# agentic.py:264 — the method this task edits
async def run(
    self, *, tree_name: str, query: str, candidates: list[dict[str, Any]], outline: dict[str, Any],
    generation: Optional[int], budget_chars: int, max_reads: int, max_tool_calls: int,
    deadline: float, draft_answer: bool,
) -> EvidenceBundle:
    """Run the supervised stage-2 loop on the caller-provided absolute deadline."""
    # line 319: response = await provider_task        (the only occurrence)
    # line 324: if stopped not in {"timeout", "max_tool_calls"}:                       (1 occurrence)
    # line 357: if stopped not in {"timeout", "max_tool_calls", "parse_error"} and answer is not None:  (1 occurrence)

# agentic.py:230 — AgenticRetriever._cancel
@staticmethod
async def _cancel(task: asyncio.Task[Any]) -> None:

# packages/ai-parrot/src/parrot/knowledge/pageindex/read_ledger.py:21
class BudgetExhausted(RuntimeError): ...
# read_ledger.py:47
class ReadLedger:
    def charge(self, requested_chars: int) -> int:      # line 58
    def record(self, result: ReadResult) -> None:       # line 69
    def entries(self) -> list[LedgerEntry]:             # line 98 (property)
    @property
    def chars_read(self) -> int:                        # line 112
```

`self.logger` exists on `AgenticRetriever` — set in `__init__` as
`self.logger = logging.getLogger(__name__)` (verified `agentic.py:175`).

### Does NOT Exist

- ~~`StopReason.provider_error`~~ — `StopReason` is a `typing.Literal`, not an enum; there
  is no attribute access, only the string `"provider_error"`.
- ~~`EvidenceBundle.error` / `.exception` / `.failure_reason`~~ — the bundle has no error
  field, and this task must not add one. The stop reason carries the outcome.
- ~~`AgenticRetriever._handle_provider_error`~~ — no such helper; the handling is inline.
- ~~`ReadLedger.charge(None)` being tolerant~~ — `charge` takes `requested_chars: int` and
  arithmetic on `None` raises; the coercion must happen at the call site.
- ~~`ReadLedger.rollback()` / `.refund()`~~ — a charge cannot be undone, which is exactly
  why the partial bundle must reach the caller.
- ~~`BUDGET_MESSAGE` being a callable~~ — it is a module-level string constant.
- ~~`asyncio.Task.exception()` being safe on a cancelled task~~ — it re-raises
  `CancelledError`; do not use it to detect the failure.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py#AgenticRetriever.run",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py#AgenticRetriever._wrap",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py#EvidenceBundle",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/read_ledger.py#ReadLedger",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/read_ledger.py#BudgetExhausted"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Never swallow `asyncio.CancelledError`** (FR-4.2). The `except` clause must be
  `except Exception` — a bare `except:` or `except BaseException` would break the
  timeout/cap-fill cancellation paths, which cancel `provider_task` deliberately.
- **`BudgetExhausted` keeps its current behaviour** (FR-2.2): it still returns
  `BUDGET_MESSAGE` and sets `flags["budget"]`; the coercion sits *before* the `try`'s
  charge, not around the `except`.
- **A positive `max_chars` is still honoured exactly** — `int(... or 12000)` changes only
  falsy values.
- **The bundle build must stay outside the `try`.** It already is (`agentic.py:371-390`),
  and it reads `ledger.entries()` / `ledger.chars_read` / `controller.admitted`, which is
  what preserves the partial reads. Do not move it.
- **Both guard sets get the new literal** (FR-4.4), or a provider error would fall into the
  answer-parsing branch with `response is None` and be reported as `parse_error`.
- Async throughout; 120-col lines; Google-style docstrings; `self.logger`, never `print`.

### References in Codebase

- `agentic.py:324-355` — the answer-parse/repair branch the new literal must bypass.
- `agentic.py:357-363` — the citation-validation branch, already guarded for `parse_error`.
- `agentic.py:365-370` — the `finally` that cancels both tasks and clears the tool manager;
  it runs on the provider-error path too and needs no change.

---

## Implementation Blueprint

### Steps (in order)

1. Extend `StopReason` with `"provider_error"` — *why*: every later edit references the
   literal, and `EvidenceBundle.stopped` is validated against it by Pydantic.
2. Coerce `max_chars` in `_wrap` — *why*: FR-2, a one-expression fix independent of the rest.
3. Wrap `response = await provider_task` and set `stopped = "provider_error"` — *why*: FR-4.2.
4. Add the literal to both guard sets — *why*: FR-4.4; without it the error is mislabelled
   `parse_error`.
5. Document the cap-fill / tie semantics in `run`'s docstring — *why*: FR-5.1.
6. Write the two tests — *why*: AC-6 and AC-8 are the closing evidence for items 1 and 3.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` (MODIFY — `StopReason`)

```python
# occurrences: 1 (verified: grep -c 'StopReason = Literal' agentic.py)
# REPLACE the line `StopReason = Literal[...]` (verified: agentic.py:42)
StopReason = Literal[
    "answered",
    "budget",
    "max_tool_calls",
    "timeout",
    "no_tool_calls",
    "parse_error",
    "provider_error",
]
```

**Why**: spec D-2 — a provider failure is its own outcome, distinguishable from
`parse_error` at triage time. The literal is expanded over several lines because the
single-line form would exceed 120 columns.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` (MODIFY — `max_chars`)

```python
# occurrences: 1 (verified: grep -c 'grant = ledger.charge(kwargs.get("max_chars", 12000))' agentic.py)
# REPLACE that line (verified: agentic.py:197)
                        grant = ledger.charge(int(kwargs.get("max_chars") or 12000))
```

**Why**: spec D-3. `dict.get`'s default fires only on an absent key, so a model passing
`max_chars: null` reaches `charge(None)` and raises `TypeError`. `or 12000` absorbs `None`,
`0` and `""` into the documented default in one expression; `int(...)` normalises a numeric
string. A schema-level rejection was rejected — it surfaces as a tool-call error the model
cannot recover from mid-loop.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` (MODIFY — provider error)

```python
# occurrences: 1 (verified: grep -c 'response = await provider_task' agentic.py)
# REPLACE that line and keep its indentation (verified: agentic.py:319, inside the
# `else:` of `elif stop_task in done:`)
                else:
                    try:
                        response = await provider_task
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 - a provider failure must not lose paid-for reads
                        self.logger.warning("agentic provider call failed: %s", exc, exc_info=True)
                        stopped = "provider_error"
```

**Why**: FR-4.2/FR-4.3. `run()` falls through to the existing `EvidenceBundle` build, which
reads `ledger.entries()`, `ledger.chars_read` and `controller.admitted` — so the reads the
request already paid for reach the caller with `answer=None` and `grounded=False`. The
explicit `except asyncio.CancelledError: raise` comes first so the deliberate
timeout/cap-fill cancellations keep propagating (Key Constraints).

### `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` (MODIFY — guard sets)

```python
# occurrences: 1 (verified: grep -c 'if stopped not in {"timeout", "max_tool_calls"}:' agentic.py)
# REPLACE that line (verified: agentic.py:324)
            if stopped not in {"timeout", "max_tool_calls", "provider_error"}:
```

```python
# occurrences: 1 (verified: grep -c 'if stopped not in {"timeout", "max_tool_calls", "parse_error"} and answer is not None:' agentic.py)
# REPLACE that line (verified: agentic.py:357)
            if stopped not in {"timeout", "max_tool_calls", "parse_error", "provider_error"} and answer is not None:
```

**Why**: FR-4.4. The first guard gates answer parsing and the repair round-trip — with
`response is None` that path would overwrite `stopped` with `parse_error` and spend another
provider call. The second gates citation validation, which has nothing to validate.
The `stopped in {"timeout", "max_tool_calls"}` cancel check at `agentic.py:322` is
deliberately NOT changed: on the provider-error path `provider_task` is already finished,
and the `finally` block cancels it idempotently.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` (MODIFY — `run` docstring)

```python
# occurrences: 1 (verified: grep -c 'Run the supervised stage-2 loop' agentic.py)
# REPLACE the one-line docstring of `run` (verified: agentic.py:286)
        """Run the supervised stage-2 loop under the caller-provided absolute deadline.

        Termination semantics callers must size for:

        * **Cap-fill ends the loop immediately.** The controller sets its stop event as
          soon as the last admitted tool call completes, so a model that uses *exactly*
          ``max_tool_calls`` reads returns ``stopped="max_tool_calls"`` with no answer.
          Size ``max_tool_calls`` one above the expected read count.
        * **A provider-done / stop tie resolves to ``max_tool_calls``.** When the provider
          finishes in the same tick the cap is reached, ``asyncio.wait`` reports both and
          the stop branch wins, discarding a completed answer.
        * **A provider failure is not raised.** It returns ``stopped="provider_error"`` with
          ``answer=None`` and the reads already charged against the budget.
        """
```

**Why**: FR-5.1 — the two surprising outcomes are stated where an integrator reading the
method will find them, with the concrete remedy (size the cap one above the expected reads)
rather than only a description. The third bullet documents this task's own new behaviour so
the docstring and `StopReason` cannot drift apart.

### `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` (MODIFY)

```python
# FILL IN: locate the attachment point — run
#   grep -n '^async def test_\|^def test_\|^class Test' \
#     packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py
# and append the two tests below after the last test in the module, reusing whatever
# retriever/stub-client fixtures and helpers the file already defines (it is 18.6K and
# already builds an AgenticRetriever with a stubbed client — do NOT invent a new fixture).


@pytest.mark.asyncio
async def test_read_tool_accepts_null_max_chars() -> None:
    """AC-6: a read invoked with max_chars=None charges the 12000 default, not TypeError."""
    # FILL IN: build an AgenticRetriever the way this module's existing tests do, wrap a
    # read tool via `_wrap` (or drive `run` with a stub client whose tool call passes
    # `max_chars=None`), invoke it, and assert it returns a clipped ReadResult payload and
    # that no TypeError escapes. Bounded by AC-6 and FR-2.1: None, 0 and "" all resolve to
    # 12000, while a positive int is still honoured exactly (assert that second case too,
    # per FR-2.2).
    raise NotImplementedError


@pytest.mark.asyncio
async def test_provider_exception_returns_partial_bundle() -> None:
    """AC-8: a provider failure returns a partial bundle, not a traceback."""
    # FILL IN: drive `AgenticRetriever.run` with a stub client whose `ask` performs one
    # successful ledger-charged read and then raises (e.g. RuntimeError("boom")). Assert the
    # returned EvidenceBundle has stopped == "provider_error", answer is None,
    # grounded is False, citations == [], and `reads` contains the entry charged before the
    # failure with chars_read > 0. Bounded by AC-8 and FR-4.3. Do NOT assert on a log
    # message; the contract is the bundle.
    raise NotImplementedError
```

**Why**: `test_agentic_retrieval.py` already owns `AgenticRetriever`'s unit surface and its
stub-client scaffolding, so the tests attach there instead of in a new module. The blueprint
deliberately does not hard-code a fixture name: the file is large and its helpers must be
read first — guessing one is exactly the hallucination the Codebase Contract guards against.

### FILL IN checklist

- [ ] `test_agentic_retrieval.py` — locate the module's existing retriever/stub-client
      fixtures before writing either test; do not invent new ones.
- [ ] `test_agentic_retrieval.py::test_read_tool_accepts_null_max_chars` — assert both the
      coerced-default case and the honoured positive case; bounded by AC-6, FR-2.1, FR-2.2.
- [ ] `test_agentic_retrieval.py::test_provider_exception_returns_partial_bundle` — assert
      the bundle fields, not the log; bounded by AC-8 and FR-4.3.

---

## Acceptance Criteria

- [ ] AC-6 — a read tool invoked with `max_chars=None` charges the 12000 default and returns
      a clipped `ReadResult` instead of raising `TypeError`; a positive `max_chars` is unchanged.
- [ ] AC-8 — when the provider task raises, `run` returns an `EvidenceBundle` with
      `stopped == "provider_error"`, `answer is None`, `grounded is False`, and `reads`
      containing the entries charged before the failure.
- [ ] `asyncio.CancelledError` still propagates (timeout and cap-fill paths unchanged).
- [ ] `AgenticRetriever.run`'s docstring documents cap-fill, the tie, and `provider_error`.
- [ ] `ruff check` clean on both changed files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_read_ledger.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_read_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_citations.py -q`

---

## Test Specification

Two tests appended to
`packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py`:
`test_read_tool_accepts_null_max_chars` (AC-6) and
`test_provider_exception_returns_partial_bundle` (AC-8). Reuse the module's existing
retriever and stub-client helpers.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-toolkit-tech-debt --feature-id FEAT-849`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-grep every anchor's occurrence count before
   editing; a count of 0 means the anchor moved: stop and report the drift
5. **Update status** in `sdd/tasks/index/pageindex-toolkit-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing every `# FILL IN:` marker
7. **Verify** by running the Validation Commands with
   `PYTHONPATH=<wt>/packages/ai-parrot/src`
8. **Commit the code** — stage only the two files this task lists; **never `toolkit.py`**
9. **Close the task**: `parrot sdd task close TASK-5386 pageindex-toolkit-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
