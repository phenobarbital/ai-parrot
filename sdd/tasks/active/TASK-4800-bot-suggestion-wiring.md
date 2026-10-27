# TASK-4800: Bot wiring — kwargs, registry, `_attach_suggestions`, `ask`/`ask_stream` call sites

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4797, TASK-4798, TASK-4799
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview, §3 Module 2 (bot half), rev 0.2 (Q2 `suggestion_model`; Q4 — YAML agent definitions already
forward arbitrary constructor kwargs through `BotMetadata.get_instance()`, `registry/registry.py:108,155`, so no
whitelist change is needed). This task connects the engine and the four built-in providers to every bot: opt-in
kwargs, the public `register_suggestion_provider()` (FEAT-756's hook), and one attach call after the output
pipeline in each entry point.

---

## Scope

- `AbstractBot.__init__`: read `enable_suggestions`, `suggest_followups`, `suggestion_timeout_s`,
  `max_suggestions`, `suggestion_model`, `presentation_modes` from `kwargs`.
- `AbstractBot` methods (before `_apply_default_output_mode`): `register_suggestion_provider`,
  `_default_suggestion_providers`, `_get_suggestion_engine`, `_suggestion_lanes`, `_attach_suggestions`.
- `BaseBot.ask()` / `ask_stream()`: one `_attach_suggestions` call each, after `_run_output_pipeline`.
- `parrot/bots/suggestions/__init__.py`: add the provider re-exports.
- Tests in `tests/bots/test_suggestion_bot_wiring.py` (unit + the spec's end-to-end test with a fake client).

**NOT in scope**: server/handler changes (TASK-4801/4802); new mixins; changes to `create_system_prompt` or
`_on_post_ask` (fire-and-forget — must NOT be used as the attachment point).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Kwargs + five methods |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Two call sites |
| `packages/ai-parrot/src/parrot/bots/suggestions/__init__.py` | MODIFY | Provider re-exports |
| `packages/ai-parrot/tests/bots/test_suggestion_bot_wiring.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# abstract.py already imports (verified): `from __future__ import annotations` (:5), Optional/Sequence/List (:6),
#   AIMessage (:37), OutputMode (:69), navconfig logging (:20); TYPE_CHECKING block at :81.
from parrot.bots.suggestions import SuggestionContext, SuggestionEngine, SuggestionProvider   # TASK-4797
from parrot.bots.suggestions.providers import (                                               # TASK-4798
    ExplainSuggestionProvider, PresentationSuggestionProvider, SkillSuggestionProvider)
from parrot.bots.suggestions.llm import LLMSuggestionProvider                                 # TASK-4799
from parrot.skills.tenancy import current_turn_skill                                          # TASK-4795
from parrot.observability.context import current_tenant  # verified: skills/tenancy.py:15; base.py uses current_tenant.get() (:608)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):  # :201
    # __init__:  self.formatter = OutputFormatter()          # :555
    #            self.default_output_mode = output_mode       # :556  ← kwargs block goes right after
    def get_client(self) -> AbstractClient: ...               # :1218
    async def _resolve_output_mode(self, query, ctx) -> Optional[OutputMode]: ...  # :4168-4189
    def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode:  # :4191 ← new methods go above
# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot(AbstractBot):                                                        # :91
    async def ask(self, question: str, session_id=None, user_id=None, ..., output_mode: OutputMode = OutputMode.DEFAULT, ...)  # :1063
    #   _skill_scope = enter_active_skill_scope()  :1133 ... exit_active_skill_scope(_skill_scope)  :1855
    #   response = await self._run_output_pipeline(response, method="ask")   :1735 ← attach right after
    async def ask_stream(self, question: str, session_id=None, user_id=None, ..., output_mode=OutputMode.DEFAULT, ...)  # :1867
    #   _skill_scope = enter_active_skill_scope()  :1911 ... exit  :2353
    #   ai_message = await self._run_output_pipeline(ai_message, method="ask_stream")  :2273
    #   linked-surface lift :2275-2286 ; AfterInvokeEvent :2288-2302 ; `yield ai_message` :2303 ← attach right before
```

### Does NOT Exist
- ~~`AbstractBot.enable_suggestions` & co.~~ — added here.
- ~~`_on_post_ask` as the attachment point~~ — fire-and-forget (`base.py:1766-1776`).
- ~~a kwargs whitelist in the YAML agent loader~~ — none; `startup_config` is forwarded verbatim (Q4).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/suggestions/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_suggestion_bot_wiring.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._apply_default_output_mode",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.get_client",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot.ask_stream"
  ]
}
```

---

## Implementation Notes

- **Import lazily** inside `_get_suggestion_engine` / `_default_suggestion_providers` / `_attach_suggestions`
  (`from .suggestions import ...`) — *because* `parrot.bots.suggestions.providers` imports `parrot.skills.tenancy`,
  and a module-level import from `abstract.py` risks an import cycle at package load. Put type-only names under the
  existing `if TYPE_CHECKING:` block (`abstract.py:81`).
- `_attach_suggestions` must never raise: wrap the engine call in `try/except Exception` + `self.logger.warning`.
- No-op guarantee (AC "byte-identical"): when `_suggestion_lanes() == {"skill"}` and `current_turn_skill()` has no
  `suggestions`, return `response` untouched — no `suggestions`, no `metadata["suggestions"]`.
- Write `response.metadata = {**(response.metadata or {}), "suggestions": meta}` (same style as `base.py:2283-2286`).

---

## Implementation Blueprint

### Steps (in order)
1. Add the kwargs block in `__init__` — *why*: opt-in flags (G2), `suggestion_model` (Q2), `presentation_modes` (§7).
2. Add the five methods above `_apply_default_output_mode` — *why*: cooperative hook surface (spec §7 Patterns).
3. Add the two call sites in `base.py` — *why*: attach after the answer is final, before it leaves the bot.
4. Extend `bots/suggestions/__init__.py` re-exports.
5. Tests; run Validation Commands (incl. the existing output-mode / linked-surface bot tests).

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — kwargs)
```python
# occurrences: 1 (verified: grep -c '        self.default_output_mode = output_mode' packages/ai-parrot/src/parrot/bots/abstract.py)
# AFTER — insert below `        self.default_output_mode = output_mode` (verified: abstract.py:556)
        # Follow-up suggestion chips (FEAT-752) — all opt-in.
        self.suggest_followups: bool = bool(kwargs.get("suggest_followups", False))
        self.enable_suggestions: bool = bool(kwargs.get("enable_suggestions", False)) or self.suggest_followups
        self.suggestion_timeout_s: float = float(kwargs.get("suggestion_timeout_s", 4.0))
        self.max_suggestions: int = int(kwargs.get("max_suggestions", 6))
        self.suggestion_model: Optional[str] = kwargs.get("suggestion_model")
        if "presentation_modes" in kwargs:
            self.presentation_modes = kwargs["presentation_modes"]
        self._suggestion_engine = None
