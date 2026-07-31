---
type: Wiki Overview
title: 'TASK-997: Wire frontmatter into generation commands'
id: doc:sdd-tasks-completed-task-997-frontmatter-in-generation-commands-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4** of FEAT-145. Generation commands are the
---

# TASK-997: Wire frontmatter into generation commands

**Feature**: FEAT-145 — SDD Flow Types and Per-Spec Index
**Spec**: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-994, TASK-996
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of FEAT-145. Generation commands are the
authoring surface — the place where flow type is decided. They must
ask once (in `sdd-brainstorm` / `sdd-proposal`) and propagate the
choice into every downstream document via the YAML frontmatter block
delivered by TASK-996.

`/sdd-spec` additionally must pull the base branch before scaffolding
so the local working copy is up-to-date with `origin`.

---

## Scope

Edit the four generation command files (markdown instructions only — no Python):

1. **`.claude/commands/sdd-brainstorm.md`**: during the Interactive Discovery rounds, ask the user "Is this a `feature` or a `hotfix`?". Default to `feature` if not asked. Emit the frontmatter block at the top of the generated brainstorm doc. For `hotfix`, set `base_branch: main`.
2. **`.claude/commands/sdd-proposal.md`**: same pattern as brainstorm. The user answer flows through to the auto-generated spec.
3. **`.claude/commands/sdd-spec.md`**:
   - Read the brainstorm's frontmatter via `python -m scripts.sdd.sdd_meta` (or by direct YAML parsing in shell). Carry `type` and `base_branch` forward verbatim into the generated spec's frontmatter.
   - Before scaffolding (new sub-step in §1 or before §4 codebase research): run `git checkout <base_branch> && git pull --ff-only origin <base_branch>`. If the working tree is dirty, abort with a clear message — do NOT stash. If `--ff-only` fails, abort and instruct the user to reconcile manually.
   - For `type: hotfix`, validate `base_branch == "main"` and refuse otherwise.
4. **`.claude/commands/sdd-fromjira.md`**: emit frontmatter (default `feature`/`dev`) on the generated brainstorm; instruct the user to flip to `hotfix` if the Jira issue is tagged as such.

