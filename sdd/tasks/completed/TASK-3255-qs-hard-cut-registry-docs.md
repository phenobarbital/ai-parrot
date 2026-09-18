# TASK-3255: Hard cut of `QSourceTool`, registry regeneration, dependency floor, docs and integration tests

**Feature**: FEAT-558 — QuerysourceToolkit — tenant-scoped query-slug and MultiQuery tools
**Spec**: `sdd/specs/querysource-toolkit-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3254
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (goal G9) plus the docs and integration tests of Module 8. `QSourceTool` has no code consumers;
only the auto-generated `TOOL_REGISTRY` references it under `q_source` and `qsource` (`parrot_tools/__init__.py:137,232`).
The generator **preserves entries its scan cannot find** (`scripts/generate_tool_registry.py:296-298`, design research
S12), so the two keys must be deleted by hand before regenerating; `tests/test_imports_integrity.py` then guards the
result. The `db` extra floor moves to the version the dialect was verified on (S11). **This task must run last.**

---

## Scope

- `git rm packages/ai-parrot-tools/src/parrot_tools/qsource.py`.
- Remove the `q_source` / `qsource` lines from `TOOL_REGISTRY`; run `python scripts/generate_tool_registry.py --tools-only` then `--check`; confirm the `querysource` key points at `parrot_tools.querysource.toolkit.QuerysourceToolkit`.
- Raise `db` extra floor to `querysource>=4.5.11` in `packages/ai-parrot-tools/pyproject.toml`.
- Write `docs/tools/querysource-toolkit.md`.
- Add integration tests (skipped without querysource) + the registry test.

**NOT in scope**: any toolkit behaviour change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/qsource.py` | DELETE | old single tool |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | remove 2 stale keys, then regenerate |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | `db` extra floor |
| `docs/tools/querysource-toolkit.md` | CREATE | user docs |
| `packages/ai-parrot-tools/tests/querysource/test_registry_and_integration.py` | CREATE | registry + real-querysource tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools import TOOL_REGISTRY                 # verified: packages/ai-parrot-tools/src/parrot_tools/__init__.py:13,241
from parrot_tools.querysource import QuerysourceToolkit   # TASK-3251
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py  (auto-generated; header lines 4-7)
    "q_source": "parrot_tools.qsource.QSourceTool",      # line 137  ← delete
    "query": "parrot_tools.querytoolkit.QueryToolkit",   # line 139  (keep — unrelated)
    "qsource": "parrot_tools.qsource.QSourceTool",       # line 232  ← delete