```
**Why**: `presentation_modes` is only set when passed so a class attribute of the same name still wins (spec §7).

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — methods)
```python
# occurrences: 1 (verified: grep -c '    def _apply_default_output_mode(self, output_mode: OutputMode) -> OutputMode:' abstract.py)
# BEFORE — insert above that line (verified: abstract.py:4191)
    def register_suggestion_provider(self, provider: "SuggestionProvider", *, prepend: bool = False) -> None:
        """Register a follow-up chip provider (FEAT-756 plugs here). Builds the engine on first use."""
        self._get_suggestion_engine().register(provider, prepend=prepend)

    def _default_suggestion_providers(self) -> list:
        """Skill, presentation, explain and LLM providers bound to ``self``. Mixins may extend via ``super()``."""
        from .suggestions.llm import LLMSuggestionProvider
        from .suggestions.providers import (
            ExplainSuggestionProvider, PresentationSuggestionProvider, SkillSuggestionProvider)
        return [SkillSuggestionProvider(self), PresentationSuggestionProvider(self), ExplainSuggestionProvider(self),
                LLMSuggestionProvider(self, model=self.suggestion_model)]

    def _get_suggestion_engine(self) -> "SuggestionEngine":
        """Lazily create the engine with the bot's caps/timeout and register the default providers."""
        # FILL IN: if self._suggestion_engine is None -> SuggestionEngine(max_suggestions=self.max_suggestions,
        #          timeout_s=self.suggestion_timeout_s, logger=self.logger), register each default provider (append),
        #          store and return it — bounded by test_bot_register_provider_prepend
        raise NotImplementedError

    def _suggestion_lanes(self) -> frozenset[str]:
        """{"skill"} plus "deterministic" if enable_suggestions plus "llm" if suggest_followups."""
        lanes = {"skill"}
        if self.enable_suggestions:
            lanes.add("deterministic")
        if self.suggest_followups:
            lanes.add("llm")
        return frozenset(lanes)

    async def _attach_suggestions(self, question: str, response: AIMessage, *, output_mode: OutputMode,
                                  user_id: Optional[str] = None, session_id: Optional[str] = None) -> AIMessage:
        """Collect chips into ``response.suggestions`` + ``metadata["suggestions"]``. Never raises; same instance."""
        # FILL IN: no-op guard (Implementation Notes) using current_turn_skill(); build SuggestionContext(question,
        #          response, output_mode, bot=self, user_id, session_id, tenant=current_tenant.get()); await
        #          engine.collect(ctx, lanes=self._suggestion_lanes()); assign; try/except + self.logger.warning
        return response
```

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY — ask)
```python
# occurrences: 1 (verified: grep -c '                response = await self._run_output_pipeline(response, method="ask")' base.py)
# AFTER — insert below that line (verified: base.py:1735)
                # FEAT-752: follow-up chips, attached once the answer is final.
                response = await self._attach_suggestions(
                    question, response, output_mode=output_mode, user_id=user_id, session_id=session_id
                )
