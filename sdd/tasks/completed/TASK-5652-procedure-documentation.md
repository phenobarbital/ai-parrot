# TASK-5652: Documentation — `wiki/sdd-tooling/sdd/procedure-graph.md`

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5642, TASK-5644, TASK-5645, TASK-5646, TASK-5648, TASK-5649
**Assigned-to**: unassigned

---

## Context

Spec §10 (documentation policy `required`), §3 Module 12 and §5. One operator page documents the
procedure graph as it was **implemented**, including the pilot baseline and the pilot activation
step the owner decided on 2026-11-13 (ai-parrot switches its interactive guard to the packaged
Python guard after merge).

---

## Scope

- Create `wiki/sdd-tooling/sdd/procedure-graph.md` from `sdd/templates/techwiki-page.md`.
- Create `tests/knowledge/wiki/procedure/test_docs_present.py`.

**NOT in scope**: code. `wiki/_index.yaml` needs no edit — it lists sections, not pages, and the
`sdd-tooling` section already exists (spec rev 0.3 decision 9). `.claude/settings.json` is
untracked: the page describes the switch, this task does not perform it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/sdd-tooling/sdd/procedure-graph.md` | CREATE | The operator page |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_docs_present.py` | CREATE | The page exists and names what it must |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). Everything the page documents is created by this feature's
> other tasks — document the **code as merged in the worktree**, not the spec.

### Verified Imports
```python
# test file: pathlib only
```

### Existing Signatures to Use
```python
# sdd/templates/techwiki-page.md — frontmatter (title, summary) and the sections:
#   Purpose · Public API · Configuration & Parameters · Usage Examples · Gotchas · Related
#   Public API links use the form  [`ClassName`](ref:parrot.module.ClassName)
# wiki/_index.yaml:37  `  - id: sdd-tooling` — the section the page belongs to (no per-page entry exists in this file)
# wiki/sdd-tooling/sdd/ — sibling pages to match in tone: decision-audit.md, closeout-hooks.md, test-selection-validation-contract.md
# packages/ai-parrot/tests/knowledge/wiki/schema/test_docs_present.py — the docs-test pattern to follow
# packages/ai-parrot/src/parrot/sdd/scripts/check_task_state.py:98  def find_violations(...)  — behind `parrot sdd task state`
# `parrot sdd techwiki check --spec <spec> --root .` — reports a spec's declared pages; never blocking
```

### Does NOT Exist
- ~~A per-page list in `wiki/_index.yaml`~~ — sections only.
- ~~`procedure.db`~~ — the plane is `.parrot/procedure/wiki.db` + `procedures.json`.
- ~~Guard integration for codex or agy~~ — they receive the task-start block only; say so.
- ~~Dispatch of mandatory procedures / an effect of `confirm` or `executor`~~ — inert in v1; say so.
- ~~Enforcement of `pr.open`~~ — it is a remote probe, CLI only; the cached local signal is a
  recorded follow-up.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/sdd-tooling/sdd/procedure-graph.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_docs_present.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- Required content, in the template's sections:
  1. **Purpose** — the three questions (what is true / what matters now / what to do next) in two
     sentences, and what this plane answers.
  2. **Public API** — `ref:` links for `ProcedureSpec`, `ProcedureManifest`, `ProcedurePlane`,
     `validate_graph`, `resolve` under `parrot.knowledge.wiki.procedure`.
  3. **Configuration & Parameters** — the manifest format (every field of a node), the overlay
     rules (`exclude`, extra files), the probe table with cost classes, the `procedure` section of
     `sdd/config.json` (`enabled`, `enforce`, `brief_max_lines`, `remote_probe_timeout_seconds`),
     the skill frontmatter `procedure:` mapping, and the three escape switches
     (`PARROT_ALLOW_PROCEDURE=1`, `PARROT_ALLOW_DANGEROUS=1`, `procedure.enforce: false`).
  4. **Usage Examples** — the six verbs (`build`, `list`, `show`, `next`, `check`, `brief`), the
     MCP tool `wiki_procedure_next`, and the namespace registration command
     `wikitoolkit ns add procedure --store .parrot/procedure`.
  5. **Gotchas** — the guard decision table; advisory text reaches the model after the command;
     coverage (interactive Claude Code with the packaged guard, and launched workers; not codex,
     not agy); a stale plane silences the guard until the next build; sources and plane are read
     from the primary checkout; `gh pr create` without `--base` is not denied.
  6. A section titled exactly **`## Pilot activation`** — the operator step: check rule parity
     between `.claude/hooks/dangerous-actions-blocker.sh` and the packaged Python guard, then run
     `parrot sdd install --portable` in the repository so `.claude/settings.json` registers
     `parrot sdd hooks dangerous-actions --hook`; say that the settings file is untracked, so each
     collaborator runs it.
  7. A section titled exactly **`## Pilot baseline`** — the count printed by
     `parrot sdd task state` on the feature branch when this task is done, with the date and the
     commit sha; and how to compare later.
