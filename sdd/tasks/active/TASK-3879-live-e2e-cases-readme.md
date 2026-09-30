# TASK-3879: Live E2E pytest cases, opt-in fixtures and README

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3878
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 14** (`test_live_compliance` skeleton) and §4 **"Live E2E behavior (not the deterministic
E2E gate)"**. TASK-3878 created the harness core (`models.py`, `runner.py`) and the `.gitignore` negations
that admit `conftest.py`, `test_compliance.py` and `README.md` in `examples/planogram/e2e/`. This task adds
the thin pytest layer that turns the runner into three opt-in live cases — `shelves`, `ink-wall`,
`backlit-endcap` — plus the README that tells a human how to supply private assets, labels and credentials.

Invocation contract (spec §4): `PARROT_TEST_REAL_LLM=1 pytest examples/planogram/e2e -q` with
`PLANOGRAM_E2E_MANIFEST` pointing at a local manifest. These live cases are **not** a CI gate and this
feature does not add `e2e` frontmatter or an E2E gate plan.

---

## Scope

- Create `examples/planogram/e2e/conftest.py`: load `runner.py` by path, a session `harness` fixture, a
  session `live_manifest` fixture (opt-in and manifest checks) and a `case` fixture parametrized over the
  three case ids that turns missing prerequisites into explicit `pytest.skip`.
- Create `examples/planogram/e2e/test_compliance.py` with `async def test_live_compliance(case)` that runs
  `run_case` and asserts no ground-truth violations, printing the report path on failure.
- Create `examples/planogram/e2e/README.md`: purpose, privacy rules, prerequisites, manifest / config /
  ground-truth formats with a **fictitious** template, run command, skip-vs-fail table, outputs, cache and
  request-budget semantics, accuracy signoff rule.

**NOT in scope**: `models.py`, `runner.py`, `.gitignore`, the offline harness tests (all TASK-3878); any
`parrot_pipelines` source change; docs under `docs/pipelines/` (TASK-3880); selecting or labelling real
fixtures (human work, spec §8 open item owned by Jesus Lara); committing any photo, config, manifest or
ground truth.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/e2e/conftest.py` | CREATE | Runner loader, opt-in/manifest/case fixtures with explicit skips |
| `examples/planogram/e2e/test_compliance.py` | CREATE | `test_live_compliance` over the three live cases |
| `examples/planogram/e2e/README.md` | CREATE | Operator guide with a fictitious manifest/ground-truth template |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest  # test stack; repo-root pytest.ini sets asyncio_mode = auto (verified: pytest.ini:3)
# Nothing from parrot_pipelines is imported directly here: everything goes through runner.py (TASK-3878).
```

### Existing Signatures to Use
```python
# pytest.ini (repo root) — registered markers used here (verified: pytest.ini:4-7):
#   live: "Live integration tests that require external services ... Skipped when prerequisites are missing."
#   real_llm: "Real LLM integration tests (require PARROT_TEST_REAL_LLM=1 env var)"
# The repo-root pytest.ini wins over pyproject.toml, so `pytest examples/planogram/e2e` runs with
# asyncio_mode=auto: plain `async def` tests need no @pytest.mark.asyncio.

# Example-script loader pattern (nothing under examples/ is a package):
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py:16-26
#   spec_from_file_location(name, path) -> module_from_spec -> sys.modules[name] = module -> exec_module
```

### Symbols created by dependency tasks (not yet on dev)
```python
# examples/planogram/e2e/models.py (TASK-3878), loaded by runner.py as module "planogram_e2e_models"
CASE_TYPES: dict[str, str]  # {"shelves": "product_on_shelves", "ink-wall": "ink_wall", "backlit-endcap": "endcap_backlit_multitier"}
class GroundTruth(BaseModel): expected_positions; expected_occupancy; expected_rules; overall_score;
                              score_tolerance; min_coverage; max_identity_errors; max_occupancy_errors
class LiveCase(BaseModel): case_id; planogram_type; photos; config_path; ground_truth_path; backend;
                           cache_dir; output_dir; max_provider_requests = 64; timeout_seconds = 600.0
class LiveManifest(BaseModel): cases: list[LiveCase]; required_env: dict[str, list[str]]

# examples/planogram/e2e/runner.py (TASK-3878), to be loaded here as module "planogram_e2e_runner"
OPT_IN_ENV = "PARROT_TEST_REAL_LLM"; MANIFEST_ENV = "PLANOGRAM_E2E_MANIFEST"
GroundTruth, LiveCase, LiveManifest, CASE_TYPES  # re-exported module attributes
def opt_in_enabled(environ: Mapping[str, str]) -> bool
def load_manifest(path: Path) -> LiveManifest  # raises on malformed JSON / schema
def missing_prerequisites(case: LiveCase, manifest: LiveManifest, environ: Mapping[str, str]) -> list[str]
async def run_case(case: LiveCase) -> dict[str, Any]  # {"case_id", "violations", "provider_requests", "report_path", "compliance_path"}
def compare_ground_truth(result: Mapping[str, Any], truth: GroundTruth) -> list[str]
```

