# G4 — Mid-conversation mount/unmount and prompt cache

## Measurement status

Measured 2026-10-30 against three real providers (issue:60de633baac2 rerun,
operator-authorised `PARROT_TEST_REAL_LLM=1`). Code under test: the `dev`
client distributions (`ai-parrot-client-anthropic`, `-openai`, `-google`) from
the main checkout. Raw output: `results.json`.

Each provider gets one opened client, six registered tools, and three turns
with the same ~16.8k-character system prefix: turn 1 (6 tools), turn 2 (same
6 tools, same prompt), turn 3 (9 tools, after mounting a 3-tool category). No
turn made a tool call. A per-run nonce heads the prefix so every run starts
cold.

## Results (cold runs)

`read` = cache-read tokens, `write` = cache-write tokens, `in` = provider input
count (Anthropic reports uncached input only; OpenAI/Google report total).

| Provider (model) | Run | Turn 1 | Turn 2 (repeat) | Turn 3 (after mount) |
|---|---|---|---|---|
| Anthropic (client default) | 6 | write 3783 | **read 3783** | read 0, **write 3996** |
| Anthropic (client default) | 7 | write 3783 | **read 3783** | read 0, **write 3996** |
| OpenAI (gpt-4.1-mini) | 6 | in 3393 | **read 3328** | read 2816 / in 3486 |
| OpenAI (gpt-4.1-mini) | 7 | in 3392 | **read 3328** | **read 0** / in 3485 |
| Google (client default) | 6 | in 4084 | **read 3726** | read 3756 / in 4483 |
| Google (client default) | 7 | in 4086 | **read 3726** | read 3756 / in 4485 |

The first fully cold Anthropic run without the nonce (`pre_nonce_first_run`)
shows the same pattern: read 3760 on turn 2, read 0 / write 3973 on turn 3.

- **Anthropic** loses the whole cached prefix on every mount. Tool definitions
  sit ahead of the system prompt in its cache order, so any tool change
  invalidates the `cache_control` breakpoint on the system block.
- **OpenAI** caches the repeat turn but loses some or all of the prefix after
  the mount (2816 of 3328 tokens kept in one run, none in the other).
- **Google** (implicit caching) kept the prefix across the mount in both cold
  runs (turn 3 read ≥ turn 2 read).

## Spike fixes needed to measure

The first version reported PENDING, and three defects would have voided any
measurement:

1. Clients were never opened (`self.client` was `None`); the spike now uses
   `async with client:`.
2. Tools went through `ask(tools=<schema dicts>)`. The Google client only
   accepts tool *objects* there and silently drops dicts, so Google's turns ran
   with no tools at all. Tools are now registered on the client's own
   `ToolManager` (`client.register_tools`), which every provider reads.
3. The system prompt was a plain string, which never triggers Anthropic's
   FEAT-181 `cache_control` path; Anthropic now gets
   `[CacheableSegment(text=..., cacheable=True)]`.

Also found: `OpenAIClient` with its default model (`gpt-5-mini`) fails every
`ask()` with `400 unsupported_parameter: max_tokens` (use
`max_completion_tokens`). The spike pins `G4_OPENAI_MODEL` (default
`gpt-4.1-mini`); the client defect is filed separately in the ledger.

## Reproduction

```bash
PARROT_TEST_REAL_LLM=1 python sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/spike.py
PARROT_SPIKE=1 PARROT_TEST_REAL_LLM=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g4_mount_prompt_cache.py -q
```

`G4_RUN_NONCE` fixes the nonce (only useful to deliberately rerun warm);
`G4_OPENAI_MODEL` overrides the OpenAI model.

## Amendment

**FAIL for free mid-conversation mounting → M7 is premount-only.** Two of the
three measured providers (Anthropic always, OpenAI in part or in full) lose the
cached prefix when a category is mounted between turns, which is the
report's stated trigger. M7 therefore:

- pre-mounts categories from intent before the first LLM turn (the planner
  path) and treats a mid-conversation `catalog_mount` as a cache-resetting
  operation, not a free one: allowed, but documented and observable as a
  cache miss;
- keeps mounted definitions out of any shared cacheable prefix, and does not
  add a mounted-tools segment to `AbstractClient._apply_cache_hints`
  (Anthropic orders tools before the system prompt, so no system-side segment
  can protect them).
