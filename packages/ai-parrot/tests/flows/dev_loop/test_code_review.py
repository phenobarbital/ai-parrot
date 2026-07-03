"""Tests for the multi-dispatcher code review gate (FEAT-270)."""

import pytest

from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
)


class _DummyReviewer(AbstractCodeReviewDispatcher):
    agent_name = "dummy"

    async def review(self, *, brief, run_id, node_id, cwd):
        return None  # placeholder

    def build_review_profile(self):
        return None  # placeholder


class TestCodeReviewDispatcherFactory:
    def test_register_and_create(self):
        CodeReviewDispatcherFactory.register("dummy")(_DummyReviewer)
        instance = CodeReviewDispatcherFactory.create("dummy")
        assert isinstance(instance, _DummyReviewer)

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown code review dispatcher"):
            CodeReviewDispatcherFactory.create("nonexistent")

    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            AbstractCodeReviewDispatcher()
