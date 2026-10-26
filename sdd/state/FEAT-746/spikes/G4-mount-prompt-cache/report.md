# G4 — Mid-conversation mount/unmount and prompt cache

## Measurement status

No real-provider measurement was performed in this task worktree. The spike is
explicitly gated by `PARROT_TEST_REAL_LLM=1` because it consumes provider quota,
and no operator-authorized configured provider session was supplied. The offline
path was run and printed the expected request shape: six baseline tools, three
mounted tools, and a 16,800-character deterministic system prefix.

The implementation discovers these exact runtime classes and runs each only when
its existing `has_server_credentials()` check succeeds:

| Provider | Class | Cache-read source normalized by spike | Status |
| --- | --- | --- | --- |
| Anthropic | `parrot.clients.anthropic.AnthropicClient` | `cache_read_input_tokens` | Pending live measurement |
| OpenAI | `parrot.clients.openai.OpenAIClient` | `prompt_tokens_details.cached_tokens` | Pending live measurement |
| Google | `parrot.clients.google.GoogleGenAIClient` | `cached_content_token_count` | Pending live measurement |

Each measured row records `input`, `cache_write`, and `cache_read` for turn 1
(six tools), turn 2 (same tools and prompt), and turn 3 (nine tools after the
mount). The spike reads the unified `AIMessage.usage` and, where the current
adapter has not retained nested counters, its serialized raw provider usage.
Missing counters remain zero rather than being inferred.

## Reproduction

```bash
PARROT_TEST_REAL_LLM=1 python sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/spike.py
PARROT_SPIKE=1 PARROT_TEST_REAL_LLM=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g4_mount_prompt_cache.py -q
```

Run with at least two configured providers. A successful gate record requires
turn 2 cache reads and records turn 3 cache behavior for every measured provider.

## Amendment

**PENDING — no provider-cache conclusion is justified without the required
two-provider measurement.** M7 must retain its current safe planner path:
pre-mount categories before an LLM turn whenever the intent is known. Do not
claim free mid-conversation mounting preserves a cached prefix, and do not add a
mounted-tools cache segment to `AbstractClient._apply_cache_hints`, until this
spike shows turn-3 cache reads for at least two providers. If either measured
provider loses its cached prefix after the mount, amend M7 to premount-only and
keep mounted definitions out of a shared cacheable prefix.
