# TASK-4798: Deterministic providers — skill, presentation, explain

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4794, TASK-4795, TASK-4796, TASK-4797
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (provider half) and the binding rules in §7 "Presentation rules", "Explain rule", "Skill rule"
(rev 0.2: the skill provider reads `current_turn_skill()`, not `current_active_skill()`). These three providers make
the feature useful without any LLM call and are registered by default in TASK-4800.

---

## Scope

- Create `parrot/bots/suggestions/providers.py` with `has_tabular_data()`, `SkillSuggestionProvider`,
  `PresentationSuggestionProvider`, `ExplainSuggestionProvider`.
- Tests in `tests/bots/test_suggestion_providers.py`.

**NOT in scope**: re-exporting from `parrot.bots.suggestions/__init__.py` (TASK-4800 does it — avoids a file overlap
with TASK-4799); the LLM provider (TASK-4799); bot kwargs such as `presentation_modes` (TASK-4800 sets the attribute,
this task only reads it with `getattr`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/suggestions/providers.py` | CREATE | Three providers + helper |
| `packages/ai-parrot/tests/bots/test_suggestion_providers.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.suggestions import Suggestion, SuggestionKind, SuggestionSource  # TASK-4794
from parrot.models.responses import AIMessage                      # verified: models/responses.py:93
from parrot.models.outputs import OutputMode                       # verified: models/outputs.py:23
from parrot.skills.tenancy import current_turn_skill               # TASK-4795 (tenancy.py)
from parrot.skills.tenancy import set_active_skill                 # verified: skills/tenancy.py:102 (tests only)
from parrot.skills.models import SkillDefinition, SkillSuggestion  # skills/models.py:60; SkillSuggestion from TASK-4796
from parrot.bots.suggestions.protocol import SuggestionContext     # TASK-4797
from parrot.bots.suggestions.engine import renderer_available      # TASK-4797
from navconfig.logging import logging                              # verified: bots/abstract.py:20
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):
    data: Optional[Any] = Field(default=None, ...)            # line 100 — list[dict] / DataFrame / None
    output_mode: OutputMode = Field(default=OutputMode.DEFAULT, ...)  # line 201
# packages/ai-parrot/src/parrot/models/outputs.py
#   OutputMode.STRUCTURED_TABLE = "structured_table" (53), STRUCTURED_CHART = "structured_chart" (52), CARD = "card" (44)
# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):                 # line 40
    async def followup(self, question: str, turn_id: str, data: Any, ...) -> AIMessage: ...   # line 1510
```

### Does NOT Exist
- ~~`AbstractBot.followup()`~~ — only `BasicAgent` has it; use `callable(getattr(bot, "followup", None))`.
- ~~`current_active_skill()` as the skill source here~~ — it is always `None` after the prompt build; use
  `current_turn_skill()` (spec rev 0.2).
- ~~`OutputMode.KPI`~~ — the KPI chip uses `OutputMode.CARD`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/suggestions/providers.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/test_suggestion_providers.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent.followup"
  ]
}
```

---

## Implementation Notes (binding — spec §7)

- **Presentation**: only when `has_tabular_data(response)`. Candidates in order: `STRUCTURED_TABLE` →
  `View as table` / `Show the previous answer as a table`; `STRUCTURED_CHART` → `View as chart` /
  `Show the previous answer as a chart`; `CARD` → `View as KPI` /
  `Show the headline figure of the previous answer as a KPI card`. `kind=presentation`, `source=provider`,
  `output_mode=<mode>`. Skip `ctx.output_mode` and `response.output_mode`; skip modes where `renderer_available`
  is False. Mode list priority: constructor `modes` → `getattr(bot, "presentation_modes", None)` → defaults.
- **Explain**: one chip `label="Explain this"`, `prompt="Explain this answer"`, `kind=action`, `action="explain"`,
  `source=provider` iff `has_tabular_data(response)` and `callable(getattr(bot, "followup", None))`.
- **Skill**: map `current_turn_skill().suggestions` 1:1, `source=skill`; `kind=presentation` iff `output_mode` set,
  else `followup`. An `output_mode` that is not an `OutputMode` value → drop that chip with `logger.warning`, never raise.
- `has_tabular_data`: True for a non-empty `list` whose items are all `dict`, or an object with `to_dict` and
  `to_string` that is not `.empty` (DataFrame-like). Everything else False.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module from the block below; fill the three `suggest` bodies per the binding notes — *why*: §7 is binding.
2. Tests (fixtures from spec §4); run Validation Commands.

