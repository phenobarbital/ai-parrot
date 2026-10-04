# TASK-3848: Example dashboard agent, WIDGETS and .gitignore whitelist

**Feature**: FEAT-610 — A2UI Linked Surfaces E2E example
**Spec**: `sdd/specs/a2ui-linked-e2e-test.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3847
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (dashboard half) + Module 9 (.gitignore, S10) (FEAT-610). `examples/**/*.py` and
`examples/**/*.html` are git-ignored (`.gitignore:20,37`), so nothing under `examples/a2ui/` can be committed until
this task whitelists it.

---

## Scope

- `.gitignore`: after `!examples/agents/a2ui/**/*.py` (line 31) add a comment and `!examples/a2ui/**/*.py`,
  `!examples/a2ui/**/*.html` (the `.js`/`.css`/`.md` are not ignored today — verify with `git check-ignore`).
- `examples/a2ui/dashboard.py`: `WIDGETS` (exactly the spec §2 verified query map — 8 entries, keys
  kpi_total/kpi_studio/kpi_mat/kpi_multi/by_country/by_licensee/by_course/graduates), `build_dashboard_agent(llm)`,
  `extract_envelope(response)`. Labels must say people (KPIs) vs diplomas (pie).
- `tests/examples/__init__.py`, `tests/examples/test_a2ui_dashboard_example.py` (unit: extract_envelope, WIDGETS shape)
  and `tests/examples/test_a2ui_dashboard_live.py` (opt-in `PARROT_TEST_QS_LIVE=1` + `ENV=prod`: real
  `build_linked_dashboard(WIDGETS)` values = spec §2 Expected).

**NOT in scope**: server.py (TASK-3849); the by-course slug seed (TASK-3852).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.gitignore` | MODIFY | whitelist examples/a2ui |
| `examples/a2ui/dashboard.py` | CREATE | WIDGETS + agent + extract_envelope |
| `tests/examples/__init__.py` | CREATE | package marker |
| `tests/examples/test_a2ui_dashboard_example.py` | CREATE | unit tests |
| `tests/examples/test_a2ui_dashboard_live.py` | CREATE | opt-in live test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `f20d82332` (dev, 2026-09-29). Re-check line numbers before editing — earlier tasks in this
> feature may have shifted them.

