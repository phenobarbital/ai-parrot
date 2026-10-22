# TASK-4453: Nightly full package-suite workflow on `dev`

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, §5 AC "nightly workflow runs every packages/*/tests + root tests/" (design research S12).
FEAT-699 deliberately narrows LOCAL test selection; the guarantee "nothing else broke" moves here. Today
`.github/workflows/ci.yml` runs only the repo-root `tests/` and NO `packages/*/tests` suite runs in CI at
all — so this net improves coverage versus today, just later (≤ 24 h). Independent track: no kernel code.

---

## Scope

- Create `.github/workflows/nightly-tests.yml`:
  - triggers: `schedule: cron "17 6 * * *"` (UTC) and `workflow_dispatch`; runs on `ref: dev`.
  - job `suites` with an EXPLICIT `strategy.matrix.suite` list (not a glob): `root` (repo `tests/`) and every
    `packages/<dist>` that has a `tests/` dir today (28 dists, listed below), `fail-fast: false`.
  - steps mirror `ci.yml`'s setup (checkout v6, setup-python 3.12, setup-uv v10.2.0, `uv sync --all-packages`),
    then `uv run pytest <suite tests path> -q -m "not real_llm" -o junit_family=xunit1
    --junitxml=junit/<suite>.xml --continue-on-collection-errors -p no:cacheprovider`, with
    `timeout-minutes: 60` for `ai-parrot` and `30` for the rest (matrix `include` overrides).
  - always upload `junit/<suite>.xml` as artifact `junit-<suite>` (`actions/upload-artifact@v4`, `if: always()`).
  - job `summary` (`needs: suites`, `if: always()`): download all junit artifacts, run
    `python scripts/sdd/nightly_red_set.py junit/ --out red-set.json` (CREATE — stdlib-only: failed/error node
    ids per suite, using the same xunit1 node-id rule as `test_scope.report.nodeid_from_testcase` but
    re-implemented locally so the script does not import `parrot`), download the previous run's `red-set`
    artifact when one exists (`dawidd6/action-download-artifact` is NOT allowed — use `gh run download`
    with `GH_TOKEN: ${{ github.token }}` and tolerate absence), compute new reds vs previous, upload
    `red-set.json` as artifact `red-set`, write a step summary, and **fail the job when new reds exist**.
  - permissions: `contents: read`, `actions: read`. The workflow NEVER pushes, commits or writes the ledger.
- Tests: `tests/sdd_scripts/test_nightly_tests_workflow.py` (YAML structure) and
  `tests/sdd_scripts/test_nightly_red_set.py` (script).

Distributions with a `tests/` dir (verified 2026-10-18): ai-parrot, ai-parrot-advisors, ai-parrot-client-amazon,
ai-parrot-client-anthropic, ai-parrot-client-gemma4, ai-parrot-client-google, ai-parrot-client-grok,
ai-parrot-client-groq, ai-parrot-client-hf, ai-parrot-client-jev, ai-parrot-client-local, ai-parrot-client-meta,
ai-parrot-client-moonshot, ai-parrot-client-nvidia, ai-parrot-client-openai, ai-parrot-client-openrouter,
ai-parrot-client-vllm, ai-parrot-client-zai, ai-parrot-embeddings, ai-parrot-integrations, ai-parrot-loaders,
ai-parrot-openlit-bridge, ai-parrot-pipelines, ai-parrot-server, ai-parrot-tools, ai-parrot-visualizations,
navrules, parrot-formdesigner.

