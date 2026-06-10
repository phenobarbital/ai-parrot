"""Tests for CompletionUsage's bidirectional token vocabulary.

CompletionUsage keeps the OpenAI naming (prompt/completion) as canonical but must
also speak the OTel-GenAI / Anthropic naming (input/output) on construction, read
and serialization, so it interoperates with any framework regardless of dialect.
"""

from __future__ import annotations

from parrot.models.basic import CompletionUsage


def test_construct_with_input_output_names():
    """input_tokens/output_tokens populate the canonical fields via validation_alias."""
    u = CompletionUsage(input_tokens=17, output_tokens=5, total_tokens=22)
    assert u.prompt_tokens == 17
    assert u.completion_tokens == 5
    assert u.input_tokens == 17
    assert u.output_tokens == 5


def test_construct_with_legacy_prompt_completion_names():
    """The legacy OpenAI naming still works (populate_by_name)."""
    u = CompletionUsage(prompt_tokens=8, completion_tokens=2)
    assert u.input_tokens == 8
    assert u.output_tokens == 2


def test_from_claude_exposes_both_vocabularies():
    """from_claude maps Anthropic's input/output dict to both readable names."""
    u = CompletionUsage.from_claude({"input_tokens": 100, "output_tokens": 30})
    assert (u.prompt_tokens, u.completion_tokens) == (100, 30)
    assert (u.input_tokens, u.output_tokens) == (100, 30)
    assert u.total_tokens == 130


def test_serialization_emits_both_vocabularies():
    """model_dump includes both prompt/completion and input/output keys."""
    dump = CompletionUsage(input_tokens=17, output_tokens=5).model_dump()
    assert dump["prompt_tokens"] == 17
    assert dump["completion_tokens"] == 5
    assert dump["input_tokens"] == 17
    assert dump["output_tokens"] == 5


def test_round_trip_is_stable():
    """Dumping then re-parsing yields identical token counts (no double-count)."""
    original = CompletionUsage(input_tokens=17, output_tokens=5, total_tokens=22)
    restored = CompletionUsage(**original.model_dump())
    assert restored.prompt_tokens == 17
    assert restored.completion_tokens == 5
    assert restored.input_tokens == 17
    assert restored.output_tokens == 5


def test_getattr_input_tokens_resolves_for_telemetry():
    """The observability layer reads usage.input_tokens via getattr; it must resolve.

    Regression: AnthropicClient emitted AfterClientCallEvent with
    getattr(usage, 'input_tokens') which returned None when CompletionUsage only
    had prompt_tokens — dropping tokens from spans, metrics and cost.
    """
    u = CompletionUsage.from_claude({"input_tokens": 42, "output_tokens": 7})
    assert getattr(u, "input_tokens", None) == 42
    assert getattr(u, "output_tokens", None) == 7
