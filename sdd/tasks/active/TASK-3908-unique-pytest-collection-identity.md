# TASK-3908: Unique pytest collection identity per package

**Feature**: FEAT-618 — Merge-Tier Gate Integrity & parrot-formdesigner Baseline Repair
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. 24 of the 28 `packages/*/tests/` roots carry a
`tests/__init__.py`, so every one of them resolves to the same top-level import
name `tests`. Collecting any two in one pytest session collides, which is why
`packages/ai-parrot-embeddings/tests/test_wheel_layout.py` errors during a
merge-tier run but passes 15/15 standalone.

This is the riskiest task in the feature: it changes how every test in the
monorepo is imported. It lands on its own commit, before M3–M7 rebase onto it.

---

## Scope

- Choose between the two candidate strategies in spec §3 Module 1 **by
  measurement**, trying (a) first and falling back to (b) only on recorded
  evidence.
- Apply the chosen strategy across all 24 affected packages.
- Rewrite every `from tests.… import …` / `import tests.…` site to the chosen
  convention (24 files — listed in "Files to Create / Modify").
- Add a regression test that collecting two package test roots together
  succeeds, so the collision cannot return silently.
- Record the rejected strategy and why in the Completion Note.

**NOT in scope**: fixing any `parrot-formdesigner` test failure (TASK-3910 /
3911 / 3912 / 3913 / 3914); changing the merge-tier selector (TASK-3909);
touching the 4 packages that already have no `tests/__init__.py`
(`ai-parrot-advisors`, `ai-parrot-openlit-bridge`, `navrules`) beyond what the
uniform rule requires.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | `[tool.pytest.ini_options]` → `addopts` import mode (strategy (a)) |
| `packages/ai-parrot/tests/__init__.py` | MODIFY | delete or rename per chosen strategy |
| `packages/ai-parrot-client-amazon/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-anthropic/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-gemma4/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-google/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-grok/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-groq/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-hf/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-jev/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-local/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-meta/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-moonshot/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-nvidia/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-openai/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-openrouter/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-vllm/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-client-zai/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-embeddings/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-integrations/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-loaders/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-pipelines/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-server/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-tools/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-visualizations/tests/__init__.py` | MODIFY | same |
| `packages/parrot-formdesigner/tests/__init__.py` | MODIFY | same |
| `packages/ai-parrot-integrations/tests/agentd/test_e2e.py` | MODIFY | rewrite `from tests.…` import |
| `packages/ai-parrot-integrations/tests/agentd/test_service.py` | MODIFY | same |
| `packages/ai-parrot/tests/bots/flows/test_storage_parity.py` | MODIFY | same |
| `packages/ai-parrot/tests/eval/test_benchmarks_e2e.py` | MODIFY | same |
| `packages/ai-parrot/tests/handlers/test_checkpoint_handlers.py` | MODIFY | same |
| `packages/ai-parrot/tests/integration/rag/test_store_router_integration.py` | MODIFY | same |
| `packages/ai-parrot/tests/integration/test_jira_wiki_e2e.py` | MODIFY | same |
| `packages/ai-parrot/tests/interfaces/jira/conftest.py` | MODIFY | same |
| `packages/ai-parrot/tests/knowledge/wiki/conftest.py` | MODIFY | same |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py` | MODIFY | same |
| `packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py` | MODIFY | same |
| `packages/ai-parrot/tests/knowledge/wiki/test_vault_scan.py` | MODIFY | same |
| `packages/ai-parrot/tests/loaders/obsidian/conftest.py` | MODIFY | same |
| `packages/ai-parrot/tests/outputs/a2ui/runtime/test_dispatch.py` | MODIFY | same |
| `packages/ai-parrot/tests/tools/test_obsidian_okf_tools.py` | MODIFY | same |
| `packages/ai-parrot/tests/tools/test_obsidian_toolkit.py` | MODIFY | same |
| `packages/ai-parrot/tests/unit/clients/test_factory_discovery.py` | MODIFY | same |
| `packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py` | MODIFY | same |
| `packages/ai-parrot-tools/tests/business_automation/test_fixture_site_e2e.py` | MODIFY | same |
| `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` | MODIFY | same |
| `packages/parrot-formdesigner/tests/integration/conftest.py` | MODIFY | same |
| `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` | MODIFY | same |
| `packages/parrot-formdesigner/tests/unit/test_feat302_review_fixes.py` | MODIFY | same |
| `packages/parrot-formdesigner/tests/unit/test_org_graph_service.py` | MODIFY | same |
| `tests/sdd_scripts/test_cross_package_collection.py` | CREATE | regression test for AC2/AC3 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No parrot imports are needed by this task. It edits packaging/test-layout
# files and the regression test shells out to pytest in a subprocess.
import subprocess  # stdlib
import sys         # stdlib
```