```

### `packages/ai-parrot/src/parrot/bots/base.py` (MODIFY — ask_stream)
```python
# occurrences: 1 (verified: grep -c '                    yield ai_message' base.py)
# BEFORE — insert above `                    yield ai_message` (verified: base.py:2303)
                    # FEAT-752: chips travel only in the final AIMessage (final stream envelope), never in text chunks.
                    ai_message = await self._attach_suggestions(
                        question, ai_message, output_mode=output_mode, user_id=user_id, session_id=session_id
                    )
```
**Why**: `output_mode`, `user_id`, `session_id` are the method parameters (verified in both signatures,
`base.py:1063-1082`, `:1867-1884`). `output_mode` is rebound in place to the effective mode before these lines
(router `:1157`, agent default `:1163` / `:1925`, error fallbacks `:1609`, `:1670`), so passing the local
`output_mode` is already the effective one — do not re-resolve it.

### `packages/ai-parrot/src/parrot/bots/suggestions/__init__.py` (MODIFY)
```python
# Replace the file body (created by TASK-4797) with the full re-export list:
from .engine import SuggestionEngine, renderer_available
from .llm import LLMSuggestionProvider
from .protocol import LANES, SuggestionContext, SuggestionProvider
from .providers import (ExplainSuggestionProvider, PresentationSuggestionProvider, SkillSuggestionProvider,
                        has_tabular_data)

__all__ = ("LANES", "ExplainSuggestionProvider", "LLMSuggestionProvider", "PresentationSuggestionProvider",
           "SkillSuggestionProvider", "SuggestionContext", "SuggestionEngine", "SuggestionProvider",
           "has_tabular_data", "renderer_available")
```

### FILL IN checklist
- [ ] `_get_suggestion_engine` — lazy build + default registration.
- [ ] `_attach_suggestions` — guard, context, collect, assign, never raise.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] Bot without opt-in and no turn skill → `suggestions == []`, no `metadata["suggestions"]`.
- [ ] `enable_suggestions=True` + tabular data → presentation + explain chips; `suggest_followups=True` adds the LLM lane
      (fake client: `invoke` once, `ask` never) and `metadata["suggestions"]["llm"]` is populated.
- [ ] `register_suggestion_provider(p, prepend=True)` with a provider class defined in the test module runs before
      the built-ins of the same lane.
- [ ] `ask()` and `ask_stream()` each call `_attach_suggestions` exactly once, after `_run_output_pipeline`
      (source-level test, same technique as `test_linked_surface_lifting.py`).
- [ ] Existing tests in the Validation Commands stay green; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_suggestion_bot_wiring.py -q`
- `pytest packages/ai-parrot/tests/bots/test_linked_surface_lifting.py -q`
- `pytest packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_suggestion_bot_wiring.py
import inspect
import logging
import pytest
from parrot.models import AIMessage
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode


def _base_bot_cls():
    try:
        from parrot.bots.base import BaseBot
    except Exception as exc:  # noqa: BLE001 — same guard as test_linked_surface_lifting.py:19-24
        pytest.skip(f"cannot import parrot.bots.base: {exc}")
    return BaseBot


def _bare_bot(**flags):
    """BaseBot instance without __init__: set only what the suggestion surface reads."""
    bot = object.__new__(_base_bot_cls())
    bot.logger = logging.getLogger("test")
    bot.suggest_followups = flags.get("suggest_followups", False)
    bot.enable_suggestions = flags.get("enable_suggestions", False) or bot.suggest_followups
    bot.suggestion_timeout_s, bot.max_suggestions, bot.suggestion_model = 1.0, 6, None
    bot._suggestion_engine = None
    return bot


def _msg(data=None):
    return AIMessage(input="q", output="a", data=data, model="m", provider="p", usage=CompletionUsage())


async def test_bot_attach_noop_without_optin():
    bot = _bare_bot()
    msg = await bot._attach_suggestions("q", _msg([{"a": 1}]), output_mode=OutputMode.DEFAULT)
    assert msg.suggestions == [] and "suggestions" not in msg.metadata


def test_ask_and_ask_stream_attach_once():
    cls = _base_bot_cls()
    for meth, pipeline in (("ask", 'method="ask")'), ("ask_stream", 'method="ask_stream")')):
        src = inspect.getsource(getattr(cls, meth))
        assert src.count("_attach_suggestions(") == 1
        assert src.index(pipeline) < src.index("_attach_suggestions(")


async def test_bot_register_provider_prepend():
    # FILL IN: define a provider class here (lane "deterministic"), register with prepend=True, assert first chip
    ...


async def test_suggestions_end_to_end_fake_client():
    # FILL IN: _bare_bot(suggest_followups=True), bot.get_client = lambda: FakeClient(...) (copy FakeClient from
    #          test_suggestion_llm_provider.py), a followup method, a turn skill with chips; assert order
    #          skill -> presentation -> explain -> llm and metadata["suggestions"]["llm"]["model"] == "fake-lite"
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4800 followup-suggestion-chips verified`).

---

## Completion Note

*(Agent fills this in when done)*