# scripts/generate_tool_registry.py
#   usage: python scripts/generate_tool_registry.py [--dry-run] [--check] [--verbose] [--tools-only] [--loaders-only]   (:6-15, :352-380)
#   _class_to_key("QuerysourceToolkit") → "querysource"  (:110-130: CamelCase→snake, strips Tool/Toolkit suffix)
#   :296-298  "Merge: new entries override, but preserve manual entries not found by scan"  ← why manual deletion is required
# packages/ai-parrot-tools/pyproject.toml:77   db = ["querysource>=4.1.11", "psycopg-binary>=3.2"]
# packages/ai-parrot-tools/tests/test_imports_integrity.py:24  test_import_all_registered_tools — imports every TOOL_REGISTRY entry
# docs/tools/ exists (compression.md, readonly-repo-toolkit.md)
```

### Does NOT Exist
- ~~any importer of `parrot_tools.qsource` outside `build/` artefacts~~ — verified by repo-wide grep (finding F013); after deletion the module must not import.
- ~~`generate_tool_registry.py --remove <key>`~~ — no such flag; delete lines by hand.
- ~~`parrot_tools.qsource` shim / deprecation alias~~ — hard cut, no shim (project rule: no external consumers).

---

## Implementation Notes

### Key Constraints
- Run the generator from the repo root with the venv active; it rewrites `TOOL_REGISTRY` in place. Inspect the diff: the only expected changes are the two deletions (already done by hand) and `"querysource": "parrot_tools.querysource.toolkit.QuerysourceToolkit"` added. If the generator also picks up other classes from the new package (e.g. models), that means a class name ends with `Tool`/`Toolkit` unexpectedly — do not rename spec-fixed classes; instead report it in the Completion Note.
- Docs must cover: configuration (`programs`, `allow_write`, `allow_raw_sql`, `allow_external_sources`, `include_sql`, `max_rows`, `forced_conditions`, `dsn`, `multiquery_timeout`), tenancy semantics table (restricted vs unrestricted × raw / external / destinations / save), the eight tools, a dialect quick-reference (copy from `DIALECT_REFERENCE`), and a migration note from `QSourceTool` (`query_slug`+`conditions` → `execute_slug(slug, placeholders, filter, …)`; raw `query` removed).

---

## Implementation Blueprint

### Steps (in order)
1. `git rm packages/ai-parrot-tools/src/parrot_tools/qsource.py` — *why*: no consumers; the registry is the only reference.
2. Delete the two registry lines (block below) — *why*: the generator keeps unmatched entries (S12).
3. `python scripts/generate_tool_registry.py --tools-only` then `python scripts/generate_tool_registry.py --check` (exit 0) — *why*: adds the `querysource` key and proves the file is not stale.
4. Edit `pyproject.toml` (block below) — *why*: dialect verified on 4.5.11 (S11).
5. Write docs and tests; run `pytest packages/ai-parrot-tools/tests/test_imports_integrity.py packages/ai-parrot-tools/tests/querysource -v`.

### `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"q_source": "parrot_tools.qsource.QSourceTool",' packages/ai-parrot-tools/src/parrot_tools/__init__.py)
# DELETE the line:    "q_source": "parrot_tools.qsource.QSourceTool",
# occurrences: 1 (verified: grep -c '"qsource": "parrot_tools.qsource.QSourceTool",' packages/ai-parrot-tools/src/parrot_tools/__init__.py)
# DELETE the line:    "qsource": "parrot_tools.qsource.QSourceTool",
# THEN run the generator; expected new line (alphabetical position decided by the generator):
    "querysource": "parrot_tools.querysource.toolkit.QuerysourceToolkit",
```
**Why**: hand deletion + regeneration is the only sequence that leaves no dead alias (S12).

### `packages/ai-parrot-tools/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '^db = \["querysource>=4.1.11"' packages/ai-parrot-tools/pyproject.toml)
# REPLACE line 77
db = ["querysource>=4.5.11", "psycopg-binary>=3.2"]
```
**Why**: the dialect reference and `.pxd` surface test were verified against 4.5.11 (S11).

### `docs/tools/querysource-toolkit.md` (CREATE — outline; fill prose)
```markdown
# QuerysourceToolkit

Tenant-scoped QuerySource tools for agents (`parrot_tools.querysource.QuerysourceToolkit`, tool prefix `qs`).

## Configuration
| Argument | Default | Meaning |
|---|---|---|
| `programs` | `None` | allowlist of `program_slug` values; `None` = unrestricted |
| `allow_write` | `False` | enables `qs_save_multiquery` and destination (`Output`) steps |
| `allow_raw_sql` | `False` | inline `{"query": …}` pipeline nodes (ignored — always forbidden — when restricted) |
| `allow_external_sources` | `True` | `files` / `sources` sections |
| `include_sql` | `True` | `qs_describe_slug` returns the SQL / pipeline JSON |
| `max_rows` | `200` | row cap pushed into QuerySource as `querylimit` |
| `forced_conditions` | `{}` | conditions merged last on every execution |
| `dsn` | querysource `asyncpg_url` | catalog connection |
| `multiquery_timeout` | `600` | seconds for `qs_run_multiquery` |

## Tools
<!-- FILL IN: one paragraph per tool (8), copied from the method docstrings -->

## Tenancy semantics
<!-- FILL IN: table restricted/unrestricted × slug / raw node / files+sources / destinations / save -->

## Conditions dialect quick reference
<!-- FILL IN: render DIALECT_REFERENCE (option keys, placeholder rules, WHERE grammar, examples) -->