### Does NOT Exist
- ~~`examples/planogram/e2e/__init__.py`~~ — must NOT be created (not admitted by `.gitignore`; examples are not packages).
- ~~An `e2e` auto-skip hook for `examples/`~~ — the `e2e` directory auto-marker lives only in package test
  conftests (`packages/ai-parrot/tests/conftest.py:28`); the opt-in skip must be implemented here.
- ~~A committed manifest, photo, config or ground truth~~ — none exists and none may be added.
- ~~`examples/planogram/pipelines/` in a worktree~~ — untracked/ignored; never import from it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "examples/planogram/e2e/conftest.py", "action": "CREATE"},
    {"path": "examples/planogram/e2e/test_compliance.py", "action": "CREATE"},
    {"path": "examples/planogram/e2e/README.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_backend_benchmark.py:16-26
spec = importlib.util.spec_from_file_location("backend_benchmark", _SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
```

### Key Constraints
- **Skip vs fail is the whole point** (spec §4): no opt-in, no manifest variable, manifest file absent, a
  case not configured, or any `missing_prerequisites` reason ⇒ `pytest.skip(<reason>)` BEFORE `run_case`
  (so no provider client is ever created). A manifest that exists but is malformed, an invalid ground
  truth, a wrong config type or a failing `check_row` ⇒ the exception propagates and the test fails.
- Load `runner.py` lazily inside the `harness` fixture, not at conftest import — *why*: collecting the
  directory without opt-in must stay cheap and must not import provider SDKs.
- Keep the module name `planogram_e2e_runner` (TASK-3878 notes rely on it) and never add `sys.path`
  entries: `runner.py` loads its own sibling `models.py`.
- `test_live_compliance` keeps the spec skeleton signature `(case: LiveCase) -> None`; it reaches the
  runner through `sys.modules["planogram_e2e_runner"]`, which the `case` fixture guarantees is loaded
  (it depends on `harness`). Import `LiveCase` only under `TYPE_CHECKING` so ruff sees the name.
- Mark tests `live` and `real_llm` (both registered in `pytest.ini`); do not invent markers
  (`--strict-markers` may be active through other configs).
- README must contain only fictitious names (e.g. `Acme`, `demo-shelf-01`, `/path/to/private/...`) — no
  retailer, store, SKU, photo name or real count (spec §4 "README contains a fictitious template").
- Never print secrets: skip reasons name missing variables, never values.

### References in Codebase
- `examples/planogram/aws/README.md`, `examples/planogram/perception_spike/README.md` — tone/structure of example READMEs.
- `packages/ai-parrot/tests/conftest.py:19-21` — existing `PARROT_TEST_REAL_LLM` skip wording.

---

## Implementation Blueprint

### Steps (in order)
1. Create `conftest.py` — *why*: every skip decision must happen in fixtures before the test body runs.
2. Create `test_compliance.py` — *why*: one small async test keeps the live surface auditable.
3. Run `pytest examples/planogram/e2e/test_compliance.py -q` WITHOUT opt-in and confirm 3 skipped —
   *why*: default opt-out is an AC17 requirement and needs no credentials to prove.
4. Write `README.md` — *why*: AC17/AC19 need an operator path to three signed-off local reports.

### `examples/planogram/e2e/conftest.py` (CREATE)
```python
"""Opt-in fixtures for the planogram live E2E cases (FEAT-612, spec Module 14 / §4 Live E2E behavior).

Nothing here runs without ``PARROT_TEST_REAL_LLM=1`` and ``PLANOGRAM_E2E_MANIFEST``; every missing
prerequisite is an explicit skip taken before any provider client is created.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
HARNESS_MODULE = "planogram_e2e_runner"
LIVE_CASE_IDS = ("shelves", "ink-wall", "backlit-endcap")


def _load_runner() -> ModuleType:
    """Load ``runner.py`` by path under a unique module name (reused if already loaded)."""
    # FILL IN: return sys.modules[HARNESS_MODULE] when present; otherwise spec_from_file_location(
    #   HARNESS_MODULE, _HERE / "runner.py"), register in sys.modules BEFORE exec_module, return it.


@pytest.fixture(scope="session")
def harness() -> Iterator[ModuleType]:
    """The runner module; popped from sys.modules at session end."""
    module = _load_runner()
    try:
        yield module
    finally:
        sys.modules.pop(HARNESS_MODULE, None)


@pytest.fixture(scope="session")
def live_manifest(harness: ModuleType) -> Any:
    """Validated manifest, or an explicit skip when the run is not opted in / not configured."""
    # FILL IN: not harness.opt_in_enabled(os.environ) ⇒ pytest.skip("Set PARROT_TEST_REAL_LLM=1 ...");
    #   env var harness.MANIFEST_ENV unset/blank ⇒ skip naming the variable; path (expanduser) not a file ⇒
    #   skip naming the path; otherwise `return harness.load_manifest(path)` — do NOT catch its errors
    #   (malformed manifest must fail, spec §4).


@pytest.fixture(params=LIVE_CASE_IDS)
def case(request: pytest.FixtureRequest, harness: ModuleType, live_manifest: Any) -> Any:
    """The configured LiveCase for this case id, or a skip naming what is missing."""
    # FILL IN: find the manifest case with case_id == request.param; absent ⇒ skip "case <id> is not
    #   configured in the manifest"; reasons = harness.missing_prerequisites(case, live_manifest, os.environ);
    #   reasons ⇒ pytest.skip("; ".join(reasons)); else return the case.
```
**Why this shape**: the spec requires skips "before provider initialization"; putting them in fixtures
means `test_live_compliance` only ever sees a fully provisioned case. `LIVE_CASE_IDS` mirrors
`CASE_TYPES` keys so each of the three fixtures reports its own skip/pass line.

### `examples/planogram/e2e/test_compliance.py` (CREATE)
```python
"""Live planogram compliance cases (FEAT-612). Opt-in, private local assets, not a CI gate.

Run: PARROT_TEST_REAL_LLM=1 PLANOGRAM_E2E_MANIFEST=/path/to/manifest.json pytest examples/planogram/e2e -q
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from models import LiveCase  # annotation only; runtime loading goes through conftest

pytestmark = [pytest.mark.live, pytest.mark.real_llm]


async def test_live_compliance(case: LiveCase) -> None:
    """Assert human labels/tolerances after explicit opt-in and required local prerequisites."""
    harness = sys.modules["planogram_e2e_runner"]  # loaded by conftest's `harness` fixture via `case`
    outcome = await harness.run_case(case)
    # FILL IN: assert outcome["violations"] == [] with a message listing every violation and
    #   outcome["report_path"] (so a human can open the evidence) — never loosen or filter violations.
```
**Why**: signature is the spec skeleton; the body stays trivial because all judgement lives in the
offline-tested `run_case` / `compare_ground_truth`. The `TYPE_CHECKING` import keeps `LiveCase`
resolvable for ruff (F821) without importing `models.py` as a bare top-level module at runtime.

### `examples/planogram/e2e/README.md` (CREATE) — outline (write prose, not code)
- **Title + one-paragraph purpose**: opt-in live check of the three-stage planogram cycle on private
  photos; not a CI gate; accuracy claims need these reports (AC17).
- **Privacy**: repository is public; only the five harness files are tracked (`.gitignore` FEAT-612 block);
  keep manifest, photos, configs, definitions, ground truth, cache, renders and reports under ignored paths
  in this folder or outside the repo; never `git add -f` them.
- **Prerequisites**: `ai-parrot-pipelines` installed (optionally `[planogram]` extra for local OCR),
  provider credentials in environment variables, configs migrated and passing preflight
  (link `docs/pipelines/planogram-cycle-migration.md`).
- **Manifest format**: fictitious JSON example with `cases` (three entries using `shelves`, `ink-wall`,
  `backlit-endcap`, `planogram_type`, `photos`, `config_path`, `ground_truth_path`, `backend`
  `"provider:model"`, `cache_dir`, `output_dir`, optional `max_provider_requests`/`timeout_seconds`) and
  `required_env` keyed by provider; note relative paths resolve against the manifest directory and each
  case needs its own cache/output directory.
- **Config file**: an exported `troc.planograms_configurations` row as JSON (`config_name`,
  `planogram_type`, `planogram_config` incl. optional `layout_profile`, `slots_definition`,
  `reference_images`, `llm_backend`); its `planogram_type` must equal the case's.
- **Ground truth format**: fictitious JSON with every `GroundTruth` field; explain facing ids come from the
  slots definition, occupancy `occupied|empty|unknown`, rule ids from `rule_bindings`, tolerances in [0,1],
  error budgets ≥ 0; labels are made by a human looking at the photo — never copied from a run.
- **Running**: the exact command from spec §4; running one case with `-k shelves`.
- **Skip vs fail table**: skip = no opt-in / no manifest / case not configured / missing file / missing
  credential; fail = malformed manifest or truth, wrong type, failing preflight, any violation.
- **Outputs**: `compliance.json`, `report.json` fields (backend, config/photo fingerprints, prompt version,
  reference selection, request/cache counts, errors, assertions), render PNGs.
- **Cost and cache**: 64 uncached provider requests and 600 s per case by default; every provider call
  counts (detector, evidence, repairs); cache hits are free only when images, references, prompt, model and
  schema are unchanged — do not promise free re-runs.
- **Signoff**: accuracy signoff requires three successful local reports (one per case) — AC17.

### FILL IN checklist
- [ ] `conftest.py::_load_runner` — path loader with unique module name
- [ ] `conftest.py::live_manifest` — opt-in, env var, file-existence skips; malformed manifest propagates
- [ ] `conftest.py::case` — per-id lookup and `missing_prerequisites` skips
- [ ] `test_compliance.py::test_live_compliance` — assertion message with violations and report path
- [ ] `README.md` — every outline bullet, fictitious names only

---

## Acceptance Criteria

- [ ] AC17: without `PARROT_TEST_REAL_LLM=1`, `pytest examples/planogram/e2e/test_compliance.py -q` reports
      3 skipped and creates no client (no provider SDK import triggered by the skip path).
- [ ] AC17: with opt-in but no manifest variable / missing file / unconfigured case / missing credential,
      each case skips with a reason naming what is missing; a malformed manifest fails.
- [ ] AC17: an opted-in, provisioned case fails with the full violation list and report path when any
      ground-truth assertion fails.
- [ ] AC18: README contains only fictitious data; `git status` after creating the files shows exactly the
      three new files as untracked-but-not-ignored (no `git add -f` needed).
- [ ] `ruff check` and `black --check --line-length 120` pass on the two Python files.

## Validation Commands

- `pytest examples/planogram/e2e/test_compliance.py -q`

Also run these gates (kept out of the bullet list because the task-graph linter accepts only pytest bullets):
`ruff check examples/planogram/e2e/conftest.py examples/planogram/e2e/test_compliance.py`  
`black --check --line-length 120 examples/planogram/e2e/conftest.py examples/planogram/e2e/test_compliance.py`  

---

## Test Specification

```python
# examples/planogram/e2e/test_compliance.py — the live test itself (see blueprint).
# Offline behaviour of the fixtures is verified by running, with a scratch manifest under tmp paths:
#
# 1. unset PARROT_TEST_REAL_LLM                     ⇒ 3 skipped, reason mentions PARROT_TEST_REAL_LLM
# 2. PARROT_TEST_REAL_LLM=1, no PLANOGRAM_E2E_MANIFEST ⇒ 3 skipped, reason names PLANOGRAM_E2E_MANIFEST
# 3. manifest path that does not exist              ⇒ 3 skipped, reason names the path
# 4. manifest file containing "{"                   ⇒ errors (json.JSONDecodeError), NOT skipped
# 5. valid manifest with only a "shelves" case whose photo is missing
#                                                   ⇒ shelves skipped naming the photo; ink-wall and
#                                                     backlit-endcap skipped as "not configured"
#
# Commands (record outputs in the Completion Note; scratch files must live outside the repo):
#   pytest examples/planogram/e2e/test_compliance.py -q -rs
#   PARROT_TEST_REAL_LLM=1 pytest examples/planogram/e2e/test_compliance.py -q -rs
#   PARROT_TEST_REAL_LLM=1 PLANOGRAM_E2E_MANIFEST=$SCRATCH/bad.json pytest examples/planogram/e2e/test_compliance.py -q
# Unit coverage of load_manifest / missing_prerequisites / run_case lives in TASK-3878's
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_live_e2e_harness.py.
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`, never `git add -f`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3879 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
