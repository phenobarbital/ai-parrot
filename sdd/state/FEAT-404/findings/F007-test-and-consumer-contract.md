---
id: F007
query_id: Q009,Q010
type: grep
intent: Find the FEAT-397 test contract to mirror and confirm downstream consumers need no change
executed_at: 2026-08-03T00:11:00Z
parent_id: null
depth: 0
---

# F007 — Per-client test convention exists; the only consumer is `MetricsSubscriber` (unchanged)

## Summary

FEAT-397 established a one-file-per-client unit-test convention —
`tests/unit/clients/test_{claude,openai,groq,grok,gemini}_multiround_usage.py`
— plus shared tests for the primitive (`test_emit_round_event.py`), the event
(`test_client_round_event.py`), the accumulator (`test_completion_usage_add.py`)
and the metrics side (`test_per_round_metrics.py`). The end-to-end test
`tests/integration/observability/test_multiround_usage.py` drives ONE real
client (AnthropicClient with a mocked SDK) through the real registry into an
in-memory OTel reader; it is not parametrized across clients, so a Bedrock
variant means a new test rather than a new parameter. The sole runtime
consumer of `ClientRoundEvent` is `MetricsSubscriber._on_client_round`
(`observability/subscribers/metrics.py:253`, subscribed at 184) — provider-
agnostic, so no consumer-side change is needed. Bedrock already has
`tests/models/test_bedrock_usage.py` and `tests/clients/test_bedrock_advanced.py`
touching usage.

## Citations

- path: `packages/ai-parrot/tests/unit/clients/test_claude_multiround_usage.py`
  symbol: per-client multiround test convention
- path: `packages/ai-parrot/tests/unit/clients/test_openai_multiround_usage.py`
- path: `packages/ai-parrot/tests/unit/clients/test_groq_multiround_usage.py`
- path: `packages/ai-parrot/tests/unit/clients/test_grok_multiround_usage.py`
- path: `packages/ai-parrot/tests/unit/clients/test_gemini_multiround_usage.py`
- path: `packages/ai-parrot/tests/unit/clients/test_emit_round_event.py`
- path: `packages/ai-parrot/tests/unit/events/lifecycle/test_client_round_event.py`
- path: `packages/ai-parrot/tests/unit/models/test_completion_usage_add.py`
- path: `packages/ai-parrot/tests/unit/observability/test_per_round_metrics.py`
- path: `packages/ai-parrot/tests/models/test_bedrock_usage.py`
- path: `packages/ai-parrot/tests/clients/test_bedrock_advanced.py`

- path: `packages/ai-parrot/tests/integration/observability/test_multiround_usage.py`
  lines: 1-8, 87-98
  symbol: `test_multiround_end_to_end` (single-client, not parametrized)
  excerpt: |
    """End-to-end multi-round token usage observability tests (FEAT-397).
    Drives a real client (AnthropicClient, mocked SDK) through the REAL event
    registry and an in-memory OTel metric reader ..."""
    ...
    def _make_claude_client(sdk_responses):
        client = AnthropicClient(api_key="fake_key")
        client._execute_tool = AsyncMock(return_value="tool result")

- path: `packages/ai-parrot/tests/integration/observability/test_multiround_usage.py`
  lines: 158-178
  symbol: metric names asserted
  excerpt: |
    round_token_pts = _collect_metric_points(reader, "parrot.client.round.token.usage")
    rounds_pts = _collect_metric_points(reader, "parrot.client.rounds")
    total_token_pts = _collect_metric_points(reader, "gen_ai.client.token.usage")

- path: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
  lines: 184, 253
  symbol: `MetricsSubscriber._on_client_round`
  excerpt: |
    registry.subscribe(ClientRoundEvent, self._on_client_round)
    ...
    async def _on_client_round(self, event: ClientRoundEvent) -> None:

## Notes

The integration test mocks `client._backend.build_client`; Bedrock's SDK seam
is `_sdk_create` (`bedrock.py:301-302`, `await self.client.converse(**payload)`),
so a Bedrock integration test mocks a different seam.
