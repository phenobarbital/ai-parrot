# TASK-999: Rewrite `/sdd-done` for flow-type awareness + main-PR enforcement

**Feature**: FEAT-145 — SDD Flow Types and Per-Spec Index
**Spec**: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-994
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of FEAT-145. `/sdd-done` is the closing
command — the place where flow type matters most:

- For `type: feature`: behave as today, merging into the spec's
  `base_branch` (defaults to `dev`). Never touch `main`.
- For `type: hotfix`: NEVER push to `main` and NEVER open a PR
  against `main` automatically. Push the hotfix branch and emit a
  `gh pr create --base main` snippet for the user to run manually.
- For `type: hotfix` (post-merge): keep `dev` in sync via optimistic
  auto-merge. On conflict: `git merge --abort` and emit an actionable
  message. (Decision 4c.)

---

## Scope

Edit `.claude/commands/sdd-done.md`. Keep the verification report,
worktree-evidence collection, and Jira-transition logic intact —
those are orthogonal to flow type.

Replace / add sections:

1. **§1 Verify We're on `dev`** → **§1 Verify We're on the Base Branch**: read the spec's frontmatter, derive `BASE_BRANCH`, refuse if not on it. For hotfix: also verify HEAD is `main`.

2. **§7 Close Tasks**: keep the existing logic but replace the index path with `sdd/tasks/index/<feature>.json`. The merge step `git merge feat-<FEAT-ID>-<slug>` runs against `BASE_BRANCH` (not hardcoded `dev`).

3. **§8 Push the Feature Branch**: unchanged.

4. **§9 Merge Feature Branch into Base** (rewrite to be flow-aware):
   - For `type: feature`: `git checkout $BASE_BRANCH && git merge --no-edit feat-<...>` then `git push origin $BASE_BRANCH`. Reject if `BASE_BRANCH == "main"`.
   - For `type: hotfix`: do NOT merge. Print a manual-PR reminder:
     ```
     ⚠️ Hotfix merging into `main` MUST go through a PR.
        Open it manually:

          gh pr create --base main --head <hotfix-branch> \
            --title "<hotfix title>" --body "<verification summary>"

        After the PR merges, re-run /sdd-done --sync-dev to
        propagate the change to dev.
     ```
   - **Refuse, with a hard error, any push to `main` or any PR creation against `main`** regardless of flags. The enforcement is independent of flow type.

5. **§9.5 Hotfix → Dev Sync** (NEW section, runs only for `type: hotfix` with `--sync-dev` or after the user confirms the PR merged):
   - `git fetch origin`
   - Verify the hotfix is now an ancestor of `origin/main`:
     `git merge-base --is-ancestor <hotfix-branch> origin/main || ABORT`
   - `git checkout dev && git pull --ff-only origin dev`
   - Optimistic merge: `git merge --no-edit <hotfix-branch>`
   - On success: `git push origin dev`. Print: `✅ dev synced with hotfix-<slug>`.
   - On conflict: `git merge --abort` and print:
     ```
     ⚠️  Conflict syncing hotfix into dev. The merge has been aborted.
        Resolve manually:
          git checkout dev
          git merge <hotfix-branch>
          # ...resolve conflicts...
          git push origin dev
     ```

6. **Cardinal enforcement (NEW, applies everywhere)**: at the very top of the command's "Steps" section, add a CRITICAL block:
   ```markdown
   > **CRITICAL — `/sdd-done` NEVER pushes to `main` and NEVER opens a PR against `main`.**
   > Hotfixes go to `main` ONLY via a manually-opened PR. This rule is non-negotiable
   > and applies to every flag combination.
   ```

**NOT in scope**:
- The Jira transition logic in §10 (kept verbatim — `--resolve-jira` works the same way).
- The cleanup logic in §11 (kept verbatim).
- Implementing a `--sync-dev` flag parser; documenting the flag is enough — the agent uses git directly.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Sections §1, §7, §9; new §9.5; new cardinal block |

---

## Codebase Contract (Anti-Hallucination)

### Existing File to Modify (verified line counts on 2026-05-05)