## Migrating from QSourceTool
<!-- FILL IN: mapping table query_slug→slug, conditions→placeholders/filter/fields/…, limit→limit, raw query → not available -->
```
**Why**: spec §5 AC requires the doc with these four topics.

### `packages/ai-parrot-tools/tests/querysource/test_registry_and_integration.py` (CREATE)
```python
"""Registry integrity after the hard cut + integration tests against the real querysource (skipped when absent)."""
import importlib, importlib.util
import pytest
from parrot_tools import TOOL_REGISTRY

HAS_QS = importlib.util.find_spec("querysource") is not None


def test_registry_has_no_stale_qsource_keys():
    assert TOOL_REGISTRY["querysource"] == "parrot_tools.querysource.toolkit.QuerysourceToolkit"
    assert "q_source" not in TOOL_REGISTRY and "qsource" not in TOOL_REGISTRY
    with pytest.raises(ImportError):
        importlib.import_module("parrot_tools.qsource")


@pytest.mark.skipif(not HAS_QS, reason="querysource not installed")
async def test_component_catalog_real_registry():
    from parrot_tools.querysource import QuerysourceToolkit
    docs = await QuerysourceToolkit(dsn="postgres://unused").list_components(category="Operators")
    names = {d.name for d in docs}
    assert {"Concat", "Join"} <= names and all(d.json_schema is not None for d in docs if d.name == "Concat")


@pytest.mark.skipif(not HAS_QS, reason="querysource not installed")
def test_validate_pipeline_real_registry_structural():
    from querysource.queries.multi.registry import ComponentRegistry
    # FILL IN: assert the proposal's example pipeline (conftest.PIPELINE) validates structurally and an unknown step
    #          name ("Frobnicate") is reported — bounded by registry.py:332-375
```
**Why**: S9/S12 — fakes cannot prove the real catalog shape or the registry hard cut.

### FILL IN checklist
- [ ] `docs/tools/querysource-toolkit.md` — four sections' prose; bounded by spec §5 AC (docs)
- [ ] `test_registry_and_integration.py::test_validate_pipeline_real_registry_structural` — bounded by registry.py:332-375

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-tools/src/parrot_tools/qsource.py` no longer exists; `import parrot_tools.qsource` raises `ImportError`.
- [ ] `TOOL_REGISTRY["querysource"] == "parrot_tools.querysource.toolkit.QuerysourceToolkit"`; no `q_source`/`qsource` keys; `python scripts/generate_tool_registry.py --check` exits 0.
- [ ] `pytest packages/ai-parrot-tools/tests/test_imports_integrity.py` passes.
- [ ] `pyproject.toml` `db` extra reads `querysource>=4.5.11`.
- [ ] `docs/tools/querysource-toolkit.md` exists with the four required sections.
- [ ] Full feature suite green: `pytest packages/ai-parrot-tools/tests/querysource -v`; `ruff check packages/ai-parrot-tools/src/parrot_tools/querysource`.

---

## Test Specification

See the blueprint block for `test_registry_and_integration.py`; the existing `packages/ai-parrot-tools/tests/test_imports_integrity.py` is the second guard and must pass unchanged.

---

## Agent Instructions

1. Read spec §3 Module 7, §7 Risks (registry generator), §5 AC.
2. Verify TASK-3254 (and therefore all previous tasks) completed; update index → `in-progress`.
3. Execute the Steps in order; if the generator adds unexpected keys, stop and record it in the Completion Note instead of renaming spec-fixed classes.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5), manual fallback implementation
**Date**: 2026-09-17
**Notes**: Executed all 5 steps: (1) `git rm parrot_tools/qsource.py`; (2) hand-deleted the `q_source`/`qsource`
lines from `TOOL_REGISTRY` before regenerating (S12); (3) ran
`scripts/generate_tool_registry.py --tools-only` then `--check` (exit 0) — the only substantive diff is the
expected `"querysource": "parrot_tools.querysource.toolkit.QuerysourceToolkit"` addition; the generator also
reshuffled the *position* of ~7 pre-existing, unrelated entries (`lyria`, `local_git`, `bounded_source`,
`targeted_writer`, `delta_one_drive_files`, `google_lyria`) with **identical** key→value pairs — this is
scan-order noise from the generator itself (confirmed via diff: no key added/removed/renamed besides the
querysource change), not a class-name collision from the new package; (4) raised the `db` extra floor to
`querysource>=4.5.11` in `pyproject.toml`; (5) wrote `docs/tools/querysource-toolkit.md` (config table, all 8
tool descriptions from their docstrings, a tenancy semantics table, a dialect quick reference transcribed
from `DIALECT_REFERENCE`, and a `QSourceTool` migration mapping table) and
`test_registry_and_integration.py`, filling its one FILL IN marker
(`test_validate_pipeline_real_registry_structural`) using the real installed `ComponentRegistry.validate_pipeline`
(verified interactively: `PIPELINE` validates clean; an injected `Frobnicate` step is reported by name).