### Existing Signatures to Use
```toml
# pyproject.toml:234  — repo root, the ONLY pytest config in the workspace
[tool.pytest.ini_options]
addopts = [            # line 235
    "--strict-config",  # line 236
    "--strict-markers", # line 237
]                       # line 238
testpaths = ["tests"]   # line 239
```

### Does NOT Exist
- ~~a per-package `[tool.pytest.ini_options]`~~ — only the repo-root `pyproject.toml:234` configures pytest.
- ~~`packages/<dist>/pytest.ini` / `setup.cfg` pytest sections~~ — none exist.
- ~~`--import-mode=importlib` as a sufficient fix on its own~~ — **verified NOT sufficient**: with `tests/__init__.py` still present, pytest derives `tests.conftest` from the `__init__.py` chain and fails with `ValueError: Plugin already registered under a different name`. The `__init__.py` files must go or be renamed.
- ~~`consider_namespace_packages`~~ — does not resolve this collision (the dirs are regular packages, not namespace packages).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-embeddings/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/integration/conftest.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_cross_package_collection.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Strategy (a) first.** Delete all 24 `packages/*/tests/__init__.py` and add
  `--import-mode=importlib` to the root `addopts`. Then rewrite the 24
  `from tests.…` importers. Only if (a) cannot be made to pass, fall back to (b)
  (rename each `tests` package uniquely) — and record the measured reason.
- Under strategy (a) a sibling helper is imported by **module name relative to
  its own directory**, which pytest's `rootdir`-based `sys.path` insertion makes
  available (e.g. `from fixture_vault import …` rather than
  `from tests.fixtures.fixture_vault import …`). Verify each rewritten site
  individually — several import from a `fixtures/` subpackage.
- Do NOT delete `packages/parrot-formdesigner/tests/fixtures/__init__.py`,
  `.../tests/formdesigner/__init__.py`, `.../tests/unit/**/__init__.py` etc.
  unless strategy (a) requires it — only the **top-level** `tests/__init__.py`
  of each package creates the collision.
- `--strict-config` and `--strict-markers` must survive in `addopts`.

### References in Codebase
- `pyproject.toml:234-249` — the single pytest configuration block.

---

## Implementation Blueprint

### Steps (in order)
1. Record the baseline collision — *why*: the Completion Note must show the error this task removes.
2. Apply strategy (a): delete the 24 top-level `tests/__init__.py`, add the import mode — *why*: the `__init__.py` chain is what forces the shared `tests.` prefix.
3. Rewrite the 24 `from tests.…` sites — *why*: those imports only resolved because of the package `__init__.py` just removed.
4. Add the regression test — *why*: AC2/AC3 must be enforced by CI, not by memory.
5. If (a) fails after 3, revert and apply (b) — *why*: the spec requires a measured choice, not a preferred one.

