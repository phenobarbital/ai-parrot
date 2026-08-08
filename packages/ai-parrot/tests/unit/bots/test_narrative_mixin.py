"""Unit tests for `NarrativeMixin` (FEAT-420 Module 5) — no live LLM calls."""

import logging
from typing import Any, Optional

from parrot.bots.mixins import NarrativeMixin
from parrot.tools.infographic_recipes.narrator import Narrator

FACTS = {
    "top_driver": {
        "division": "D",
        "project": "P",
        "ebitda_variance": -42000.0,
        "trend": -8000.0,
        "urgency": "immediate",
    },
    "n_snapshots": 3,
}


class _FakeAgent(NarrativeMixin):
    """Minimal harness — override the two seams the mixin depends on."""

    narrative_skill = "budget-narrative"

    def __init__(self, prose=None, exc=None, definition=object()):  # noqa: B008 - harmless shared sentinel
        self.logger = logging.getLogger("test")
        self._prose, self._exc, self._definition = prose, exc, definition

    async def _load_narrative_skill(self, name):
        return self._definition

    async def _call_llm_for_narrative(self, prompt):
        if self._exc:
            raise self._exc
        return self._prose


class TestNarrativeMixin:
    def test_satisfies_narrator_protocol(self):
        assert isinstance(_FakeAgent(), Narrator)

    async def test_returns_derivable_prose(self):
        # House style (SKILL.md/reference.md): fmt_money signs negatives with
        # U+2212 MINUS SIGN — matches the figure guard's signed comparison.
        agent = _FakeAgent(prose="  P slipped −$42.0K, still worsening.  ")
        result = await agent.narrate(FACTS, "budget-narrative")
        assert result.startswith("P slipped")

    async def test_missing_skill_returns_none(self, caplog):
        with caplog.at_level("WARNING"):
            result = await _FakeAgent(definition=None).narrate(FACTS, "nope")
        assert result is None
        assert any("not found" in r.getMessage() for r in caplog.records)

    async def test_llm_exception_returns_none(self, caplog):
        agent = _FakeAgent(exc=RuntimeError("boom"))
        with caplog.at_level("WARNING"):
            result = await agent.narrate(FACTS, "budget-narrative")
        assert result is None
        assert any("Narrative generation failed" in r.getMessage() for r in caplog.records)

    async def test_blank_output_returns_none(self):
        assert await _FakeAgent(prose="   ").narrate(FACTS, "budget-narrative") is None

    async def test_none_output_returns_none(self):
        assert await _FakeAgent(prose=None).narrate(FACTS, "budget-narrative") is None

    async def test_guard_failure_discards_everything(self):
        """One invented figure kills the whole narrative (G-H)."""
        agent = _FakeAgent(prose="P slipped −$42.0K. Also $999.9K vanished.")
        assert await agent.narrate(FACTS, "budget-narrative") is None

    async def test_guard_failure_does_not_log_full_prose(self, caplog):
        prose = "P slipped −$42.0K. Also $999.9K vanished."
        with caplog.at_level("WARNING"):
            await _FakeAgent(prose=prose).narrate(FACTS, "budget-narrative")
        assert prose not in caplog.text

    async def test_no_skill_name_returns_none(self, caplog):
        agent = _FakeAgent(prose="text")
        agent.narrative_skill = None
        with caplog.at_level("WARNING"):
            result = await agent.narrate(FACTS, "")
        assert result is None
        assert any("no skill name" in r.getMessage() for r in caplog.records)

    def test_module_has_no_domain_vocabulary(self):
        """G-I: the primitive must be domain-agnostic."""
        import inspect

        from parrot.bots.mixins import narrative

        src = inspect.getsource(narrative).lower()
        for word in ("ebitda", "revenue", "budget variance"):
            assert word not in src, f"domain vocabulary leaked: {word}"

    def test_no_hardcoded_model(self):
        import inspect

        from parrot.bots.mixins import narrative

        src = inspect.getsource(narrative)
        for token in ("gemini", "nova", "gpt-", "claude-"):
            assert token not in src.lower()

    def test_does_not_reference_deprecated_enhance_lane(self):
        import inspect

        from parrot.bots.mixins import narrative

        src = inspect.getsource(narrative)
        assert "_maybe_enhance" not in src and "enhance_infographic" not in src


class _CooperativeBase:
    """A stand-in for the agent class further down the MRO."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.base_init_called = True

    async def configure(self, *args: Any, **kwargs: Any) -> None:
        self.base_configure_called = True


class _ComposedAgent(NarrativeMixin, _CooperativeBase):
    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger("test")

    async def _load_narrative_skill(self, name: str) -> Optional[Any]:
        return None

    async def _call_llm_for_narrative(self, prompt: str) -> Optional[str]:
        return None


class TestCooperativeMixinDiscipline:
    """Acceptance: `__init__` and `configure` chain to `super()`."""

    def test_init_chains_to_super(self):
        agent = _ComposedAgent()
        assert agent.base_init_called is True

    async def test_configure_chains_to_super(self):
        agent = _ComposedAgent()
        await agent.configure()
        assert agent.base_configure_called is True
