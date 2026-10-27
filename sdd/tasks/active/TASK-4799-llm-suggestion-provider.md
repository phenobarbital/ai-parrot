# TASK-4799: `LLMSuggestionProvider` (opt-in LLM lane)

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4794, TASK-4797
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, §7 "LLM prompt" (binding template), and rev 0.2 Q2 (resolved: a `model` override so an agent on
an expensive model can run the chip call on a cheap tier). The provider produces grounded follow-up questions with
ONE `AbstractClient.invoke()` call — never `ask()`, never `self.invoke()` on the bot — and records its cost for the
engine to copy into `metadata["suggestions"]["llm"]`.

---

## Scope

- Create `parrot/bots/suggestions/llm.py` with `SUGGESTION_PROMPT`, `_answer_text()`, `LLMSuggestionProvider`.
- Constructor takes `model: Optional[str] = None`, forwarded as `invoke(model=...)` (Q2).
- Tests in `tests/bots/test_suggestion_llm_provider.py` (fake client fixture from spec §4).

**NOT in scope**: timeout (the engine's `asyncio.wait_for` owns it); bot kwarg `suggestion_model` (TASK-4800 passes it
in); `__init__.py` re-exports (TASK-4800).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/suggestions/llm.py` | CREATE | LLM provider |
| `packages/ai-parrot/tests/bots/test_suggestion_llm_provider.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.suggestions import Suggestion, SuggestionBatch, SuggestionKind, SuggestionSource  # TASK-4794
from parrot.models.responses import AIMessage, InvokeResult        # verified: models/responses.py:93, :1329
from parrot.models.basic import CompletionUsage                    # verified: models/basic.py:48
from parrot.bots.suggestions.protocol import SuggestionContext     # TASK-4797
from navconfig.logging import logging                              # verified: bots/abstract.py:20
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    async def invoke(self, prompt: str, *, output_type: Optional[type] = None, structured_output=None,
                     model: Optional[str] = None, system_prompt: Optional[str] = None, max_tokens: Optional[int] = None,
                     temperature: float = 0.0, use_tools: bool = False, tools: Optional[list] = None) -> InvokeResult
                     # line 1952-1964
    def _resolve_invoke_model(self, model: Optional[str] = None) -> str  # line 2054 (explicit > self.model > lightweight)
# packages/ai-parrot/src/parrot/bots/abstract.py
def get_client(self) -> AbstractClient: return self._llm      # line 1218-1229 (mixins such as ModelSwitchingMixin override)
# Enter pattern (bots/mixins/narrative.py:199-201):
#     client = self.get_client()
#     async with client as entered:
#         response = await ...entered...
# packages/ai-parrot/src/parrot/models/responses.py
class InvokeResult(BaseModel): output: Any; output_type; model: str; usage: CompletionUsage; raw_response; budget_report  # 1329
class AIMessage: @property to_text -> str                    # line 246-247
```

### Does NOT Exist
- ~~`BaseBot.invoke()` → `AbstractClient.invoke()`~~ — the bot's `invoke` runs `execute_llm_call(client, "ask")`
  (`bots/base.py:748-771`). Never call `ctx.bot.invoke(...)` or `client.ask(...)` here.
- ~~`AbstractBot._lightweight_model`~~ — that attribute is on `AbstractClient` (`clients/base.py:309`).
- ~~`AIMessage.text`~~ — use the `to_text` property.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/suggestions/llm.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/test_suggestion_llm_provider.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient.invoke",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.get_client",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#InvokeResult"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the module from the block; fill `suggest()` — *why*: binding template + forced fields per spec §7.
2. Tests with the fake client; run Validation Commands.

### `packages/ai-parrot/src/parrot/bots/suggestions/llm.py` (CREATE)
```python
"""LLM follow-up suggestion provider (FEAT-752) — one lightweight invoke() per answer."""
from __future__ import annotations

import time
from typing import Any, Final, Optional, Sequence

from navconfig.logging import logging

from parrot.models.responses import AIMessage
from parrot.models.suggestions import Suggestion, SuggestionBatch, SuggestionKind, SuggestionSource

from .protocol import SuggestionContext

logger = logging.getLogger(__name__)

SUGGESTION_PROMPT: Final[str] = (
    "You suggest at most {max_items} short follow-up questions a user might ask next, grounded ONLY on the "
    "exchange below.\nRules: each label ≤ 40 characters, each prompt is a complete question the assistant can "
    "answer with the same data\nor context, no duplicates of the original question, no presentation changes (those "
    "are offered separately), no\nactions. Respond with the structured schema only.\n\n"
    "Question: {question}\nAnswer (may be truncated): {answer_text}\n"
)


def _answer_text(response: AIMessage, limit: int) -> str:
    """``response.to_text`` truncated to ``limit`` characters (empty string on failure)."""
    try:
        text = response.to_text or ""
    except Exception:  # noqa: BLE001 — to_text must never break the lane
        text = ""
    return text[:limit]