### `packages/ai-parrot/src/parrot/bots/suggestions/providers.py` (CREATE)
```python
"""Built-in deterministic suggestion providers (FEAT-752)."""
from __future__ import annotations

from typing import Any, ClassVar, Optional, Sequence

from navconfig.logging import logging

from parrot.models.outputs import OutputMode
from parrot.models.responses import AIMessage
from parrot.models.suggestions import Suggestion, SuggestionKind, SuggestionSource
from parrot.skills.tenancy import current_turn_skill

from .engine import renderer_available
from .protocol import SuggestionContext

logger = logging.getLogger(__name__)


def has_tabular_data(response: AIMessage) -> bool:
    """True for a non-empty list of dicts in ``response.data`` or a non-empty DataFrame-like object."""
    # FILL IN: per Implementation Notes — bounded by test_has_tabular_data
    raise NotImplementedError


class SkillSuggestionProvider:
    """lane="skill". Emits the turn skill's declared chips (FEAT-752, spec rev 0.2)."""

    name = "skill"
    lane = "skill"

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        skill = current_turn_skill()
        if skill is None or not getattr(skill, "suggestions", None):
            return []
        # FILL IN: map per "Skill" rule; invalid output_mode -> logger.warning + skip that chip
        raise NotImplementedError


class PresentationSuggestionProvider:
    """lane="deterministic". Offers "View as table / chart / KPI" for modes the server can render."""

    name = "presentation"
    lane = "deterministic"
    DEFAULT_MODES: ClassVar[tuple[tuple[OutputMode, str, str], ...]] = (
        (OutputMode.STRUCTURED_TABLE, "View as table", "Show the previous answer as a table"),
        (OutputMode.STRUCTURED_CHART, "View as chart", "Show the previous answer as a chart"),
        (OutputMode.CARD, "View as KPI", "Show the headline figure of the previous answer as a KPI card"),
    )

    def __init__(self, bot: Any, *, modes: Optional[Sequence[OutputMode]] = None) -> None:
        self.bot = bot
        self._modes = modes

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        if not has_tabular_data(ctx.response):
            return []
        # FILL IN: resolve allowed modes (constructor > bot.presentation_modes > all DEFAULT_MODES), keep DEFAULT_MODES
        #          order, skip current modes and unavailable renderers — bounded by test_presentation_provider_rules
        raise NotImplementedError


class ExplainSuggestionProvider:
    """lane="deterministic". One "Explain this" action chip for data answers on bots that support followup."""

    name = "explain"
    lane = "deterministic"

    def __init__(self, bot: Any) -> None:
        self.bot = bot

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        if not has_tabular_data(ctx.response) or not callable(getattr(self.bot, "followup", None)):
            return []
        return [Suggestion(label="Explain this", prompt="Explain this answer", kind=SuggestionKind.ACTION,
                           action="explain", source=SuggestionSource.PROVIDER)]
```
**Why this shape**: class names, `name`/`lane` values and constructor signatures are fixed by spec §3 M3. The
provider uses `ctx.bot` only through `self.bot` captured at construction (the engine passes the same bot).

### FILL IN checklist
- [ ] `has_tabular_data` — list-of-dicts / DataFrame-like rule.
- [ ] `SkillSuggestionProvider.suggest` — 1:1 mapping, invalid mode dropped.
- [ ] `PresentationSuggestionProvider.suggest` — mode resolution and skips.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] Skill chips are emitted iff `current_turn_skill()` is a skill with `suggestions`; an invalid `output_mode`
      string drops only that chip.
- [ ] Presentation: no data → `[]`; current mode excluded; mode with no renderer excluded; order table → chart → KPI.
- [ ] Explain: emitted only with tabular data **and** a callable `followup` on the bot.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_suggestion_providers.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_suggestion_providers.py
from pathlib import Path
import pytest
from parrot.bots.suggestions import SuggestionContext
from parrot.bots.suggestions import engine as engine_mod
from parrot.bots.suggestions.providers import (
    ExplainSuggestionProvider, PresentationSuggestionProvider, SkillSuggestionProvider, has_tabular_data,
)
from parrot.models import AIMessage
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode
from parrot.skills.models import SkillDefinition, SkillSuggestion
from parrot.skills.tenancy import enter_active_skill_scope, exit_active_skill_scope, set_active_skill


@pytest.fixture
def ai_message_with_table() -> AIMessage:
    return AIMessage(input="q", output="text", data=[{"month": "Sep", "sales": 10}, {"month": "Oct", "sales": 12}],
                     model="fake", provider="fake", usage=CompletionUsage(), output_mode=OutputMode.DEFAULT)


class BotWithFollowup:
    async def followup(self, *a, **k):
        return None


def _ctx(msg, bot, mode=OutputMode.DEFAULT):
    return SuggestionContext(question="q", response=msg, output_mode=mode, bot=bot)


async def test_skill_provider_emits_only_turn_skill(ai_message_with_table):
    token = enter_active_skill_scope()
    try:
        assert await SkillSuggestionProvider(None).suggest(_ctx(ai_message_with_table, None)) == []
        # FILL IN: set_active_skill(<SkillDefinition with 2 SkillSuggestion, one output_mode="card", one "bogus">),
        #          then set_active_skill(None) (prompt-build clear) and assert the valid chips are still emitted
    finally:
        exit_active_skill_scope(token)


async def test_presentation_provider_rules(ai_message_with_table, monkeypatch):
    # FILL IN: no data -> []; ctx mode STRUCTURED_TABLE excluded; monkeypatch engine_mod.get_renderer to raise for CARD
    ...


async def test_explain_provider_requires_data_and_followup(ai_message_with_table):
    # FILL IN: object() bot -> []; BotWithFollowup() -> one chip with action == "explain"
    ...


def test_has_tabular_data():
    # FILL IN: [] / None / "x" / [1, 2] -> False; [{"a": 1}] -> True
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4798 followup-suggestion-chips verified`).

---

## Completion Note

*(Agent fills this in when done)*
