"""FEAT-783 TASK-4984 — CompletionUsage cache/reasoning counters."""

from parrot.models.basic import CompletionUsage


def test_aliases_populate_counters() -> None:
    """Provider aliases populate the canonical cache counter fields."""
    cache_read_input = CompletionUsage(cache_read_input_tokens=11)
    cached_input = CompletionUsage(cached_input_tokens=12)
    cache_creation_input = CompletionUsage(cache_creation_input_tokens=13)
    cache_write_input = CompletionUsage(cache_write_input_tokens=14)

    assert cache_read_input.cache_read_tokens == 11
    assert cached_input.cache_read_tokens == 12
    assert cache_creation_input.cache_creation_tokens == 13
    assert cache_write_input.cache_creation_tokens == 14


def test_add_sums_new_counters_fieldwise() -> None:
    """Addition preserves all cache and reasoning usage across rounds."""
    first = CompletionUsage(cache_read_tokens=2, cache_creation_tokens=3, reasoning_output_tokens=5)
    second = CompletionUsage(cache_read_tokens=7, cache_creation_tokens=11, reasoning_output_tokens=13)

    combined = first + second

    assert combined.cache_read_tokens == 9
    assert combined.cache_creation_tokens == 14
    assert combined.reasoning_output_tokens == 18


def test_from_claude_and_bedrock_populate_counters() -> None:
    """Claude and Bedrock factories retain raw cache usage and expose counters."""
    claude_payload = {
        "input_tokens": 20,
        "output_tokens": 4,
        "cache_read_input_tokens": 15,
        "cache_creation_input_tokens": 6,
    }
    bedrock_payload = {
        "inputTokens": 30,
        "outputTokens": 8,
        "cacheReadInputTokens": 17,
        "cacheWriteInputTokens": 9,
    }

    claude_usage = CompletionUsage.from_claude(claude_payload)
    bedrock_usage = CompletionUsage.from_bedrock(bedrock_payload)

    assert (claude_usage.cache_read_tokens, claude_usage.cache_creation_tokens) == (15, 6)
    assert claude_usage.extra_usage == claude_payload
    assert (bedrock_usage.cache_read_tokens, bedrock_usage.cache_creation_tokens) == (17, 9)
    assert bedrock_usage.extra_usage == {
        "cacheReadInputTokens": 17,
        "cacheWriteInputTokens": 9,
    }


def test_total_tokens_unchanged_by_cache_counters() -> None:
    """Cache counters remain an input breakdown rather than increasing totals."""
    usage = CompletionUsage(
        prompt_tokens=20,
        completion_tokens=5,
        total_tokens=25,
        cache_read_tokens=100,
        cache_creation_tokens=50,
    )

    assert usage.total_tokens == 25
