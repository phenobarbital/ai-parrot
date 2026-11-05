# TASK-5171: techwiki.yml sync workflow

**Feature**: FEAT-801 — GitHub Wiki as the Technical Reference
**Spec**: `sdd/specs/github-wiki-technical-reference.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5168
**Assigned-to**: unassigned

---

## Context

> Spec §3 M6. Creates the GitHub Actions workflow that publishes the wiki bundle on
> `release: published` and validates it on `pull_request`. Depends on TASK-5168 because the
> workflow runs `parrot sdd techwiki bundle`.

---

## Scope

- CREATE `.github/workflows/techwiki.yml` with `release`, `pull_request`, `workflow_dispatch` triggers
- CREATE `tests/sdd_scripts/test_techwiki_workflow_contract.py` (YAML-level assertions)

**NOT in scope**: The actual `wiki/` content (TASK-5172), the bundle code (TASK-5168), Pages cut-over (M9 follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/techwiki.yml` | CREATE | Wiki sync workflow |
| `tests/sdd_scripts/test_techwiki_workflow_contract.py` | CREATE | YAML contract test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Tests only — import yaml and pathlib
import yaml
from pathlib import Path
```

### Existing Signatures to Use
```python
# .github/workflows/release.yml — trigger pattern to mirror:
# on: release: types: [created]   (techwiki uses [published])

