"""LLM-family label parity sweep (FEAT-496 TASK-2728).

Enumerates every `LLMCodeDispatcher` subclass dynamically so a future
backend that forgets to accept `labels=` fails this test instead of
silently shipping unlabelled.
"""

import inspect

import pytest

from parrot.flows.dev_loop.dispatchers._shared import _DISPATCH_LABELS_CTX, bind_labels
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import DispatchLabels

# Import the subclass modules so they register on LLMCodeDispatcher before
# the sweep below runs.
import parrot.flows.dev_loop.dispatchers.nova
import parrot.flows.dev_loop.dispatchers.grok
import parrot.flows.dev_loop.dispatchers.zai
import parrot.flows.dev_loop.dispatchers.moonshot  # noqa: F401

ALL = [LLMCodeDispatcher, *LLMCodeDispatcher.__subclasses__()]


@pytest.mark.parametrize("cls", ALL, ids=lambda c: c.__name__)
def test_dispatch_accepts_labels(cls):
    sig = inspect.signature(cls.dispatch)
    assert "labels" in sig.parameters, f"{cls.__name__}.dispatch lacks labels="
    assert sig.parameters["labels"].default is None


def test_at_least_the_four_known_subclasses_are_covered():
    """Guards against an import regression silently shrinking the sweep."""
    names = {c.__name__ for c in LLMCodeDispatcher.__subclasses__()}
    assert {
        "NovaCodeDispatcher",
        "GrokCodeDispatcher",
        "ZaiCodeDispatcher",
        "MoonshotCodeDispatcher",
    } <= names


class TestLLMPayloadEnrichment:
    async def test_publish_event_stamps_labels_and_summary(self):
        from parrot.flows.dev_loop.dispatchers._shared import normalize_payload

        token = bind_labels(DispatchLabels(task_id="TASK-1", seat="development.w1"))
        try:
            out = normalize_payload(
                "dispatch.tool_use",
                {"tool_call_id": "call_1", "tool_name": "read_file", "arguments": "{}"},
            )
        finally:
            _DISPATCH_LABELS_CTX.reset(token)
        assert out["summary"]
        assert out["task_id"] == "TASK-1"
        assert out["seat"] == "development.w1"
        # pre-existing keys untouched
        assert out["tool_call_id"] == "call_1"
        assert out["tool_name"] == "read_file"
        assert out["arguments"] == "{}"
