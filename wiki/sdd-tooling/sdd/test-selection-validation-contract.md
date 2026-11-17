---
title: "Test selection in the SDD flow — the Validation Contract (FEAT 699)"
---

# Test selection in the SDD flow — the Validation Contract (FEAT-699)

## Authoring

The Validation Contract is authored directly in each feature specification document (`sdd/specs/<slug>.spec.md`) under Section 4 (`### Validation Contract`).

### Format
Contract operands are `.py` files or `file.py::node` ids; a directory or suite is rejected when the contract is
parsed or loaded, and `check_task_graph` reports it as `test-contract-malformed`.

The section defines explicit test paths and optional markers:

```markdown
### Validation Contract
tests:
  - tests/sdd_scripts/test_brief_meta.py
  - tests/sdd_scripts/test_brief_scaffold_integration.py
markers: none
```

- **Fallback**: If a spec does not require focused scoping, it uses `none — fallback` in place of test lists.
- **`real_llm` Rule**: `real_llm` test paths or markers must not be included in standard merge/feature validation contracts unless explicitly required.
- **Caching Command**: The contract is cached into the per-spec index header using:
  ```bash
  python -m scripts.sdd.cache_test_contract --spec sdd/specs/<slug>.spec.md --index sdd/tasks/index/<slug>.json
  ```
  The `/sdd-task` workflow automatically invokes caching during task breakdown.

## How plans are built

`scripts.sdd.select_tests` builds test execution plans across tiers based on whether a `test_contract` is cached:

| Tier | Contract Mode | Fallback Mode |
|---|---|---|
| **task** | Scoped to task's declared `Validation Commands` | Scoped to task's declared `Validation Commands` |
| **merge** | Contract tests + affected target file mirrors | FEAT-563 diff heuristics + target file mirrors |
| **feature** | Full contract test set across all spec tasks | Full repo/distribution test sweep |

- **File-level mirror**: Changes in source files automatically pull in corresponding mirror test files.
- **No suite escalation**: The selector strictly obeys scope without unnecessary full-suite escalations.

## Green cache and baseline verdict

- **Cached targets**: green results are recorded per worktree in `parrot-test-scope-green.json`
  (`green_cache.CACHE_FILENAME`), only for `.py` files and node ids.
- **Namespace**: one store namespace per feature id + base ref + contract digest (`green_cache.namespace_for`;
  a feature without a contract digests as `""`). `select_tests` and the MCP supervisor compute the same value,
  so neither clears the other's entries; any change to the three inputs invalidates the whole store.
- **Depth-1 key**: a cache key digests the test file, its `conftest.py` chain, the root and distribution
  `pyproject.toml`, and the source modules the test imports **directly**. A change two imports away does not
  invalidate the entry — the feature tier runs fresh and the nightly sweep is the backstop.
- **Invalidation inputs**: Cache entries are invalidated when source files, test files, or dependent module digests change.
- **Baseline verdict**:
  - **New red**: Test failed in the current branch diff.
  - **Baseline red**: Test was already failing on the base branch (`origin/dev`).
  - **Unknown**: New test or unverified baseline state.
- **Feature tier fresh**: Feature tier executions bypass cache lookup (`--fresh`) to ensure full feature verification before closeout.

## Safety net

Nightly integration runs (`.github/workflows/nightly-tests.yml`) execute full test sweeps across all distributions to catch any edge cases or regressions missed by contract-scoped validation runs.

## Measured (FEAT-698 replay, commits d7e03cb93 vs 49806c49f)

| Tier | Mode | Tests collected | Wall time (s) |
|---|---|---:|---:|
| merge | before (FEAT-563 heuristics) | 2990 | 87 |
| feature | before (FEAT-563 heuristics) | 2562 | — |
| merge | contract | 197 | 38.62 |
| merge | contract (cached 2nd run) | 197 | 39.37 |
| feature | contract | 197 | 38.81 |
| merge | fallback | 2219 | 228.67 |
| feature | fallback | 2219 | — |