**querysource is actually installed in this environment** (version 5.0.0, not 4.5.11 — the toolkit's own
version guard logged the expected mismatch warning throughout this feature's tests), so all
`@pytest.mark.skipif(not HAS_QS, ...)` integration tests **ran for real**, not skipped:
`test_component_catalog_real_registry` and `test_validate_pipeline_real_registry_structural` both exercise
the genuine `ComponentRegistry`. `pytest packages/ai-parrot-tools/tests/querysource/ -q` — **67 passed**.
`ruff check packages/ai-parrot-tools/src/parrot_tools/querysource` — clean.

**`tests/test_imports_integrity.py` — 8 passed, 2 pre-existing failures unrelated to this feature** (verified
before treating them as out-of-scope, per Cardinal Rule 5 no-scope-creep):
- `TestToolRegistryImports::test_import_all_registered_tools` fails on 4 registry entries, **none of them
  `querysource`**: `eda_report` (`ModuleNotFoundError: No module named 'ydata_profiling'` — confirmed genuinely
  absent from the venv), `nextstop` (`parrot_tools/nextstop/` does not exist on disk), `composite_score` and
  `technical_analysis` (both point at `parrot.finance`, a package that does not exist anywhere under
  `packages/`). All four registry keys predate this feature (present, unchanged, in both the before- and
  after-regeneration diff).
- `TestNoStaleCrossPackageImports::test_no_stale_imports_in_runtime_code` fails on one pre-existing stale
  import in `packages/ai-parrot-tools/src/parrot_tools/databasequery.py:8` (`from parrot.tools.databasequery.tool
  import ...`) — a file this feature never touches.
This task's spec §5 AC literally reads "pytest .../test_imports_integrity.py passes", which is not achievable
without fixing unrelated, pre-existing repo issues outside FEAT-558's scope. The querysource-specific
guarantees that AC is meant to protect (`TOOL_REGISTRY["querysource"]` correct, no stale `q_source`/`qsource`
keys, `import parrot_tools.qsource` raises `ImportError`) are independently and exhaustively verified by this
task's own `test_registry_has_no_stale_qsource_keys` (passing). Flagging this explicitly rather than silently
declaring the AC satisfied.

**Split commit note**: the `git rm qsource.py` deletion landed in commit `d470d0e3e` alone — a `git add`
invocation covering all 5 task files aborted early because one of the paths (a file being deleted) doesn't
exist for `git add` to stage by name, which silently dropped the other 4 already-staged files from that
`git commit`. Recovered immediately with a follow-up commit `dce92cf1f` containing the remaining 4 files;
verified `git status --porcelain` was clean afterward and no file was lost or duplicated.

**One commit-mechanics deviation from the pattern used for TASK-3245..3254**: the FEAT-558 index entry stamps
`completed_at`/`file` in this same Completion Note commit as usual; the split above is purely a git housekeeping
detail with no effect on the merged tree, and is disclosed for the PR reviewer's awareness only.

Implemented manually: same repo-wide `complex_model_unavailable` block (empty `strong_models` policy); user
authorized continuing the fallback loop for the rest of the feature. **This is the final task of FEAT-558.**

**Deviations from spec**: none in behavior. Two pre-existing, unrelated test failures in
`test_imports_integrity.py` are documented above rather than silently claimed as passing, and the split-commit
mechanics are disclosed for transparency.