**NOT in scope**: GitHub-issue creation for new reds (spec §8 open question — the red job is the signal);
per-PR package CI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/nightly-tests.yml` | CREATE | Matrix workflow |
| `scripts/sdd/nightly_red_set.py` | CREATE | junit dir → red set + diff vs previous |
| `tests/sdd_scripts/test_nightly_tests_workflow.py` | CREATE | Workflow structure test |
| `tests/sdd_scripts/test_nightly_red_set.py` | CREATE | Script test |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
- `.github/workflows/ci.yml` setup steps: `actions/checkout@v6`, `actions/setup-python@v6` (3.12),
  `astral-sh/setup-uv@v10.2.0`, `uv sync --all-packages`.
- `.github/workflows/e2e.yml` — existing nightly workflow; copy its `schedule`/`workflow_dispatch` shape.
- `tests/sdd_scripts/test_e2e_ci_plans.py` — existing pattern for asserting workflow YAML structure (check how it loads YAML).
- Marker `real_llm` registered at `packages/ai-parrot/pyproject.toml:1050`.

### Does NOT Exist
- ~~any workflow running `packages/*/tests`~~ — verified
- ~~`scripts/sdd/nightly_red_set.py`~~ — created here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".github/workflows/nightly-tests.yml", "action": "CREATE"},
    {"path": "scripts/sdd/nightly_red_set.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_nightly_tests_workflow.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_nightly_red_set.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Pushing `.github/workflows/*` needs SSH (`git@github.com:`), the gh token lacks `workflow` scope (team
  memory). If the push is rejected, report it in the Completion Note — never weaken the workflow.
- `nightly_red_set.py`: `main(argv) -> int` — `red-set <junit_dir> --out <json> [--previous <json>]`;
  output `{"suites": {"<suite>": [nodeids...]}, "new_reds": [...]}`; exit 1 when `new_reds` non-empty.
  No `print` for logs (use `logging`), only the final JSON/summary on stdout.

---

## Implementation Blueprint

### `.github/workflows/nightly-tests.yml` (CREATE)
```yaml
name: Nightly — package suites (FEAT-699)

on:
  schedule:
    - cron: "17 6 * * *"
  workflow_dispatch:

permissions:
  contents: read
  actions: read

jobs:
  suites:
    name: ${{ matrix.suite }}
    runs-on: ubuntu-latest
    timeout-minutes: ${{ matrix.timeout }}
    strategy:
      fail-fast: false
      matrix:
        suite: [root, ai-parrot]  # FILL IN: all 28 distributions listed in Scope, explicit
        timeout: [30]
        include:
          - suite: ai-parrot
            timeout: 60
    steps:
      - uses: actions/checkout@v6
        with:
          ref: dev
      # FILL IN: setup-python 3.12, setup-uv v10.2.0, uv sync --all-packages,
      #          pytest step (root → tests ; else packages/<suite>/tests), upload-artifact if: always()
  summary:
    needs: suites
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          ref: dev
      # FILL IN: download-artifact (pattern junit-*), gh run download previous red-set (tolerate absence),
      #          python scripts/sdd/nightly_red_set.py, upload red-set, step summary; fail on new reds
```
**Why**: explicit matrix (S12) makes a new distribution a visible one-line change instead of a silent glob.

### FILL IN checklist
- [ ] full matrix; per-suite path; timeouts
- [ ] summary job with previous-run comparison
- [ ] `nightly_red_set.py`
- [ ] tests: every `packages/*/tests` dir on disk appears in the matrix (so a new dist without a matrix entry fails the test), `real_llm` excluded, no `contents: write`, no `git push` anywhere in the file

---

## Acceptance Criteria

- [ ] `test_nightly_tests_workflow.py` proves matrix ⊇ every existing `packages/*/tests` dir + `root`.
- [ ] The workflow has no write permission and no push/commit step.
- [ ] `nightly_red_set.py` reports new reds vs a previous red set and exits 1 when there are any.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_nightly_tests_workflow.py -q`
- `pytest tests/sdd_scripts/test_nightly_red_set.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_nightly_tests_workflow.py
def test_matrix_covers_every_package_suite():
    # FILL IN: load YAML; compare matrix.suite to sorted(p.parent.name for p in ROOT.glob("packages/*/tests")) + ["root"]
    ...
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4453 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
