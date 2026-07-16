---
type: Wiki Overview
title: 'TASK-1002: Update `sdd/WORKFLOW.md` and `CLAUDE.md` for the new flow model'
id: doc:sdd-tasks-completed-task-1002-update-sdd-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 9** of FEAT-145. Documentation closes the loop —
---

# TASK-1002: Update `sdd/WORKFLOW.md` and `CLAUDE.md` for the new flow model

**Feature**: FEAT-145 — SDD Flow Types and Per-Spec Index
**Spec**: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-994, TASK-995, TASK-996, TASK-997, TASK-998, TASK-999, TASK-1000, TASK-1001
**Assigned-to**: unassigned

---

## Context

Implements **Module 9** of FEAT-145. Documentation closes the loop —
without it, future contributors and Claude sessions will re-introduce
the old assumptions (monolithic index, dev-only flow). This task is
last so it documents what was actually built, not what was planned.

---

## Scope

### `sdd/WORKFLOW.md`

- Replace the current "Task Index Schema" section with the per-spec schema documented in the spec §2 Data Models.
- Add a new "Flow Types" section explaining `feature` vs `hotfix` and the frontmatter convention.
- Update the "Phase 2 — Task Generation" wording to reference `sdd/tasks/index/<feature>.json` instead of `sdd/tasks/.index.json`.
- Add a "Migration" note pointing at `scripts/sdd/migrate_index.py` for historical context.

### `CLAUDE.md`

- In the "SDD Workflow & Worktree Policy" section: replace the "Worktrees branch from: the CURRENT branch (`HEAD`), never hardcoded to `main`" wording with the flow-type-aware version (hotfix → main, feature → base_branch from frontmatter).
- Update the Auto-Commit Rule table:
  - `/sdd-task` now commits `sdd/tasks/index/<feature>.json` (not `sdd/tasks/.index.json`).
  - `/sdd-start` now commits the per-spec index in the worktree.
  - `/sdd-done` documents the main-PR enforcement and hotfix dev-sync.
- Update the "Task Index Schema" subsection with the new schema.
- Add a one-paragraph note pointing to `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md` (FEAT-145) as the authoritative reference.

**NOT in scope**:
- Editing `.agent/CONTEXT.md` (already correctly silent on the index — no changes needed).
- Editing `.claude/rules/*.md` (worktree rules are already flow-type agnostic).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/WORKFLOW.md` | MODIFY | Index schema + flow types section + migration note |
| `CLAUDE.md` | MODIFY | Worktree policy + auto-commit table + task index schema |

---

## Codebase Contract (Anti-Hallucination)

### Existing Files to Modify (verified on 2026-05-05)

- `sdd/WORKFLOW.md` exists; "Task Artifact Format" + "Task Index Schema" sections are about midway in the file.
- `CLAUDE.md` exists in the repo root. It contains:
  - `## Project` (header)
  - `## Development Environment` (uv + venv rules)
  - `## Tool-Centric Architecture`
  - `## Async-First Development`
  - `## Integration Patterns`
  - `## Non-Negotiable Rules`
  - `## Key References`
  - `# SDD Workflow & Worktree Policy` (the section that needs editing)
  - `## Git Configuration`
  - `## Worktree Creation`
  - `## SDD Auto-Commit Rule` (table to update)
  - `## Isolation Model`
  - `## Typical Workflow`
  - `## Autonomous Agent (sdd-worker)`
  - `## Task Index Schema` (subsection to update)
  - `### When NOT to Use Worktrees`

### Per-Spec Index Schema (drop into both files)

Use the canonical schema from spec §2 Data Models verbatim.

### Does NOT Exist

- ~~A separate `docs/sdd/flow-types.md` document~~ — not creating one. Documentation lives in WORKFLOW.md and CLAUDE.md to keep authority concentrated.

---

## Implementation Notes

### `sdd/WORKFLOW.md` — Flow Types section to insert

```markdown
## Flow Types (NEW — FEAT-145)

Every brainstorm/proposal/spec declares its flow type via YAML frontmatter:

```yaml
---
type: feature        # or: hotfix
base_branch: dev     # or: main (mandatory for hotfix)
---
```

| Type      | base_branch       | When to use                                          |
|-----------|-------------------|------------------------------------------------------|
| `feature` | `dev` (default)   | Most work. Lands on `dev` via `/sdd-done`.           |
| `feature` | `<other-branch>`  | Sub-features extending another feature branch.       |
| `hotfix`  | `main` (required) | Production hotfixes. Land on `main` via manual PR.   |

`/sdd-done` enforces: hotfixes are NEVER auto-pushed or auto-PR'd to `main`.
The user opens the PR manually; afterwards, `/sdd-done --sync-dev` propagates
the change to `dev`.
```

### `CLAUDE.md` — Auto-Commit Rule table (replace current)

```markdown
| Command | What it commits | Where |
|---|---|---|
| `/sdd-brainstorm` | `sdd/proposals/<n>.brainstorm.md` (with frontmatter) | base_branch |
| `/sdd-proposal`   | `sdd/proposals/<n>.proposal.md` (with frontmatter)  | base_branch |
| `/sdd-spec`       | `sdd/specs/<n>.spec.md` (with frontmatter)          | base_branch |
| `/sdd-task`       | `sdd/tasks/index/<feature>.json` + `sdd/tasks/active/TASK-*` | base_branch |
| `/sdd-start`      | Per-spec index update + implementation code | worktree (feature branch) |
| `/sdd-done`       | Per-spec index final state + task file moves; merges feature → base_branch | base_branch |
```