`.claude/commands/sdd-done.md` — 355 lines:
- Header / Usage / Guardrails: lines 1–30
- §1 "Verify We're on `dev`": lines 33–43
- §7 "Close Tasks": lines 137–161
- §8 "Push the Feature Branch": lines 163–168
- §9 "Merge Feature Branch into `dev`": lines 169–197
- §10 "Transition Jira Ticket": lines 199–300
- §11 "Cleanup the Worktree": lines 302–319
- §12 "Output": lines 321–349

### Frontmatter Read Pattern (same as TASK-997, TASK-998)

```bash
META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")
TYPE=$(echo "$META" | awk '{print $1}')
BASE_BRANCH=$(echo "$META" | awk '{print $2}')
```

### Existing Pattern Reference (line 177 — to be replaced)

```bash
git merge feat-<FEAT-ID>-<slug> --no-edit
```

becomes:

```bash
if [[ "$BASE_BRANCH" == "main" ]]; then
    echo "REFUSED: /sdd-done never merges into main directly. Open a PR manually."
    exit 1
fi
git merge --no-edit feat-<FEAT-ID>-<slug>
git push origin "$BASE_BRANCH"
```

### Does NOT Exist

- ~~A `--sync-dev` flag parser today~~ — documented as new flag in this task; user passes it explicitly.
- ~~A `gh pr create --base main` call inside `/sdd-done`~~ — must NOT be added; the user runs it manually.
- ~~Any auto-PR-to-main logic~~ — explicitly forbidden.

---

## Implementation Notes

### Cardinal block placement

Insert immediately before the "## Steps" heading. Use a `>` blockquote
so it visually stands out.

### Refusal logic

The "REFUSED" abort messages should use exit code 1 (or the markdown
equivalent: `STOP and emit the message verbatim`). For markdown
commands, the convention in the existing files is to write `STOP and
print:`.

### Backwards compatibility

If the spec has no frontmatter (legacy spec), `parse()` returns
`feature/dev` defaults. `/sdd-done` then behaves like the old version
(merge into dev). This means legacy in-flight features keep working.

### Key Constraints

- Markdown-only edit. No code shipped here.
- Must NOT remove the §10 Jira-transition logic.
- Must NOT remove the verification report (§5–§6).

---

## Acceptance Criteria

- [ ] The cardinal block "NEVER pushes to main / NEVER opens PR against main" appears at the top of the Steps section.
- [ ] §1 reads `BASE_BRANCH` from the spec's frontmatter (no hardcoded `dev`).
- [ ] §7 references `sdd/tasks/index/<feature>.json` instead of `sdd/tasks/.index.json`.
- [ ] §9 has an explicit `if BASE_BRANCH == "main": refuse` guard.
- [ ] §9.5 (hotfix dev-sync) exists with the optimistic-merge / safe-abort flow.
- [ ] `gh pr create --base main` snippet is shown to the user, but the command never executes it.
- [ ] `grep -c "git push origin main\|--base main" .claude/commands/sdd-done.md` shows the snippet appears only in the "instructions to the user" context, never in an executable command block.
- [ ] No remaining references to `sdd/tasks/.index.json` in the file.

---

## Test Specification

Verification via grep + manual review:

```bash
grep -n "NEVER pushes to .main\|NEVER opens" .claude/commands/sdd-done.md  # ≥ 1
grep -n "BASE_BRANCH\|base_branch" .claude/commands/sdd-done.md             # ≥ 1
grep -n "sdd/tasks/index/" .claude/commands/sdd-done.md                     # ≥ 1
grep -nE "git checkout dev[^\-]" .claude/commands/sdd-done.md               # 0 (no hardcoded dev checkouts)
grep -n "merge --abort" .claude/commands/sdd-done.md                        # ≥ 1 (in §9.5)
grep -n "merge-base --is-ancestor" .claude/commands/sdd-done.md             # ≥ 1
grep -n "sdd/tasks/.index.json" .claude/commands/sdd-done.md                # 0
```

All counts must match.

---

## Agent Instructions

1. Read `.claude/commands/sdd-done.md` end-to-end.
2. Use surgical `Edit` calls. The file is 355 lines and has a lot of
   value beyond the changes — do not rewrite wholesale.
3. After all edits, run the grep verifications.
4. Commit: `feat(sdd): TASK-999 — sdd-done flow-aware + main-PR enforcement`.

---

## Completion Note

*(Agent fills this in when done)*
