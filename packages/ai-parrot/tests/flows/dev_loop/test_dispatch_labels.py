"""Unit tests for DispatchLabels + the shared label ContextVar (FEAT-496 TASK-2722)."""

import asyncio

import pytest
from parrot.flows.dev_loop.dispatchers._shared import (
    _DISPATCH_LABELS_CTX,
    bind_labels,
    current_labels,
)
from parrot.flows.dev_loop.models import DispatchLabels


class TestDispatchLabels:
    def test_empty_labels_add_no_keys(self):
        assert DispatchLabels().as_payload() == {}

    def test_as_payload_omits_empty_fields(self):
        p = DispatchLabels(task_id="TASK-1857", seat="development.w1").as_payload()
        assert p == {"task_id": "TASK-1857", "seat": "development.w1"}

    def test_as_payload_includes_attempt_only_when_gt_one(self):
        assert "attempt" not in DispatchLabels(attempt=1).as_payload()
        assert DispatchLabels(attempt=2).as_payload()["attempt"] == 2

    def test_frozen(self):
        with pytest.raises(Exception):
            DispatchLabels().task_id = "nope"


class TestLabelContext:
    def test_current_labels_defaults_to_none(self):
        assert current_labels() is None

    def test_bind_and_reset(self):
        token = bind_labels(DispatchLabels(task_id="TASK-1"))
        try:
            assert current_labels().task_id == "TASK-1"
        finally:
            _DISPATCH_LABELS_CTX.reset(token)
        assert current_labels() is None

    @pytest.mark.asyncio
    async def test_labels_are_task_local(self):
        """Two concurrent tasks must never see each other's labels — the
        safety property the whole ContextVar approach rests on."""
        seen = {}

        async def seat(name):
            token = bind_labels(DispatchLabels(seat=name))
            try:
                await asyncio.sleep(0)  # force interleaving
                seen[name] = current_labels().seat
            finally:
                _DISPATCH_LABELS_CTX.reset(token)

        await asyncio.gather(seat("development.w1"), seat("development.w2"))
        assert seen == {
            "development.w1": "development.w1",
            "development.w2": "development.w2",
        }