### Migration note

```markdown
> **Migration history (FEAT-145, 2026-05)**: the monolithic
> `sdd/tasks/.index.json` was split into per-spec files at
> `sdd/tasks/index/<feature>.json` by `scripts/sdd/migrate_index.py`.
> The original monolith is preserved as a historical artifact. New
> tooling reads only per-spec indexes.
```

### Key Constraints

- Pure markdown edits.
- Preserve all sections and rules not directly affected.

---

## Acceptance Criteria

- [ ] `sdd/WORKFLOW.md` references `sdd/tasks/index/<feature>.json`.
- [ ] `sdd/WORKFLOW.md` has a "Flow Types" section.
- [ ] `CLAUDE.md`'s Auto-Commit Rule table reflects the new commit targets.
- [ ] `CLAUDE.md`'s Task Index Schema subsection shows the per-spec schema.
- [ ] Both files reference FEAT-145 / `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md` as the authoritative source.
- [ ] No remaining references to "`sdd/tasks/.index.json`" as the live source of truth in either file (one acceptable mention in the Migration note pointing to the deprecated file is fine).

---

## Test Specification

```bash
grep -c "sdd/tasks/index/" sdd/WORKFLOW.md      # ≥ 2
grep -c "sdd/tasks/index/" CLAUDE.md            # ≥ 2
grep -c "Flow Types\|type: feature\|type: hotfix" sdd/WORKFLOW.md  # ≥ 1
grep -c "FEAT-145" sdd/WORKFLOW.md              # ≥ 1
grep -c "FEAT-145" CLAUDE.md                    # ≥ 1
grep -c "main-PR enforcement\|never auto-pushed\|NEVER pushes" CLAUDE.md  # ≥ 1
```

All counts must match.

---

## Agent Instructions

1. Read `sdd/WORKFLOW.md` and `CLAUDE.md` end-to-end.
2. Apply edits in this order: WORKFLOW.md (Task Index Schema → add Flow Types section → migration note) → CLAUDE.md (Auto-Commit table → Task Index Schema → flow types intro).
3. Run all grep verifications.
4. Commit: `docs(sdd): TASK-1002 — document FEAT-145 per-spec index + flow types`.

---

## Completion Note

**Completed by**: Claude (Opus 4.7) — interactive session via `/sdd-start TASK-1002`
**Date**: 2026-05-05
**Notes**: Final task of FEAT-145. Both docs now describe the new model end-to-end. Future contributors and Claude sessions reading these files will see the per-spec model as the source of truth, with the monolith called out as a historical artifact.

**`sdd/WORKFLOW.md`:**
- §"Phase 2 — Task Generation": rewrote the index reference from `tasks/.index.json` to `sdd/tasks/index/<feature-slug>.json` with FEAT-145 attribution.
- New §"Flow Types (FEAT-145)" section: documents `type: feature | hotfix` + `base_branch` frontmatter, table of when to use each, and the `--sync-dev` flow for hotfixes.
- §"Task Index Schema" replaced with the per-spec schema (header + tasks array, type/base_branch/completed_at fields). Includes the migration history note and pointer to `_orphans.json`.

**`CLAUDE.md`:**
- §"Git Configuration": added flow-types declaration (frontmatter), worktree branch source explanation per flow type, and the explicit `/sdd-done NEVER pushes to main` rule with the `--sync-dev` mention.
- §"SDD Auto-Commit Rule" table: added Where (FEAT-145) column, updated all paths to per-spec; added a note about `/sdd-start` no longer needing the cd dance.
- §"Task Index Schema": replaced with the per-spec schema (header + tasks). Added migration history paragraph and the `.gitignore templates/` heads-up I flagged in TASK-996.

**Acceptance grep results:**
| Check                                  | Value | Required |
|----------------------------------------|-------|----------|
| WORKFLOW.md `sdd/tasks/index/` refs    | 3     | ≥ 2 ✅   |
| WORKFLOW.md `FEAT-145` refs            | 4     | ≥ 1 ✅   |
| WORKFLOW.md Flow Types section         | 2     | ≥ 1 ✅   |
| CLAUDE.md `sdd/tasks/index/` refs      | 3     | ≥ 2 ✅   |
| CLAUDE.md `FEAT-145` refs              | 6     | ≥ 1 ✅   |
| CLAUDE.md NEVER push/PR to main        | 1     | ≥ 1 ✅   |

**Deviations from contract**: none.

**Reconciliation note for the team**: this commit closes FEAT-145 in the worktree. After `/sdd-done FEAT-145` is run on `dev`, the live monolithic `sdd/tasks/.index.json` will still contain the (now stale) duplicate of FEAT-145's tasks. A clean way to reconcile is to re-run `python -m scripts.sdd.migrate_index` from `dev` after the merge — it will overwrite the per-spec index for FEAT-145 with the latest monolith snapshot. From there onwards, any new feature is born in the per-spec model and never touches the monolith.