class LLMSuggestionProvider:
    """lane="llm". Grounded follow-ups via ``bot.get_client()`` → ``invoke(output_type=SuggestionBatch)``."""

    name = "llm"
    lane = "llm"

    def __init__(self, bot: Any, *, max_items: int = 4, max_tokens: int = 256, answer_chars: int = 2000,
                 temperature: float = 0.3, model: Optional[str] = None) -> None:
        self.bot = bot
        self.max_items = max_items
        self.max_tokens = max_tokens
        self.answer_chars = answer_chars
        self.temperature = temperature
        self.model = model  # Q2: None keeps AbstractClient._resolve_invoke_model's choice
        self._last_cost: Optional[dict[str, Any]] = None

    @property
    def last_cost(self) -> Optional[dict[str, Any]]:
        """Cost record of the most recent successful call, or None."""
        return self._last_cost

    async def suggest(self, ctx: SuggestionContext) -> Sequence[Suggestion]:
        self._last_cost = None
        prompt = SUGGESTION_PROMPT.format(max_items=self.max_items, question=ctx.question,
                                          answer_text=_answer_text(ctx.response, self.answer_chars))
        started = time.perf_counter()
        try:
            client = self.bot.get_client()
            async with client as entered:
                result = await entered.invoke(prompt, output_type=SuggestionBatch, model=self.model,
                                              max_tokens=self.max_tokens, temperature=self.temperature)
        except Exception as exc:  # noqa: BLE001 — never fail the answer
            logger.warning("LLM suggestion call failed: %s", exc)
            return []
        # FILL IN: accept result.output when it is a SuggestionBatch (else try SuggestionBatch.model_validate on a dict;
        #          any failure -> []); rebuild each chip with source=LLM, kind=FOLLOWUP, output_mode=None, action=None;
        #          truncate to self.max_items; set self._last_cost = {"model": result.model,
        #          "usage": result.usage.model_dump(), "elapsed_ms": <ms since started>} — bounded by spec §7 "LLM prompt"
        raise NotImplementedError
```
**Why this shape**: the template text and `invoke` kwargs are binding (spec §7); `model=None` reproduces the spec's
default resolution exactly. Do NOT add `system_prompt` (client default) and do NOT wrap in `wait_for` (engine does).

### FILL IN checklist
- [ ] `LLMSuggestionProvider.suggest` — output coercion, forced fields, cap, cost record.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] Fake client: `invoke` called exactly once with `output_type=SuggestionBatch`, `max_tokens=256`,
      `temperature=0.3`; `ask` never called.
- [ ] `model="cheap-model"` passed to the constructor reaches `invoke(model="cheap-model")`; default passes `None`.
- [ ] More than `max_items` chips truncated; every chip has `source == "llm"`, `kind == "followup"`,
      `output_mode is None`, `action is None` even if the model returned otherwise.
- [ ] `last_cost` has `model`, `usage`, `elapsed_ms`; `invoke` raising → `[]` and `last_cost is None`.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_suggestion_llm_provider.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_suggestion_llm_provider.py
import pytest
from parrot.bots.suggestions import SuggestionContext
from parrot.bots.suggestions.llm import LLMSuggestionProvider
from parrot.models import AIMessage, Suggestion, SuggestionBatch
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode
from parrot.models.responses import InvokeResult


class FakeClient:
    def __init__(self, output=None, exc=None):
        self.calls, self._output, self._exc = [], output, exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def invoke(self, prompt, **kw):
        self.calls.append((prompt, kw))
        if self._exc:
            raise self._exc
        return InvokeResult(output=self._output, output_type=SuggestionBatch, model="fake-lite", usage=CompletionUsage())

    async def ask(self, *a, **k):
        raise AssertionError("ask must not be called")


class FakeBot:
    def __init__(self, client):
        self._client = client

    def get_client(self):
        return self._client


def _ctx(bot):
    msg = AIMessage(input="q", output="answer", model="m", provider="p", usage=CompletionUsage())
    return SuggestionContext(question="q", response=msg, output_mode=OutputMode.DEFAULT, bot=bot)


async def test_llm_provider_uses_invoke_not_ask():
    batch = SuggestionBatch(suggestions=[Suggestion(label="Why?", prompt="Why did it change?")])
    client = FakeClient(output=batch)
    chips = await LLMSuggestionProvider(FakeBot(client)).suggest(_ctx(FakeBot(client)))
    assert len(client.calls) == 1 and client.calls[0][1]["output_type"] is SuggestionBatch
    assert chips[0].source == "llm"


async def test_llm_provider_model_override():
    # FILL IN
    ...


async def test_llm_provider_cost_recorded_and_capped():
    # FILL IN: max_items=2 with 4 returned chips (one with kind="presentation", output_mode="card") -> 2 forced chips
    ...


async def test_llm_provider_failure_is_silent():
    # FILL IN: FakeClient(exc=RuntimeError()) -> [] and last_cost is None
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4799 followup-suggestion-chips verified`).

---

## Completion Note

*(Agent fills this in when done)*