- Write the examples by running the commands in the worktree; do not copy output from the spec.

---

## Implementation Blueprint

### Steps (in order)
1. Read the template and one sibling page — *why*: tone and link forms.
2. Run each verb once in the worktree and record real output for the examples and the baseline.
3. Write the page.
4. Write the test; run the validation command and the techwiki check.

### `wiki/sdd-tooling/sdd/procedure-graph.md` (CREATE)
```markdown
---
title: Procedure Graph
summary: The procedure plane — what to do next in a workflow, as a deterministic, queryable graph.
---

# Procedure Graph

<!-- FILL IN: the seven content blocks of the Implementation Notes, in the template's section order,
     written from the implemented code. Keep `## Pilot activation` and `## Pilot baseline` as exact headings. -->
```

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_docs_present.py` (CREATE)
```python
"""The operator page for the procedure graph exists and covers what the spec requires (FEAT-891)."""

from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[6] / "wiki" / "sdd-tooling" / "sdd" / "procedure-graph.md"

REQUIRED = (
    "parrot sdd procedure build",
    "parrot sdd procedure next",
    "parrot sdd procedure check",
    "parrot sdd procedure brief",
    "wiki_procedure_next",
    "PARROT_ALLOW_PROCEDURE",
    "PARROT_ALLOW_DANGEROUS",
    "enforce",
    "wikitoolkit ns add procedure",
    "## Pilot activation",
    "parrot sdd install --portable",
    "## Pilot baseline",
    "parrot sdd task state",
)


def test_docs_present() -> None:
    """The page exists and names the CLI verbs, the three escape switches and the pilot steps."""
    if not PAGE.parent.is_dir():
        pytest.skip("not running from the monorepo checkout")
    text = PAGE.read_text(encoding="utf-8")
    missing = [needle for needle in REQUIRED if needle not in text]
    assert not missing, f"procedure-graph.md lacks: {missing}"
```
**Why**: `parents[6]` is the repository root from
`packages/ai-parrot/tests/knowledge/wiki/procedure/` (procedure → wiki → knowledge → tests →
ai-parrot → packages → root); confirm it resolves before relying on it.

### FILL IN checklist
- [ ] `procedure-graph.md` — all seven blocks, examples from real command output
- [ ] The baseline number, date and commit sha are filled in (not a placeholder)

---

## Acceptance Criteria

- [ ] `wiki/sdd-tooling/sdd/procedure-graph.md` exists and follows the template's sections.
- [ ] It documents the model, the manifest and overlay, the probes, the guard behavior, the three escape switches, the skill fields, the six verbs, the MCP tool and the namespace command.
- [ ] It has a "Pilot activation" section naming `parrot sdd install --portable` and a "Pilot baseline" section with the recorded count.
- [ ] Also run (acceptance, not a registered runner): `parrot sdd techwiki check --spec sdd/specs/procedural-graph-plane.spec.md --root .`

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_docs_present.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check every `Depends-on` task is `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Document the implemented code; if the code and the spec differ, document the code and say so in the Completion Note.
4. Implement only the files listed above; complete every `FILL IN`.
5. Run the Validation Commands and the acceptance check.
6. Commit, then close with `parrot sdd task close TASK-5652 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note


- Task: TASK-5652
- Feature: procedural-graph-plane
- Implementation SHA: e95afcb29bb25de4bd5e95aa34e1622752392cc6
- Closed at (UTC): 2026-11-13T23:23:15+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 510.1s · Tokens: n/a |
