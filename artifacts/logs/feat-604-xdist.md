# FEAT-604 M3 — xdist safety per distribution

Date: 2026-09-25 · host cores: 12 · pytest 9.1.1 · xdist 3.8.0
flags: pytest -q --tb=short -p no:cacheprovider -o log_cli=false -m "not e2e and not real_llm and not integration" --confcutdir=/home/jesuslara/proyectos/ai-parrot/.claude/worktrees/feat-FEAT-604-merge-tier-validation-cost--pool/TASK-3801-a1-a1f4c9e23b7d4e6a9c1f604604604604
Budget: ~2h (resolved spec §8 OQ2); smallest-first; resumable per distribution.

## Pre-excluded (decided, not measured — resolved OQ2)

| distribution | reason |
|---|---|
| ai-parrot | ≈2.3h per serial pass (artifacts/logs/feat-563-s3-xdist.md); stays serial — M1/M2 dedupe buys down its cost |
| ai-parrot-integrations | deterministic hang in test_handle_web_app_data_routes_to_strategy (ledger 1dbb2aac09ba) |
| ai-parrot-server | ~18 intermittent contention failures when run together (ledger e21ec87c6aba) |

## Measured

| distribution | tests | serial (s) | -n auto run1 (s) | run2 (s) | workers | disagreements | verdict |
|---|---|---|---|---|---|---|---|
| ai-parrot-advisors | 6 | 5.22 | 9.45 | 9.53 | 12 | None | safe |
| ai-parrot-client-amazon | 69 | 7.41 | 9.58 | 9.42 | 12 | None | safe |
| ai-parrot-client-anthropic | 13 | 3.81 | 7.78 | 7.51 | 12 | None | safe |
| ai-parrot-client-gemma4 | 1 | 3.71 | 7.21 | 6.78 | 12 | None | safe |
| ai-parrot-client-grok | 13 | 3.90 | 7.67 | 7.33 | 12 | None | safe |
| ai-parrot-client-groq | 5 | 3.53 | 7.02 | 7.48 | 12 | None | safe |
| ai-parrot-client-hf | 1 | 8.69 | 12.56 | 11.99 | 12 | None | safe |
| ai-parrot-client-jev | 1 | 3.80 | 7.37 | 7.34 | 12 | None | safe |
| ai-parrot-client-local | 1 | 4.04 | 7.41 | 6.89 | 12 | None | safe |
| ai-parrot-client-meta | 1 | 3.91 | 7.23 | 7.76 | 12 | None | safe |
| ai-parrot-client-moonshot | 1 | 4.29 | 7.14 | 7.18 | 12 | None | safe |
| ai-parrot-client-nvidia | 1 | 3.86 | 7.38 | 7.04 | 12 | None | safe |
| ai-parrot-client-openai | 54 | 5.04 | 9.20 | 8.48 | 12 | None | safe |
| ai-parrot-client-openrouter | 1 | 4.04 | 6.75 | 6.37 | 12 | None | safe |
| ai-parrot-client-vllm | 1 | 3.57 | 6.23 | 6.49 | 12 | None | safe |
| ai-parrot-client-zai | 1 | 3.55 | 6.36 | 6.36 | 12 | None | safe |
| ai-parrot-openlit-bridge | 8 | 3.49 | 4.92 | 5.17 | 12 | None | safe |
| ai-parrot-loaders | 421 | 19.57 | >30.00 | 19.36 | 12 | run1 did not terminate before the enforced timeout | excluded (wall time 30.00s) |
| navrules | 146 | 0.68 | >30.00 | — | 12 | xdist run did not terminate before the enforced timeout | excluded (wall time 30.00s) |

The remaining distributions were not completed during this resumable measurement run and stay excluded pending their own serial-plus-two-xdist comparisons: `root`, `ai-parrot-client-google`, `ai-parrot-embeddings`, `ai-parrot-pipelines`, `ai-parrot-tools`, `ai-parrot-visualizations`, and `parrot-formdesigner`.

## Disagreements (first 30 per unsafe distribution)

None recorded.

## Decision

```python
XDIST_SAFE_DISTRIBUTIONS = frozenset(
    {
        "ai-parrot-advisors",
        "ai-parrot-client-amazon",
        "ai-parrot-client-anthropic",
        "ai-parrot-client-gemma4",
        "ai-parrot-client-grok",
        "ai-parrot-client-groq",
        "ai-parrot-client-hf",
        "ai-parrot-client-jev",
        "ai-parrot-client-local",
        "ai-parrot-client-meta",
        "ai-parrot-client-moonshot",
        "ai-parrot-client-nvidia",
        "ai-parrot-client-openai",
        "ai-parrot-client-openrouter",
        "ai-parrot-client-vllm",
        "ai-parrot-client-zai",
        "ai-parrot-openlit-bridge",
    }
)
```