**NOT in scope**:
- The per-spec index file or any task-stage logic (TASK-998+).
- `/sdd-tojira` (no change needed for now — additive metadata only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-brainstorm.md` | MODIFY | Add type-question to discovery; emit frontmatter |
| `.claude/commands/sdd-proposal.md` | MODIFY | Add type-question; emit frontmatter |
| `.claude/commands/sdd-spec.md` | MODIFY | Read brainstorm frontmatter; pull base; emit frontmatter |
| `.claude/commands/sdd-fromjira.md` | MODIFY | Emit default frontmatter on generated brainstorm |

---

## Codebase Contract (Anti-Hallucination)

### Existing Files to Modify (verified line counts on 2026-05-05)

- `.claude/commands/sdd-spec.md` — 248 lines. Section §1 "Parse Input" at line 22; §6 "Commit the Spec" at line 192.
- `.claude/commands/sdd-brainstorm.md` — exists; "Interactive Discovery" step (mandatory ≥ 2 rounds) is described in §3.
- `.claude/commands/sdd-proposal.md` — exists; "Discuss and Clarify" step in §3.
- `.claude/commands/sdd-fromjira.md` — exists; verify before editing.

### Frontmatter Block (from TASK-996, must match exactly)

```markdown
---
type: feature
base_branch: dev
---

```

For hotfix:

```markdown
---
type: hotfix
base_branch: main
---

```

### Pull Base Branch (insert in `/sdd-spec` before §2 or §4)

Section to insert into `/sdd-spec` (immediately after §1 "Parse Input"):

```markdown
### 1.5 Sync the Base Branch

Before scaffolding, sync the local base branch with `origin`. The base
is `dev` by default, or whatever the brainstorm's frontmatter declares.
For `type: hotfix`, base MUST be `main`.

```bash
git checkout <base_branch>
git pull --ff-only origin <base_branch>
```

If the working tree is dirty, abort with:
```
⚠️  Cannot sync <base_branch>: working tree has uncommitted changes.
   Stash or commit first, then re-run /sdd-spec.
```

If `--ff-only` fails, abort with:
```
⚠️  Cannot fast-forward <base_branch>. Reconcile manually
   (git pull --rebase or merge), then re-run /sdd-spec.
```
```

### Does NOT Exist

- ~~`scripts.sdd.sdd_meta` as a CLI~~ — TASK-994 only delivers it as a library. Commands invoke it via `python -c "..."` snippets, not `python -m`.
- ~~Any existing pull-base-branch step in `/sdd-spec`~~ — verified absent (current §1 jumps to "Check for Prior Exploration").

---

## Implementation Notes

### Pattern for asking the type in brainstorm/proposal

In the discovery section of each command, add a question to the first round of clarifying questions:

```markdown
**Flow type (mandatory):**
- Is this a regular feature (lands on `dev`) or a hotfix (lands on `main`)?
- For `feature`, which base branch? (default: `dev`; can be another feature branch for sub-features)
- For `hotfix`, base is fixed to `main`.
```

### Pattern for emitting frontmatter

When the brainstorm/proposal/spec file is created, the very first line written must be `---\ntype: <chosen>\nbase_branch: <chosen>\n---\n` followed by the existing template body.

### Pattern for `/sdd-spec` carrying frontmatter forward

In §2 (Check for Prior Exploration), after loading the brainstorm:

```bash
META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<brainstorm-path>')); print(m.type, m.base_branch)")
TYPE=$(echo "$META" | awk '{print $1}')
BASE_BRANCH=$(echo "$META" | awk '{print $2}')
```

Then carry these forward into the spec's frontmatter.

### Key Constraints

- All edits are markdown — no Python or shell scripts to ship beyond inline snippets in the command docs.
- Backwards compatibility: brainstorms without frontmatter MUST still work via `parse()` defaults (verified in TASK-994).

---

## Acceptance Criteria

- [ ] All four command files include explicit instructions for asking and emitting frontmatter.
- [ ] `/sdd-spec` documents the base-branch sync sub-step with the dirty-tree and FF-fail abort messages.
- [ ] `/sdd-spec` documents the `type: hotfix ⇒ base_branch == main` validation.
- [ ] `/sdd-fromjira` emits a default `feature`/`dev` frontmatter on its generated brainstorm.
- [ ] No existing instructions are removed (additive edits only, except where the spec explicitly says to replace, e.g. the §1 "Verify Branch" block in `/sdd-task` which is TASK-998's job — NOT this task).

---

## Test Specification

Manual exercise after implementation:

```bash
# Dry-run mental walkthrough:
# 1. Read each modified command file end-to-end.
# 2. Verify the frontmatter ask-and-emit pattern is present.
# 3. Verify /sdd-spec includes the §1.5 base-branch sync block.
# 4. Read .claude/commands/sdd-spec.md and grep for "git pull --ff-only".
```

```bash
grep -n "type: feature\|type: hotfix\|--ff-only\|base_branch" .claude/commands/sdd-{brainstorm,proposal,spec,fromjira}.md
```

Expected: at least one match per file for `type: feature` (placeholder) and one match in `sdd-spec.md` for `--ff-only`.

---

## Agent Instructions

1. Read each command file fully before editing.
2. Use `Edit` tool with unique string anchors for each insert. Do NOT rewrite files wholesale.
3. After all four files are edited, run the grep verification.
4. Commit: `feat(sdd): TASK-997 — wire frontmatter into generation commands`.

---

## Completion Note

**Completed by**: Claude (Opus 4.7) — interactive session via `/sdd-start TASK-997`
**Date**: 2026-05-05
**Notes**: Markdown-only edits to all four generation commands. All grep acceptance checks pass.

**What landed per file:**
- **`sdd-brainstorm.md`**: new `Round 0 — Flow type` block in §3 (asks two questions before Round 1, with default `feature`/`dev`); §10 step 2 now instructs the agent to update — not strip — the template's frontmatter from the user's Round 0 answers.
- **`sdd-proposal.md`**: new `Flow type (always ask first)` block at the top of §3; §2 step 2 now mentions preserving the template frontmatter.
- **`sdd-spec.md`**: new `§2d Sync the Base Branch` (after §2c, before §3 clarifying questions). Reads frontmatter via `python -c "from scripts.sdd.sdd_meta import parse; ..."`, validates `type: hotfix ⇒ base_branch == "main"`, runs `git checkout <BASE> && git pull --ff-only origin <BASE>` with documented dirty-tree and FF-fail abort messages. §5 step 2 now requires writing the literal `type:`/`base_branch:` frontmatter at the top of the spec, with an inline YAML example.
- **`sdd-fromjira.md`**: existing Jira-metadata frontmatter block in §12 step 3 now also includes `type: feature` and `base_branch: dev` (plus a comment guiding the user to flip to `hotfix`/`main` for hotfix-tagged issues).

**Acceptance grep results:**
- `type: feature|hotfix` references — sdd-brainstorm: 3, sdd-proposal: 2, sdd-spec: 1, sdd-fromjira: 2 (all ≥ 1 as required).
- `--ff-only` in sdd-spec: 2 (≥ 1 required).
- `base_branch` in sdd-spec: 3 (≥ 1 required).

**Deviations from contract**: none.

**Heads-up for downstream tasks**: TASK-998 (`/sdd-task` rewrite) will rely on the spec frontmatter that this task ensures is now written. The contract chain holds.