### `pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '^addopts = \[' pyproject.toml)
# REPLACE the addopts list at pyproject.toml:235-238
addopts = [
    "--strict-config",
    "--strict-markers",
    "--import-mode=importlib",
]
```
**Why**: `importlib` mode stops pytest deriving a module name from a `sys.path`
prepend, which is the other half of the collision. It is necessary but **not
sufficient** — verified: it still fails while any `tests/__init__.py` remains,
so step 2's deletions must land in the same commit. Do not change
`--strict-config` / `--strict-markers`.

### `packages/*/tests/__init__.py` (MODIFY — 24 files, strategy (a) = delete)
```text
# FILL IN: delete each of the 24 top-level packages/*/tests/__init__.py listed in
# "Files to Create / Modify" — bounded by AC2 (two roots collect together) and by
# the constraint that NESTED __init__.py files (tests/fixtures/, tests/unit/, …)
# are left alone unless a rewritten import in step 3 proves otherwise.
```
**Why**: each of these files is what makes its directory the regular package
`tests`, so 24 directories claim one import name. Removing them is the actual
defect fix; the import mode only keeps pytest from re-creating the clash.

### `tests/sdd_scripts/test_cross_package_collection.py` (CREATE)
```python
"""FEAT-618 TASK-3908: package test roots must collect together (AC2/AC3)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

EMBEDDINGS = "packages/ai-parrot-embeddings/tests"
FORMDESIGNER = "packages/parrot-formdesigner/tests"


def _collect(*targets: str) -> subprocess.CompletedProcess[str]:
    """Run `pytest --collect-only` over `targets` in a clean subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )


def test_two_package_roots_collect_in_one_session() -> None:
    """AC2: no ImportPathMismatchError and no pluggy double-registration."""
    proc = _collect(EMBEDDINGS, FORMDESIGNER)
    # FILL IN: assert proc.returncode == 0 and assert the two known collision
    # signatures are absent from proc.stdout + proc.stderr
    # ("ImportPathMismatchError", "Plugin already registered under a different name")
    # — bounded by AC2.
    raise NotImplementedError


def test_wheel_layout_still_passes_standalone() -> None:
    """AC3: the originally-reported file is unaffected by the layout change."""
    # FILL IN: run the 15 tests in
    # packages/ai-parrot-embeddings/tests/test_wheel_layout.py and assert they
    # all pass — bounded by AC3.
    raise NotImplementedError
```
**Why this shape**: the collision only manifests across two *separate* pytest
sessions' import state, so it cannot be asserted in-process — a subprocess is
required. Keep both tests subprocess-based and keep the two literal error
strings, because those are exactly the two failures observed on `dev`.

### FILL IN checklist
- [ ] `pyproject.toml` — confirm strategy (a) holds after the deletions; bounded by AC2
- [ ] 24 × `packages/*/tests/__init__.py` — delete; bounded by AC2
- [ ] 24 × `from tests.…` import sites — rewrite; bounded by AC2 + each package's own suite staying green
- [ ] `test_cross_package_collection.py` — both assertions; bounded by AC2/AC3
- [ ] Completion Note — record the rejected strategy and the measured reason

---

## Acceptance Criteria

- [ ] **AC2** `python -m pytest packages/ai-parrot-embeddings/tests packages/parrot-formdesigner/tests --collect-only -q` exits 0, with no `ImportPathMismatchError` and no `Plugin already registered under a different name`.
- [ ] **AC3** `python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q` passes 15/15.
- [ ] Each package whose `tests/__init__.py` was removed still collects its own suite with no new import errors.
- [ ] **AC7** `ruff check` clean on every changed Python file.
- [ ] Completion Note records the chosen strategy, the rejected one, and the evidence.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_cross_package_collection.py -q`
- `pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q`
- `pytest packages/ai-parrot/tests/unit/clients/test_factory_discovery.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_vault_scan.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_org_graph_service.py -q`

---

## Test Specification

See the `tests/sdd_scripts/test_cross_package_collection.py` block above — it is
the task's test scaffold and both `FILL IN` bodies must be completed.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug tests-test-wheel-layout-tech-debt --feature-id FEAT-618`)
2. **Read the spec** §3 Module 1 for the two candidate strategies.
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** before writing code; in particular re-confirm `pyproject.toml:234`.
5. **Update status** in `sdd/tasks/index/tests-test-wheel-layout-tech-debt.json` → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** the Validation Commands.
8. **Commit the code** — stage only this task's files (never `git add .` / `-A`).
9. **Close** with `scripts/sdd/close_task.sh TASK-3908 tests-test-wheel-layout-tech-debt verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: Chosen strategy, rejected strategy + measured reason, AC2/AC3 evidence.

**Deviations from spec**: none | describe if any
