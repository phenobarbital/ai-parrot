---
id: F019
query_id: Q032
type: git_log
intent: "Recent history of the default-model plumbing (conf.py + llm_defaults.py) — FEAT-796 landed days ago."
executed_at: 2026-11-04T01:37:14Z
duration_ms: 400
parent_id: null
depth: 0
---

# F019 — llm_defaults.py was born on 2026-11-04 (FEAT-796); conf.py is edited by many lanes

## Summary

`packages/ai-parrot/src/parrot/llm_defaults.py` was created by `8d5cb6ac3a` (TASK-5138,
2026-11-04, +79 lines, with `tests/unit/test_llm_defaults.py` +87) and `conf.py` got the
matching DEFAULT_LLM wiring in `28255feed6` (TASK-5137, 2026-11-03, +4/-1, with
`tests/unit/test_conf_default_llm.py` +20). Both merged via PR #1949 (FEAT-796). Fifteen
commits touched `conf.py` in 60 days (reviewer, workday, bedrock, connections, locale) —
it is a shared settings file, so a default-model change there is small but must be surgical.

## Citations

- path: `packages/ai-parrot/src/parrot/llm_defaults.py`
  lines: n/a
  symbol: n/a
  excerpt: |
    8d5cb6ac3a 2026-11-04 Jesus feat(per-component-llm-defaults): TASK-5138 (llm_defaults.py +79; tests/unit/test_llm_defaults.py +87)
    87d036bb94 2026-11-04 Jesus style(per-component-llm-defaults): TASK-5138 — engine lint autofix

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: n/a
  symbol: n/a
  excerpt: |
    28255feed6 2026-11-03 Jesus feat(per-component-llm-defaults): TASK-5137 (conf.py +4/-1; tests/unit/test_conf_default_llm.py +20)
    1051201922 2026-10-31 feat(connections-web-slack): TASK-5034
    0d186326a7 2026-10-30 feat(delegated-auth-connections): TASK-4941
    2ab54ab5cc 2026-10-22 feat(reviewer): own Google key, open-only today_pr, strict /review_pr gate
    9da2063530 2026-10-17 changes in aws bedrock client

- path: `packages/ai-parrot/tests/unit/test_conf_default_llm.py`
  lines: n/a
  symbol: n/a
  excerpt: |
    added by 28255feed6 — asserts the DEFAULT_LLM resolution in conf.py

## Notes

- The FEAT-796 tests (`test_llm_defaults.py`, `test_conf_default_llm.py`) are where a changed Google default must be re-asserted.
- [cross-lane: type=read, intent=read llm_defaults.py and the conf.py DEFAULT_LLM block to find the literal Google id used as fallback]
