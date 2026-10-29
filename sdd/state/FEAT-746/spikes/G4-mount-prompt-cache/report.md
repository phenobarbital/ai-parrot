# G4 — Mid-conversation mount/unmount and prompt cache

## Measurement status

Measured live 2026-10-30 (`PARROT_TEST_REAL_LLM=1`): six baseline tools, turn 2
repeats turn 1, turn 3 mounts three more tools; 16,800-character system prefix sent as
`[CacheableSegment(PAD, cacheable=True)]` — the production path `AbstractBot` uses.

| Provider | Model | Turn 1 read/write | Turn 2 read | Turn 3 (after mount) read/write |
| --- | --- | --- | --- | --- |
| Anthropic | client default | 0 / 3,760 | 3,760 | **0 / 3,973** — prefix invalidated |
| OpenAI | `gpt-4.1-mini` | 3,200 / – | 3,200 | 3,328 — preserved |
| Google (string prompt, implicit cache) | client default | 0 | 3,060 | 3,060 — preserved |
| Google (segment prompt) | client default | error | – | – |

Notes:

- Anthropic only emits `cache_control` blocks for a segment list (FEAT-181); with a plain
  string it caches nothing (an earlier run showed 0/0/0 for that reason).
- Anthropic orders tools before the system prompt in its cache prefix, so changing the
  tool set rewrites the cached prefix — turn 3 is a full cache write.
- Google with cacheable segments fails with 400 `CachedContent can not be used with
  GenerateContent request setting system_instruction, tools or tool_config` — a Google
  client defect (explicit cache + tools), filed in the ledger. Its implicit cache on the
  string path survives the mount.
- OpenAI's `gpt-5-mini` default is unusable (client `max_tokens` defect, see G3).

## Reproduction

```bash
PARROT_TEST_REAL_LLM=1 python sdd/state/FEAT-746/spikes/G4-mount-prompt-cache/spike.py
PARROT_SPIKE=1 PARROT_TEST_REAL_LLM=1 pytest packages/ai-parrot-squawk/tests/spikes/test_g4_mount_prompt_cache.py -q
```

Run with at least two configured providers. A successful gate record requires
turn 2 cache reads and records turn 3 cache behavior for every measured provider.

## Amendment

**Resolved — M7 is premount-only.** The gate rule applies: a measured provider
(Anthropic) loses its cached prefix after a mid-conversation mount. Therefore:

- M7 pre-mounts categories before an LLM turn whenever the intent is known; no free
  mid-conversation mounting is claimed to preserve the cache.
- Mounted definitions stay out of any shared cacheable prefix; do not add a
  mounted-tools cache segment to `AbstractClient._apply_cache_hints`.
- OpenAI and Google implicit caching do survive a mount, but a provider-dependent
  guarantee is not a contract M7 can rely on.