# .github/workflows/docs.yml:11
# paths: ['packages/ai-parrot/src/parrot/**']  — M9 edits this (not this task)
```

### Does NOT Exist
- ~~`.github/workflows/techwiki.yml`~~ — created by this task
- ~~Wiki sync in any existing workflow~~ — none exists

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".github/workflows/techwiki.yml", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_techwiki_workflow_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Trigger `release: [published]` — NOT on every push to `main` (design research S3)
- `pull_request` job: read-only validation, `--dry-run`, fails on collisions/dangling/skipped modules
- `publish` job: `if: github.event_name == 'release'` — pushes to `ai-parrot.wiki.git`
- `permissions: contents: write` (needed for wiki push)
- `concurrency` group serialises runs per event/ref
- Uses `uv sync --package ai-parrot --extra techwiki`
- Bundle step uses `--strict` (exit 4 on skipped modules) and `--json`
- PR paths: `wiki/**`, `docs/decisions/**`, `packages/*/src/**`, `sdd/config.json`, `.github/workflows/techwiki.yml`
- `workflow_dispatch` uploads bundle as artifact only; `publish` job not triggered

---

## Implementation Blueprint

### Steps (in order)
1. Create `.github/workflows/techwiki.yml` — *why*: the deployment pipeline
2. Create contract test — *why*: AC-12

### `.github/workflows/techwiki.yml` (CREATE)
```yaml
name: techwiki
on:
  release:
    types: [published]
  pull_request:
    paths:
      - 'wiki/**'
      - 'docs/decisions/**'
      - 'packages/*/src/**'
      - 'sdd/config.json'
      - '.github/workflows/techwiki.yml'
  workflow_dispatch:
    inputs:
      ref:
        description: 'tag or branch to bundle (preview only unless a published release tag)'
        required: false
permissions:
  contents: write
concurrency:
  group: techwiki-${{ github.event_name }}-${{ github.ref }}
  cancel-in-progress: false
jobs:
  bundle:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.release.tag_name || github.event.inputs.ref || github.sha }}
          fetch-depth: 0
          fetch-tags: true
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: uv sync --package ai-parrot --extra techwiki
      - name: Build bundle
        run: |
          TAG="${{ github.event.release.tag_name || '' }}"
          if [ -z "$TAG" ]; then TAG=$(git describe --tags --always); fi
          # FILL IN: set DRY_RUN flag for pull_request events — bounded by AC-12
          uv run parrot sdd techwiki bundle \
            --out build/techwiki \
            --release "$TAG" \
            --json --strict \
            $DRY_RUN_FLAG
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: techwiki-bundle
          path: build/techwiki/

  publish:
    needs: bundle
    if: github.event_name == 'release'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: techwiki-bundle
          path: build/techwiki
      - name: Push to wiki
        run: |
          git clone https://x-access-token:${{ secrets.GITHUB_TOKEN }}@github.com/${{ github.repository }}.wiki.git wiki-repo
          rsync -a --delete --exclude .git build/techwiki/ wiki-repo/
          cd wiki-repo
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          if git diff --cached --quiet; then
            echo "No changes to push"
          else
            TAG="${{ github.event.release.tag_name }}"
            SHA="${{ github.sha }}"
            git commit -m "techwiki: sync $TAG (${SHA::7})"
            git push
          fi
```
**Why this shape**: `release: [published]` matches the design decision (S3). Separate bundle and publish jobs so the artifact is always uploaded even on failure. PR path uses `--dry-run` implicitly.

### FILL IN checklist
- [ ] `techwiki.yml` bundle step: DRY_RUN flag for pull_request — set `--dry-run` when `github.event_name == 'pull_request'`; bounded by AC-12

---

## Acceptance Criteria

- [ ] Workflow parses as valid YAML (AC-12)
- [ ] `on.release.types == [published]` (AC-12)
- [ ] `on.pull_request` present with paths (AC-12)
- [ ] `permissions.contents == write` (AC-12)
- [ ] `publish` job has `if: github.event_name == 'release'` (AC-12)
- [ ] Bundle step uses `--extra techwiki` and `--strict` (AC-12)
- [ ] PR path uses `--dry-run` (AC-12)
- [ ] No `requests`/`httpx`/LangChain; `ruff check` passes on test file (AC-14)

---

## Validation Commands

- `pytest tests/sdd_scripts/test_techwiki_workflow_contract.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_techwiki_workflow_contract.py
import pytest
import yaml
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/techwiki.yml"


class TestTechwikiWorkflow:
    @pytest.fixture(autouse=True)
    def load_workflow(self):
        assert WORKFLOW.exists(), "techwiki.yml not found"
        self.wf = yaml.safe_load(WORKFLOW.read_text())

    def test_trigger_release_published(self):
        assert self.wf["on"]["release"]["types"] == ["published"]

    def test_trigger_pull_request_present(self):
        assert "pull_request" in self.wf["on"]

    def test_permissions_contents_write(self):
        assert self.wf["permissions"]["contents"] == "write"

    def test_publish_only_on_release(self):
        publish = self.wf["jobs"]["publish"]
        assert "release" in publish["if"]

    def test_bundle_uses_strict(self):
        bundle_job = self.wf["jobs"]["bundle"]
        steps_text = yaml.dump(bundle_job["steps"])
        assert "--strict" in steps_text
        assert "--extra techwiki" in steps_text

    def test_pr_uses_dry_run(self):
        bundle_job = self.wf["jobs"]["bundle"]
        steps_text = yaml.dump(bundle_job["steps"])
        assert "--dry-run" in steps_text or "DRY_RUN" in steps_text
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**
2. **Check dependencies** — TASK-5168 must be `done`
3. **Create** the workflow file
4. **Run tests** — `pytest tests/sdd_scripts/test_techwiki_workflow_contract.py -q`
5. **Commit** only the listed files
6. **Close** with `parrot sdd task close TASK-5171 github-wiki-technical-reference verified`

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by native seat opus, attempt 1 (uid 52e514dc…), commit a21d0cef8b.
**Date**: 2026-11-05
**Notes**: Both listed files delivered; workflow contract tests 9 passed. Coder found a TASK-5168 defect: `parrot sdd techwiki bundle` lacked the `--strict` flag the spec/workflow require (would exit 2 in CI). Fixed by the orchestrator in 15c021b0ca (techwiki_bundle.py: `--strict` → exit 4 when modules skipped); bundle + workflow tests 14 passed. Not run: a real GitHub Actions run; workflow push needs SSH/workflow scope. Review not recorded in the feedback plane (`coder_record_review` broken server-side).

**Deviations from spec**: `"on"` key quoted (PyYAML parses bare `on` as True); event values passed via `env:` instead of inline `${{ }}` (script-injection hardening).
