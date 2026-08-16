"""Unit tests for CompletionUsage.__add__ and AIMessage.total_usage()."""
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage


def test_add_tokens():
    a = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    b = CompletionUsage(prompt_tokens=20, completion_tokens=7, total_tokens=27)
    c = a + b
    assert (c.prompt_tokens, c.completion_tokens, c.total_tokens) == (30, 12, 42)
    assert c is not a and c is not b


def test_add_timing_none_aware():
    a = CompletionUsage(completion_time=1.0)
    b = CompletionUsage()
    assert (a + b).completion_time == 1.0
    assert (b + b).completion_time is None


def test_add_timing_both_set():
    a = CompletionUsage(prompt_time=1.5, queue_time=0.5, total_time=2.0)
    b = CompletionUsage(prompt_time=2.5, queue_time=0.5, total_time=3.0)
    c = a + b
    assert c.prompt_time == 4.0
    assert c.queue_time == 1.0
    assert c.total_time == 5.0


def test_add_estimated_cost_none_aware():
    a = CompletionUsage(estimated_cost=0.01)
    b = CompletionUsage()
    assert (a + b).estimated_cost == 0.01
    assert (b + b).estimated_cost is None
    c = CompletionUsage(estimated_cost=0.02)
    assert (a + c).estimated_cost == 0.03


def test_add_extra_merge_right_wins():
    a = CompletionUsage(extra_usage={"x": 1, "shared": "a"})
    b = CompletionUsage(extra_usage={"y": 2, "shared": "b"})
    assert (a + b).extra_usage == {"x": 1, "y": 2, "shared": "b"}


def test_add_returns_not_implemented_for_other_types():
    a = CompletionUsage(prompt_tokens=1)
    assert a.__add__("not-a-usage") is NotImplemented


def test_add_does_not_mutate_operands():
    a = CompletionUsage(prompt_tokens=10)
    b = CompletionUsage(prompt_tokens=20)
    _ = a + b
    assert a.prompt_tokens == 10
    assert b.prompt_tokens == 20


def test_total_usage_identity():
    msg = AIMessage(
        input="q", output="a", model="m", provider="p",
        usage=CompletionUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    )
    assert msg.total_usage() is msg.usage
