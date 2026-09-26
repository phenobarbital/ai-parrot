# FEAT-604 M3 — xdist safety per distribution

Date: 2026-09-25 · host cores: 12 · pytest 9.1.1 · xdist 3.8.0
flags: pytest -q --tb=short -p no:cacheprovider -o log_cli=false -m "not e2e and not real_llm and not integration" --confcutdir=/home/jesuslara/proyectos/ai-parrot
Budget: ~2h (resolved spec §8 OQ2); smallest-first; resumable per distribution.

## Addendum (2026-09-26, issue:dd35b0648576)

The initial TASK-3801 pass (rows below unchanged from that run) used a flat 30s
per-run timeout instead of the task's own "~3x expected serial time" formula,
which wrongly excluded `ai-parrot-loaders` (serial 19.57s, correct cap ~59s)
and left `navrules` ambiguous, and stopped after only ~15min of the ~2h budget
with 7 in-scope distributions unmeasured. This addendum completes the
measurement: `ai-parrot-loaders` and `navrules` were re-measured with the
correct 3x-serial-time cap (both now genuinely safe), and all 7 remaining
in-scope distributions were measured. Two of them — `parrot-formdesigner` and
`ai-parrot-tools` — are excluded on REAL evidence of per-test outcome
disagreement between serial and `-n auto` runs (see Disagreements below); this
is exactly the "flaky suite converted into a silently flaky gate" risk the
spec's own Key Constraints warn about, so they are correctly NOT added despite
now having a completed 3-run comparison.

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
| ai-parrot-loaders (re-measured, 3x-serial cap) | 421 | 28.56 | 27.77 | 27.53 | 12 | None (rc=1 identically in all 3 runs — pre-existing red, counts as agreement) | safe |
| navrules (re-measured, 3x-serial cap) | 144 | 3.21 | 7.85 | 7.98 | 12 | None | safe |
| ai-parrot-embeddings | 214 | 44.37 | 32.10 | 32.67 | 12 | None (rc=1 identically — pre-existing red) | safe |
| ai-parrot-client-google | 259 | 92.04 | 38.97 | 39.01 | 12 | None | safe |
| ai-parrot-visualizations | 396 | 8.71 | 12.45 | 13.15 | 12 | None | safe |
| ai-parrot-pipelines | 387 | 10.35 | 12.39 | 12.39 | 12 | None (rc=1 identically — pre-existing red) | safe |
| parrot-formdesigner | 2869 | 35.79 | 31.55 | 31.02 | 12 | **8** (real per-test outcome flips, not pre-existing red) | **unsafe — excluded** |
| ai-parrot-tools | 4985 | 393.78 | 118.04 | 118.34 | 12 | **7** (real per-test outcome flips, not pre-existing red) | **unsafe — excluded** |
| root | 7090 | 310.02 | 108.54 | 100.70 | 12 | **7** (real per-test outcome flips) | **unsafe — excluded** |

## Disagreements (first 30 per unsafe distribution)

**parrot-formdesigner** (8 total, all in `tests.unit.controls.test_control_registry_capabilities`):
`TestBuiltinControlCapabilities::test_all_builtin_controls_present`,
`TestBuiltinControlCapabilities::test_container_controls_have_limited_effects`,
`TestBuiltinControlCapabilities::test_nps_likert_ranking_are_numeric`,
`TestBuiltinControlCapabilities::test_numeric_control_has_arithmetic_operations`,
`TestBuiltinControlCapabilities::test_numeric_control_has_comparison_operators`,
and 3 more in the same module/class — consistent with shared mutable registry
state that is order-dependent under `-n auto`'s worker distribution, not
present under serial execution. Not investigated further (out of scope for
this ledger fix — filing as a separate finding, see below).

**ai-parrot-tools** (7 total, all in `research/test_academic_*`):
`test_academic_crossref.TestCrossref::test_uses_bibliographic_query`,
`test_academic_crossref.TestCrossref::test_uses_polite_pool`,
`test_academic_details.TestGetPaperDetails::test_explicit_source_overrides`,
`test_academic_details.TestGetPaperDetails::test_s2_paper_lookup_url`,
`test_academic_pubmed.TestPubMed::test_two_step_workflow`, and 2 more —
consistent with shared rate-limiter/session state across the academic-API
research tools bleeding across xdist workers. Not investigated further (out
of scope for this ledger fix).

**root** (7 total, all in `tests.unit.integrations.oauth2.*`):
`test_handler`, `test_hydration`, `test_jira_provider`, `test_models`,
`test_persistence`, and 2 more — the serial run's own log shows
`parrot.integrations.oauth2: 8 module(s) skipped` alongside `RuntimeError:
Event loop is closed` in both serial and xdist logs, consistent with a shared
asyncio event loop being torn down by one worker while another still holds a
reference — a real, order/worker-dependent xdist-unsafety in this module's
fixtures. Not investigated further (out of scope for this ledger fix).

## Decision

```python
XDIST_SAFE_DISTRIBUTIONS = frozenset(
    {
        "ai-parrot-advisors",
        "ai-parrot-client-amazon",
        "ai-parrot-client-anthropic",
        "ai-parrot-client-gemma4",
        "ai-parrot-client-google",
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
        "ai-parrot-embeddings",
        "ai-parrot-loaders",
        "ai-parrot-openlit-bridge",
        "ai-parrot-pipelines",
        "ai-parrot-visualizations",
        "navrules",
    }
)
```

`parrot-formdesigner`, `ai-parrot-tools` and `root` are measured but
deliberately EXCLUDED — they showed real per-test outcome disagreements
between serial and `-n auto`, i.e. genuine order/worker-dependent test bugs,
not measurement noise. Every in-scope distribution from spec §3 M3's scope
statement has now been measured (or was pre-excluded on cited evidence); none
remain unmeasured.