### Verified Imports
```python
from parrot.bots import Agent                                          # bots/__init__.py:2
from parrot.models.basic import ToolCall                               # basic.py:23 (id, name, arguments, result, error)
from parrot.models.responses import AIMessage                          # responses.py:93 (tool_calls :157)
from parrot_tools.querysource.toolkit import QuerysourceToolkit        # toolkit.py:64 (programs=... kwarg, line 77)
```
### Existing Signatures to Use
```text
.gitignore:20  examples/**/*.py
.gitignore:31  !examples/agents/a2ui/**/*.py        (anchor, occurrences: 1)
.gitignore:37  examples/**/*.html
Agent(name=..., llm="provider:model", tools=[...], system_prompt=...) — FILL IN: confirm kwargs from an existing example
  (e.g. examples/agents/a2ui/*.py) before use.
```
### Does NOT Exist
- ~~`ToolCall.output`~~ — the field is `result`.
- ~~`polestar_graduates_by_course`~~ — exists only after the TASK-3852 seed runs; the live test must skip that widget's
  value check when the slug is missing.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".gitignore",
      "action": "MODIFY"
    },
    {
      "path": "examples/a2ui/dashboard.py",
      "action": "CREATE"
    },
    {
      "path": "tests/examples/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "tests/examples/test_a2ui_dashboard_example.py",
      "action": "CREATE"
    },
    {
      "path": "tests/examples/test_a2ui_dashboard_live.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: depends on TASK-3847: build_dashboard_agent's prompt drives the qs_build_linked_dashboard tool and WIDGETS feeds it; first task under examples/a2ui/, owns the .gitignore whitelist every later example task relies on.
- Production data: any live query uses `ENV=prod`, read-only. Never commit tokens, passwords or DSNs.
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src:packages/ai-parrot-server/src`
  as needed; never `uv sync` inside a worktree.

---

## Implementation Blueprint

**Steps (in order)**
1. `.gitignore` first — then `git check-ignore -v examples/a2ui/dashboard.py examples/a2ui/static/index.html` must print nothing.
2. `dashboard.py`: copy the §2 table into `WIDGETS` verbatim (request dicts exactly as the table), because AC7 values
   were verified live with those exact requests.
3. Agent prompt: instruct ONE `qs_build_linked_dashboard(widgets=WIDGETS, title=...)` call — pass WIDGETS as JSON in
   the prompt; `extract_envelope` fails loudly otherwise (spec §7 "Agent determinism").

```gitignore
# .gitignore — AFTER — insert below `!examples/agents/a2ui/**/*.py` (verified: .gitignore:31, occurrences: 1)
# FEAT-610 A2UI linked-surfaces E2E example (server + static renderer) ships with the repo.
!examples/a2ui/**/*.py
!examples/a2ui/**/*.html
```
```python
# examples/a2ui/dashboard.py — CREATE
"""FEAT-610 — Polestar graduates linked dashboard: widget specs + the agent that emits the surface."""

from __future__ import annotations

import json
from typing import Any

from parrot.bots import Agent
from parrot.models.responses import AIMessage
from parrot_tools.querysource.toolkit import QuerysourceToolkit

SLUG = "polestar_graduates_directory"
BY_COURSE_SLUG = "polestar_graduates_by_course"
DEFAULT_LLM = "anthropic:claude-sonnet-5"

WIDGETS: list[dict[str, Any]] = [
    # FILL IN: the 8 entries of spec §2 "Verified query map", e.g.
    # {"key": "kpi_total", "slug": SLUG, "request": {"fields": ["count(*) as total"]},
    #  "component": {"component": "KPICard", "title": "Graduates (people)", "value": "total"}},
    # bar charts: {"component": "Chart", "type": "bar", "x": "country", "y": ["graduates"], "title": ...}
    # grid: DataTable with columns from the request fields, request ordering ["student_uid"], limit 500.
]


def build_dashboard_agent(llm: str | None = None) -> Agent:
    """Agent named 'polestar-dashboard' with QuerysourceToolkit(programs=['polestar'])."""
    toolkit = QuerysourceToolkit(programs=["polestar"])
    prompt = (
        "You build dashboards. Call the tool qs_build_linked_dashboard exactly once with the widgets given by the "
        "user, unchanged, then reply with one short sentence."
    )
    # FILL IN: construct the Agent with name, llm (llm or DEFAULT_LLM), toolkit tools and prompt — bounded by the
    #   verified Agent kwargs.


def dashboard_question() -> str:
    """User turn that hands WIDGETS to the agent verbatim."""
    return "Build the Polestar graduates dashboard with these widgets:\n" + json.dumps(WIDGETS)


def extract_envelope(response: AIMessage) -> dict[str, Any]:
    """Return the qs_build_linked_dashboard ToolCall result's a2ui_envelope.

    Raises:
        RuntimeError: if the tool was not called or the envelope has no parrot_data_sources.
    """
    for call in response.tool_calls:
        if call.name == "qs_build_linked_dashboard" and isinstance(call.result, dict):
            envelope = call.result.get("a2ui_envelope")
            # FILL IN: verify envelope["createSurface"]["metadata"]["extensions"]["parrot_data_sources"] exists
            #   (check the exact nesting against a real build_linked_surface dump) and return it.
    raise RuntimeError("the agent did not call qs_build_linked_dashboard; no linked envelope to serve")
```
```python
# tests/examples/test_a2ui_dashboard_example.py — CREATE
"""FEAT-610 TASK-3848 — example dashboard module (extract_envelope, WIDGETS)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui"))
import dashboard  # noqa: E402

# FILL IN: test_widgets_match_query_map (8 keys, unique, 4 KPICard/3 Chart/1 DataTable, KPI value strings),
#   test_extract_envelope (AIMessage with a ToolCall result → envelope), test_extract_envelope_raises (no call).
```
**FILL IN checklist**
- [ ] 8 WIDGETS from §2; Agent construction; envelope nesting; unit + live test bodies (live: skipif env unset).

---

## Acceptance Criteria

- [ ] `git check-ignore -v examples/a2ui/server.py examples/a2ui/static/index.html` prints nothing (AC13, S10).
- [ ] `WIDGETS` equals the §2 query map; `extract_envelope` picks the tool result and raises when absent (§4).
- [ ] Live test (opt-in) reproduces §2 Expected values; no credentials committed.

---

## Validation Commands

- `pytest tests/examples/test_a2ui_dashboard_example.py -q`
- `pytest tests/examples/test_a2ui_dashboard_live.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_extract_envelope` / `_raises` | §4 M7 |
| `test_widgets_match_query_map` | AC1 input |
| `test_linked_dashboard_live` (opt-in) | AC7 |

---

## Agent Instructions

1. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
2. Implement exactly the files listed; no refactors outside scope.
3. `ruff check --fix` the touched Python files; run the Validation Commands.
4. Commit code only: `feat(a2ui-linked-e2e-test): TASK-3848 — Example dashboard agent, WIDGETS and .gitignore whitelist`.
5. Close with `scripts/sdd/close_task.sh TASK-3848 a2ui-linked-e2e-test verified` and fill the Completion Note.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 334.0s · Tokens: n/a

.gitignore whitelists examples/a2ui/**/*.py|html; examples/a2ui/dashboard.py (8 WIDGETS, agent, extract_envelope) tracked; tests/examples: 3 passed, 1 skipped (live test is opt-in PARROT_TEST_QS_LIVE=1 + ENV=prod, NOT run). Merge-tier sweep skipped (env-red, see TASK-3842).
