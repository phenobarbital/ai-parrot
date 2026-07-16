---
type: Wiki Overview
title: 'TASK-996: Add YAML frontmatter to SDD templates'
id: doc:sdd-tasks-completed-task-996-sdd-templates-frontmatter-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of FEAT-145. Templates are the first thing
---

# TASK-996: Add YAML frontmatter to SDD templates

**Feature**: FEAT-145 — SDD Flow Types and Per-Spec Index
**Spec**: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of FEAT-145. Templates are the first thing
generation commands read. Adding the frontmatter block here means new
brainstorm/proposal/spec docs are born with a placeholder ready for
the user to set, and `scripts.sdd.sdd_meta.parse()` (TASK-994) will
read it directly.

---

## Scope

- Prepend a YAML frontmatter block at the very top of each template:
  - `sdd/templates/spec.md`
  - `sdd/templates/brainstorm.md`
  - `sdd/templates/proposal.md`
- The frontmatter block must contain `type` and `base_branch` placeholders, plus a one-line comment instructing the user how to fill them in.
- Do NOT remove any existing content from the templates — frontmatter is purely additive.

**NOT in scope**:
- Retrofitting existing spec/brainstorm/proposal documents (they default to feature/dev via `sdd_meta.parse()` and remain valid as-is).
- Updating commands to emit frontmatter (TASK-997).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/spec.md` | MODIFY | Prepend frontmatter block |
| `sdd/templates/brainstorm.md` | MODIFY | Prepend frontmatter block |
| `sdd/templates/proposal.md` | MODIFY | Prepend frontmatter block |

---

## Codebase Contract (Anti-Hallucination)

### Existing Files to Modify (verified)

- `sdd/templates/spec.md` (188 lines, starts with `# Feature Specification: <Feature Name>`).
- `sdd/templates/brainstorm.md` — exists; verify before editing.
- `sdd/templates/proposal.md` — exists; verify before editing.

### Frontmatter Block to Prepend

```markdown
---
# SDD flow type and base branch.
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

```

(Trailing blank line is intentional — separates frontmatter from the existing markdown heading.)

### Does NOT Exist

- ~~Existing frontmatter on these templates~~ — verified absent (templates start directly with markdown headings).

---

## Implementation Notes

### Order of edits

1. `sdd/templates/spec.md`: prepend block before line 1 (`# Feature Specification: <Feature Name>`).
2. `sdd/templates/brainstorm.md`: prepend block before the first heading.
3. `sdd/templates/proposal.md`: same.

### Sanity check

After editing, run:

```bash
head -8 sdd/templates/spec.md
head -8 sdd/templates/brainstorm.md
head -8 sdd/templates/proposal.md
```

Each should show the frontmatter block followed by the existing first heading.

### Key Constraints

- Pure markdown edits. No code logic.
- No removal of existing template content.

---

## Acceptance Criteria

- [ ] All three template files start with the frontmatter block.
- [ ] Existing template body is preserved byte-for-byte (after the prepended block).
- [ ] `python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; print(parse(Path('sdd/templates/spec.md')))"` returns `FlowMeta(type='feature', base_branch='dev')` (sanity check that the inserted block is parseable).

---

## Test Specification

Manual / scripted verification:

```bash
source .venv/bin/activate
for f in sdd/templates/{spec,brainstorm,proposal}.md; do
    python -c "
from pathlib import Path
from scripts.sdd.sdd_meta import parse
m = parse(Path('$f'))
assert m.type == 'feature' and m.base_branch == 'dev', '$f'
print('OK', '$f')
"
done
```

---

## Agent Instructions

1. Read each template to find line 1.
2. Prepend the frontmatter block via Edit (use the existing first line as the unique anchor for the insert).
3. Run the sanity check above.
4. Commit: `feat(sdd): TASK-996 — frontmatter on SDD templates`.

---

## Completion Note

**Completed by**: Claude (Opus 4.7) — interactive session via `/sdd-start TASK-996`
**Date**: 2026-05-05
**Notes**: Prepended an 8-line YAML frontmatter block (`type: feature`, `base_branch: dev`, with inline guidance comment) to the three templates. Sanity-checked all three with `scripts.sdd.sdd_meta.parse()` — each parses to `FlowMeta(type='feature', base_branch='dev')`.

**Files modified** (exactly as scoped):
- `sdd/templates/spec.md`
- `sdd/templates/brainstorm.md`
- `sdd/templates/proposal.md`

**Heads-up for downstream tasks**: the worktree's `.gitignore` has a global `templates/` rule (line 245) that masks any future new template files. The three templates above were already tracked before that rule landed, so the edit committed cleanly — but TASK-1002 (docs) might want to flag this as a follow-up if new templates are ever added under `sdd/templates/`.

**Deviations from contract**: none.
