# TASK-4854: MetricSuggestionProvider (FEAT-752 deterministic provider)

**Feature**: FEAT-756 — Metric Definition Registry
**Spec**: `sdd/specs/metric-definition-registry.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4846
**Assigned-to**: unassigned

---

> **BLOCKED (cross-feature)** — do NOT start until FEAT-752 `followup-suggestion-chips`
> has merged to `dev` its TASK-4794 (`parrot/models/suggestions.py`) and TASK-4797
> (`parrot/bots/suggestions/protocol.py`). On 2026-10-27 every FEAT-752 task is `pending`.
> When it lands, re-verify every symbol under "Does NOT Exist yet" before writing code.

---

## Context

Spec §3 Module 8 (provider half), goal G7, open question Q2. The protocol is pinned to the
FEAT-752 spec (`sdd/specs/followup-suggestion-chips.spec.md` L209-240, L320-345), which
**supersedes** the FEAT-756 skeleton's `suggest(*, question, response, ctx)` signature: the
provider implements `async suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]`.

---

## Scope

- Implement `MetricSuggestionProvider` (`name = "metrics"`, `lane = "deterministic"`, `max_chips=5`).
- Read the match with `current_metric_match()`; no match → `[]`.
- Chips: "vs previous period" (when `comparison.mode != "none"`), "by <dimension>" per declared dimension (max 3),
  "as <other shape>" (KPICard ↔ Chart ↔ DataTable, excluding the current default). Each `prompt` is a complete
  sentence ("Show Worked Hours by cost center"); `label` ≤ 40 chars (truncate). Presentation chips set
  `kind=PRESENTATION`; others `FOLLOWUP`; `source=PROVIDER`. Never raises.
- Write `test_suggestions.py`.

**NOT in scope**: registering the provider on bots (host code / docs TASK-4856), chip transport/rendering (FEAT-752).
Do not edit `parrot/metrics/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/metrics/suggestions.py` | CREATE | provider |
| `packages/ai-parrot/tests/unit/metrics/test_suggestions.py` | CREATE | chip tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.metrics.context import current_metric_match     # TASK-4846 (new)
from parrot.metrics.models import MetricMatch               # TASK-4843 (new)
```

### Does NOT Exist yet (lands with FEAT-752 — verify before use)
```python
from parrot.models.suggestions import Suggestion, SuggestionKind, SuggestionSource   # FEAT-752 TASK-4794; spec L209-240
#   Suggestion(label: str[1..40], prompt: str[1..500], output_mode: OutputMode | None, kind, source, action)
#   SuggestionKind: FOLLOWUP | PRESENTATION | ACTION ; SuggestionSource: LLM | SKILL | PROVIDER
from parrot.bots.suggestions.protocol import SuggestionContext, SuggestionProvider   # FEAT-752 TASK-4797; spec L320-345
#   SuggestionContext(question, response, output_mode, bot, user_id=None, session_id=None, tenant=None)
#   SuggestionProvider(Protocol): name: str; lane: Literal["skill","deterministic","llm"];
#       async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]
# AbstractBot.register_suggestion_provider(provider, *, prepend=False)   # FEAT-752 TASK-4800
```

### Does NOT Exist
- ~~`suggest(*, question, response, ctx)`~~ — FEAT-756 skeleton form, superseded by FEAT-752's `suggest(ctx)`.
- ~~`ctx.metric_match` on `SuggestionContext`~~ — read via `current_metric_match()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/metrics/suggestions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/metrics/test_suggestions.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `parrot.metrics` stays light: import `parrot.models.suggestions` at top (pure Pydantic); do NOT import `parrot.bots.suggestions` at runtime — type-annotate `SuggestionContext` under `TYPE_CHECKING`.
- Presentation chips set `output_mode=OutputMode.A2UI`? No — leave `output_mode=None` and phrase the prompt ("Show Worked Hours as a chart") so it re-enters the resolver.

---

## Implementation Blueprint

### Steps (in order)
1. Re-verify the FEAT-752 symbols — *why*: they did not exist when this task was written.
2. Write the provider — *why*: deterministic, no LLM.
3. Write tests binding a match with `bind_metric_match` / `reset_metric_match`.

### `packages/ai-parrot/src/parrot/metrics/suggestions.py` (CREATE)
```python
"""Deterministic follow-up chips from the stashed MetricMatch (FEAT-756 G7, FEAT-752 provider)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Sequence

from parrot.metrics.context import current_metric_match
from parrot.models.suggestions import Suggestion, SuggestionKind, SuggestionSource

if TYPE_CHECKING:
    from parrot.bots.suggestions.protocol import SuggestionContext

_LOGGER = logging.getLogger(__name__)
_SHAPES = ("KPICard", "Chart", "DataTable")


class MetricSuggestionProvider:
    """Chips: "vs previous period", "by <dimension>" (≤3), "as <other shape>"."""

    name: str = "metrics"
    lane: Literal["skill", "deterministic", "llm"] = "deterministic"

    def __init__(self, *, max_chips: int = 5) -> None:
        self.max_chips = max_chips

    async def suggest(self, ctx: "SuggestionContext") -> Sequence[Suggestion]:
        match = current_metric_match()
        if match is None:
            return []
        try:
            # FILL IN: build chips in order compare → dimensions[:3] → other shapes; labels ≤ 40 chars;
            #   skip "vs previous period" when match.metric.comparison.mode == "none"; cap at self.max_chips.
            return []
        except Exception as exc:
            _LOGGER.warning("metric suggestions failed: %s", exc)
            return []
```

### FILL IN checklist
- [ ] chip construction — bounded by G7 and the FEAT-752 `Suggestion` field limits

---

## Acceptance Criteria

- [ ] No stashed match → `[]`.
- [ ] Match with 2 dimensions + previous_period → compare chip, 2 dimension chips, shape chips, total ≤ `max_chips`.
- [ ] `comparison.mode == "none"` → no compare chip.
- [ ] Every chip validates as FEAT-752 `Suggestion`.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/metrics/test_suggestions.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/metrics/test_suggestions.py
from parrot.metrics.context import bind_metric_match, reset_metric_match
from parrot.metrics.suggestions import MetricSuggestionProvider

async def test_metric_suggestion_provider_chips(worked_hours_def): ...
async def test_no_match_returns_empty(): ...
async def test_comparison_none_skips_compare_chip(worked_hours_def): ...
```

---

## Agent Instructions

1. Confirm FEAT-752 TASK-4794 and TASK-4797 are merged on `dev` (`git log origin/dev -- packages/ai-parrot/src/parrot/bots/suggestions/protocol.py`). If not, STOP and leave this task pending.
2. Work in the feature worktree; confirm TASK-4846 is `done`.
3. Implement, run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, commit listed files, close with `scripts/sdd/close_task.sh TASK-4854 metric-definition-registry verified`.

## Completion Note

Unblocked after FEAT-752 landed on dev (merged into the feature branch, 65f3a58b9). Delivered by glm (nova), attempt 1,
merged via coder_merge; merge-tier validation green (74 passed). Review fix 4b6e0c912: the delivery omitted the
required 40-char label truncation, added `_clip` + test. Files: `parrot/metrics/suggestions.py`,
`tests/unit/metrics/test_suggestions.py`. Prior revert of the earlier premature merge is superseded.
