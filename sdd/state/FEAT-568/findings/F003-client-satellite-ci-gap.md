# F003 — FEAT-523 split 15 LLM clients into satellite packages; `ci.yml` was never updated to sync them

**Query**: Q005/Q008 extended (git log, directory search), largest single contributor to test-core failures
**Confidence**: high

## Evidence

- `packages/ai-parrot/src/parrot/clients/` now contains only `base.py`,
  `budget.py`, `budget_scope.py`, `detection.py`, `factory.py`, `models.py`,
  `openai_base.py`, `protocols.py`, plus empty `google/` and `nova/`
  directories (just stale `__pycache__`, no `.py` files).
- `packages/` has 15 new satellite distributions:
  `ai-parrot-client-{amazon,anthropic,gemma4,google,grok,groq,hf,local,meta,
  moonshot,nvidia,openai,openrouter,vllm,zai}`, each contributing
  `parrot.clients.<provider>` via PEP 420 namespace merging (same pattern as
  `ai-parrot-embeddings`, FEAT-201).
- `sdd/tasks/index/pep-420-llm-clients.json` (FEAT-523): all 15 tasks
  `"status": "done"`, `completed_at: 2026-09-04` — a real, complete,
  intentional refactor, not a regression.
- `git log -- packages/ai-parrot/src/parrot/clients/google/` confirms the
  core copy was explicitly emptied: `cceff6174 fix(pep-420-llm-clients):
  stage missed google/gemma4/hf deletion from core (TASK-2851 follow-up)`.
- `.github/workflows/ci.yml` has **no job or sync step that installs any
  `ai-parrot-client-*` package**. `test-core` runs `uv sync --package
  ai-parrot` (bare core) then `pytest tests/ -q --ignore=tests/tools
  --continue-on-collection-errors` — which still walks root `tests/clients/`
  (containing tests for every one of these providers, e.g.
  `test_google_fallback.py`, `test_bridged_hitl.py` [anthropic],
  `test_meta_client.py`, `test_moonshot_client.py`,
  `test_openai_base_parity.py`, `test_openai_fallback.py`).
- CI log tally (`test-core`, Python 3.12, this run): `ModuleNotFoundError`
  counts — `parrot.clients.anthropic` (143 occurrences across its test
  file's cases), `.google` (115), `.openai` (96), `.groq` (52), `.grok` (42),
  `.local` (38), `.amazon` (12), `.meta` (5), `.gemma4` (4), `.nvidia` (2),
  `.hf` (2), `.moonshot` (1) — **~512 of the job's 319 reported "errors"**
  (pytest counts per test case, not per file) trace to this one root cause.
- Same shape, smaller: `ai-parrot-server[scheduler]`'s `apscheduler` extra
  (declared in both `ai-parrot/pyproject.toml` — `scheduler =
  ["apscheduler==3.11.2"]` — and `ai-parrot-server/pyproject.toml`, which
  already defines a `requires_apscheduler` pytest marker convention) is not
  installed either; `parrot.scheduler.__getattr__` → `_imports.load_satellite_attr`
  even raises a **self-diagnosing** error: *"The module was found, so this
  is NOT a missing install — check for a version mismatch... or a missing
  optional dependency."* — confirming this is a known, anticipated
  satellite-boundary case, just not wired into this CI job. Also present at
  lower volume in the same sweep: `mcp` (the third-party MCP SDK, 5
  occurrences, `tests/mcp/test_oauth2_*`), `parrot.integrations.oauth2` (2,
  needs `ai-parrot-integrations`), `googleapiclient` (2), `folium` (2, needs
  `ai-parrot-visualizations[map]`).

## Precedent already established in this same `ci.yml`

`test-wiki-extras` + `test-wiki-luau-fallback` (FEAT-498/FEAT-532) already
implement exactly the pattern this gap needs: one job proves the **absence**
of an extra degrades gracefully (skip, not crash), a second job installs the
extra and runs the same tests for real, **with an explicit "confirm nothing
was silently skipped" gate** (`grep -q SKIPPED ... && exit 1`) so a broken
wheel can't hide behind a skip.

## Conclusion

Two complementary actions are needed, following the established
wiki-extras/luau-fallback precedent — not one or the other:
1. Every test module that imports an optional satellite's namespace
   (`parrot.clients.<provider>`, `parrot.scheduler` when it needs
   apscheduler, `parrot.integrations.oauth2`, the third-party `mcp` SDK,
   `googleapiclient`) should guard collection with
   `pytest.importorskip(...)` (or an equivalent marker) so `test-core`'s
   bare-core sweep degrades cleanly instead of hard-failing — this changes
   nothing about what the tests assert.
2. Add a CI job (or jobs) that actually syncs the client satellites (and
   `ai-parrot-server[scheduler]`, `ai-parrot-integrations`, `mcp`) and runs
   `tests/clients/` (+ the scheduler/oauth2 suites) for real, with a
   Luau-style "nothing skipped" gate — otherwise these 15+ packages have
   **zero CI coverage** post-FEAT-523, silently.
