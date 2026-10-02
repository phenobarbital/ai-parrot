# TASK-4021: CI lint step, docs/wiki/lint.md, end-to-end SQLite test

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-4020
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10, AC12/AC13 + the §4 integration test.

---

## Scope

- Add a step to job `test-wiki-extras` after the wiki pytest step: build a plane over a small committed fixture and run `wikitoolkit lint --fail-on error --no-ledger --no-notes`.
- Write `docs/wiki/lint.md`: every rule id, pack, severity, fixable, plus flags, routing, LLM env vars, CI usage.
- End-to-end test: build fixture plane → seed defects → `lint` → `lint --fix` → `lint`; only non-fixable findings remain.

**NOT in scope**: New rules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/ci.yml` | MODIFY | lint step in test-wiki-extras |
| `docs/wiki/lint.md` | CREATE | Operator docs |
| `packages/ai-parrot/tests/knowledge/lint/test_lint_e2e_sqlite.py` | CREATE | Integration test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint import LintOptions, LintRunner  # TASK-4009/4010
```

### Existing Signatures to Use
```python
# .github/workflows/ci.yml job `test-wiki-extras` (:207); last broad step:
#       - name: Run wiki tests with both extras installed
#         run: uv run pytest tests/knowledge/wiki/ -q --tb=short --continue-on-collection-errors   (:274)
# FILL IN: confirm the job's working-directory (steps run from packages/ai-parrot?) before choosing fixture paths
```

### Does NOT Exist
- ~~an existing lint CI step~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".github/workflows/ci.yml",
      "action": "MODIFY"
    },
    {
      "path": "docs/wiki/lint.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_lint_e2e_sqlite.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; never block the event loop (file I/O via `asyncio.to_thread`).
- Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; 120 cols.
- Writes only through store/export APIs — never raw SQL from a rule; never delete pages or edges (spec AC2).

### References in Codebase
- Spec `sdd/specs/wikitoolkit-lint.spec.md` §2–§7 (rule ids, severities, decisions are fixed there).

---

## Implementation Blueprint

### Steps (in order)
1. Use `wikitoolkit build --path <fixture> --no-git --quiet` then `wikitoolkit lint --path <fixture>` — *why*: CI must be offline and deterministic (no --llm).
2. Push via SSH remote — *why*: the gh OAuth token lacks workflow scope (branches touching .github/workflows need git@github.com).

### `.github/workflows/ci.yml` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '        run: uv run pytest tests/knowledge/wiki/ -q --tb=short --continue-on-collection-errors' .github/workflows/ci.yml)
# AFTER — insert below that line (verified: ci.yml:274)

      - name: Lint a fixture wiki plane (FEAT-625)
        run: |
          # FILL IN: fixture path relative to the job working dir; build flags verified against `wikitoolkit build --help`
          uv run wikitoolkit build --path tests/knowledge/lint/fixtures/repo --no-git --quiet
          uv run wikitoolkit lint --path tests/knowledge/lint/fixtures/repo --fail-on error --no-ledger --no-notes
```

### `docs/wiki/lint.md` (CREATE)
```markdown
# wikitoolkit lint

`wikitoolkit lint` checks the wiki knowledge graph (any backend), its markdown export,
agent memories and ADRs. It reports by default; `--fix` applies only safe, idempotent
fixes and never deletes pages or edges.

## Rules

| Rule id | Pack | Severity | Fixable |
|---|---|---|---|
<!-- FILL IN: one row per rule from default_rules(), generated or copied; include okf-* rules note -->

## Flags
<!-- FILL IN: from `wikitoolkit lint --help` -->

## Where findings go
<!-- FILL IN: ledger (lint:<rule>, fingerprint dedup, per-rule cap), report.json/report.md, page notes -->

## LLM contradiction pass
`--llm` resolves the model from `--llm-model`, `WIKI_LINT_LLM`, `WIKI_EXTRACT_LLM`, then coding-agent
auto-detection (`PARROT_NO_AUTO_LLM=1` disables). At most `--llm-max-pairs` (default 50) pairs are judged.

## CI
<!-- FILL IN: the test-wiki-extras step -->
```

**Why this shape**: AC12/AC13. The fixture must be tiny and committed so CI is offline. If a fixture repo dir is needed, it is created under the test dir declared above — FILL IN: add it to Files if you create one (and keep tests/knowledge/lint/__init__.py untouched).

### FILL IN checklist
- [ ] CI working dir + fixture
- [ ] docs tables
- [ ] e2e test body

---

## Acceptance Criteria

- [ ] CI step present and green locally (`act` not required; run the two commands by hand)
- [ ] Docs list every rule id from `default_rules()`
- [ ] E2E test passes
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_lint_e2e_sqlite.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_lint_e2e_sqlite.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_lint_e2e_sqlite.py
async def test_lint_end_to_end_sqlite(tmp_path):
    # FILL IN: SQLite store in tmp_path; seed: asymmetric references edge, broken edge, duplicate slug;
    #          run -> 3 findings; run(fix=True) -> asymmetric fixed; run -> broken-link + duplicate-slug remain
    ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4021 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
