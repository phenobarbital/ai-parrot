# TASK-5182: `CLAUDE.md` and human docs name the new default

**Feature**: FEAT-802 — Worktree Root Under `.parrot/`
**Spec**: `sdd/specs/worktree-root-under-parrot.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5175
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (docs half) and G5. `CLAUDE.md` (always loaded) and the human guides still say worktrees live under `.claude/worktrees/`; `docs/sdd/CODEX.md:160` and `docs/sdd/ANTIGRAVITY.md:97` even justify the location "for compatibility" — that rationale is now false and must go. Historical documents (`sdd/specs/*`, `sdd/tasks/completed/*`, `docs/superpowers/*`) are NOT rewritten (spec Non-Goals).

---

## Scope

- Rewrite every `.claude/worktrees` occurrence in the files below (26 lines at `/sdd-task` time) by the rules R1-R6.
- `docs/install/global-runtime.md:245` and `docs/getting-started.md:434`: the installer's ignore block now covers the resolved in-repository worktree root (and `.parrot/`); mention that `parrot sdd install`/`parrot doctor` refuse while worktrees remain under the legacy `.claude/worktrees/` and print the migration recipe.
- `docs/sdd/CODEX.md:160`, `docs/sdd/ANTIGRAVITY.md:97`: replace the compatibility rationale with "host-agnostic, under `.parrot/`".
- `docs/dev_loop/sdd-compaction-capabilities.md:68` is a historical measurement row naming a real path — rewrite to the default path only if it reads as current guidance; otherwise leave it and record why (AC1's grep does not cover `docs/`).

**NOT in scope**: `sdd/WORKFLOW.md` and `docs/sdd/WORKFLOW.md` (no hits at `/sdd-task` time — re-check and handle any that appear); rule/command/agent files (TASK-5180, TASK-5181).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `CLAUDE.md` | MODIFY | 2 legacy-root line(s) |
| `docs/sdd/GUIDE.md` | MODIFY | 6 legacy-root line(s) |
| `docs/sdd/PLATFORM.md` | MODIFY | 3 legacy-root line(s) |
| `docs/sdd/CODEX.md` | MODIFY | 6 legacy-root line(s) |
| `docs/sdd/ANTIGRAVITY.md` | MODIFY | 2 legacy-root line(s) |
| `docs/getting-started.md` | MODIFY | 1 legacy-root line(s) |
| `docs/install/global-runtime.md` | MODIFY | 1 legacy-root line(s) |
| `docs/dev_loop/claude-native-sandbox.md` | MODIFY | 2 legacy-root line(s) |
| `docs/dev_loop/sdd-compaction-capabilities.md` | MODIFY | 1 legacy-root line(s) |
| `docs/clients/meta.md` | MODIFY | 1 legacy-root line(s) |
| `docs/clients/openai-compatible.md` | MODIFY | 1 legacy-root line(s) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Interfaces
```bash
parrot sdd worktree root --root "$MAIN_ROOT"     # TASK-5175 — prints one absolute path; exit 0
parrot sdd worktree ensure --slug <slug> --feature-id FEAT-<NNN>   # prints the worktree path (ensure_worktree.py main)
parrot sdd worktree status                        # lists legacy entries as flow_type "legacy" after TASK-5177
parrot doctor                                     # prints the migration recipe in the "sdd: legacy worktrees" fix (TASK-5179)
MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)   # verified: .claude/commands/sdd-done.md:80
```

### Does NOT Exist
- ~~`parrot sdd worktree migrate`~~ / ~~`git worktree move` wrapper~~ — out of scope by decision; users run the printed recipe.
- ~~`parrot sdd worktree root` without `--root`~~ — the flag is required.
- ~~a dual-root lookup~~ — never tell an agent to "check both `.parrot/worktrees` and `.claude/worktrees`".

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "CLAUDE.md", "action": "MODIFY"},
    {"path": "docs/sdd/GUIDE.md", "action": "MODIFY"},
    {"path": "docs/sdd/PLATFORM.md", "action": "MODIFY"},
    {"path": "docs/sdd/CODEX.md", "action": "MODIFY"},
    {"path": "docs/sdd/ANTIGRAVITY.md", "action": "MODIFY"},
    {"path": "docs/getting-started.md", "action": "MODIFY"},
    {"path": "docs/install/global-runtime.md", "action": "MODIFY"},
    {"path": "docs/dev_loop/claude-native-sandbox.md", "action": "MODIFY"},
    {"path": "docs/dev_loop/sdd-compaction-capabilities.md", "action": "MODIFY"},
    {"path": "docs/clients/meta.md", "action": "MODIFY"},
    {"path": "docs/clients/openai-compatible.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Rewrite rules (identical across TASK-5180, TASK-5181, TASK-5182)

| Rule | Where it applies | Rewrite |
|---|---|---|
| R1 prose | a sentence that says where worktrees live | "under the worktree root (default `.parrot/worktrees/`, override with an exported `WORKTREE_BASE_PATH`)" — shorten to "the worktree root" after the first mention in a file |
| R2 operational snippet | a shell line that builds, `cd`s into, removes or tests a worktree path | resolve first: `MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)` then `WORKTREES_DIR=$(parrot sdd worktree root --root "$MAIN_ROOT") \|\| exit $?`; use `"$WORKTREES_DIR/<name>"` with the quotes kept |
| R3 creation snippet | `git worktree add -b X .claude/worktrees/X HEAD` | replace with the documented creator: `parrot sdd worktree ensure --slug <slug> --feature-id FEAT-<NNN>` (prints the path); hand-built `git worktree add` contradicts the worktree rule |
| R4 illustrative output / JSON | `Worktree: .claude/worktrees/x`, `"worktree_path": "/abs/.claude/worktrees/..."` | show the default: `.parrot/worktrees/x`, `/abs/.parrot/worktrees/...` |
| R5 "am I in a worktree" check | "refuse if inside `.claude/worktrees/`" | "refuse if `git rev-parse --git-dir` differs from `--git-common-dir` (a linked worktree)" — location-independent |
| R6 migration text | ONLY the worktree-management rule and its twin | one paragraph telling users with worktrees under the legacy `.claude/worktrees/` to run the recipe `parrot doctor` prints; every line that names `.claude/worktrees` must also contain `git worktree repair` (the TASK-5183 guard test allows exactly those lines) |

Never substitute another fixed path for `.claude/worktrees` in an operational snippet: a fixed `.parrot/worktrees` would ignore `WORKTREE_BASE_PATH` (spec §6 note under Edit Sites).


### Edit sites (verified at `/sdd-task` time; re-grep before editing)

| File | Line | Current text (verbatim, truncated at 110 chars) | Rule |
|---|---|---|---|
| `CLAUDE.md` | 172 | `Everything about worktrees — location (`.claude/worktrees/`), naming,` | R1 |
| `CLAUDE.md` | 228 | `cd .claude/worktrees/feat-FEAT-<NNN>-<slug>` | R2 |
| `docs/sdd/GUIDE.md` | 61 | `cd .claude/worktrees/feat-<ID>-<slug>` | R2 |
| `docs/sdd/GUIDE.md` | 206 | ``git worktree add -b feat-<ID>-<slug> .claude/worktrees/feat-<ID>-<slug> HEAD`` | R3 |
| `docs/sdd/GUIDE.md` | 247 | `cd .claude/worktrees/feat-147-crew-result-storage` | R2 |
| `docs/sdd/GUIDE.md` | 341 | `cd .claude/worktrees/feat-150-agent-tracing` | R2 |
| `docs/sdd/GUIDE.md` | 372 | `cd .claude/worktrees/feat-NNN-<slug>` | R2 |
| `docs/sdd/GUIDE.md` | 388 | `cd .claude/worktrees/feat-NNN-fix-pgvector-deadlock` | R2 |
| `docs/sdd/PLATFORM.md` | 179 | ``git worktree add -b feat-<FEAT-ID>-<slug> .claude/worktrees/feat-<FEAT-ID>-<slug> HEAD`.` | R3 |
| `docs/sdd/PLATFORM.md` | 343 | `│ cd .claude/worktrees/feat-071-<slug>                                      │` | R2 |
| `docs/sdd/PLATFORM.md` | 373 | `index + task files, creates `.claude/worktrees/feat-071-<slug>`.` | R1 |
| `docs/sdd/CODEX.md` | 148 | `cd .claude/worktrees/<feature-worktree>` | R2 |
| `docs/sdd/CODEX.md` | 160 | `The worktree directory is still `.claude/worktrees/` for compatibility with the` | R1 |
| `docs/sdd/CODEX.md` | 277 | `7. Creates the feature worktree under `.claude/worktrees/`.` | R1 |
| `docs/sdd/CODEX.md` | 292 | `cd .claude/worktrees/feat-<FEAT-ID>-<feature-slug>` | R2 |
| `docs/sdd/CODEX.md` | 392 | `\| Worktrees \| `.claude/worktrees/<branch-name>/` \|` | R1 |
| `docs/sdd/CODEX.md` | 421 | `cd .claude/worktrees/feat-<FEAT-ID>-nav-8036-<slug>` | R2 |
| `docs/sdd/ANTIGRAVITY.md` | 77 | `cd .claude/worktrees/<feature-worktree>` | R2 |
| `docs/sdd/ANTIGRAVITY.md` | 97 | `- **Worktree Isolation**: Worktrees live under `.claude/worktrees/` for cross-tool compatibility.` | R4 |
| `docs/getting-started.md` | 434 | ``sdd/tasks/.id_ledger.json`, an ignore block for `.claude/worktrees/` and `.parrot/`, a marked `.gitattributes` | R1 |
| `docs/install/global-runtime.md` | 245 | `- It also seeds `sdd/tasks/.id_ledger.json` and an ignore block for `.claude/worktrees/` and `.parrot/` (parro` | R1 |
| `docs/dev_loop/claude-native-sandbox.md` | 13 | `directory, the primary checkout's `.claude/worktrees/` and `.parrot/ledger/`, and the per-user` | R1 |
| `docs/dev_loop/claude-native-sandbox.md` | 201 | `under the primary checkout's `.claude/worktrees/` remains possible.` | R1 |
| `docs/dev_loop/sdd-compaction-capabilities.md` | 68 | `\| This worktree (`.claude/worktrees/feat-FEAT-584-.../TASK-3555-a1-...`) \| `false` \| `false` \| `true` (from `T` | R1 |
| `docs/clients/meta.md` | 257 | ``.claude/worktrees/<feature>/` will silently import the **main**` | R1 |
| `docs/clients/openai-compatible.md` | 344 | `from inside a `.claude/worktrees/<feature>/` checkout, `cd`-ing there is not` | R1 |

The Rule column is a first guess from the line's shape; read each line's surrounding block and apply the
rule that fits (an R1 line inside a fenced shell block is R2).

---

## Implementation Blueprint

### Steps (in order)
1. For each file, open it, re-grep, and classify every hit by R1-R6 — *why*: line numbers drift and the rule depends on context.
2. Where a file has an operational shell block, add the two-line root resolution ONCE at the top of that block and reuse `$WORKTREES_DIR` — *why*: AC9, effective root honours `WORKTREE_BASE_PATH`.
3. Apply R1/R4/R5 text edits — *why*: prose must name the new default (G5).

4. Verify with `grep -rn 'claude/worktrees' <files>` — only R6 lines (containing `git worktree repair`) may remain.

### FILL IN checklist
- [ ] every row of the Edit-sites table resolved (record any re-classification in the Completion Note).
- [ ] no operational snippet names a fixed worktree directory.

---

## Acceptance Criteria

- [ ] `grep -n 'claude/worktrees' CLAUDE.md` returns nothing.
- [ ] The listed docs name `.parrot/worktrees/` as the default and `WORKTREE_BASE_PATH` as the override; no doc claims `.claude/worktrees/` is kept for compatibility.
- [ ] Install docs describe the legacy refusal and point at the recipe `parrot doctor` prints.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Agent Instructions

1. Work in the feature worktree; TASK-5175 must be `done` (the `parrot sdd worktree root` verb exists).
2. Re-run `grep -n 'claude/worktrees' <file>` for every file before editing: the table was verified at
   `/sdd-task` time and line numbers may have moved; a vanished line is fine, a NEW one must be handled by the same rules.
3. Mark `in-progress`, edit, run the Validation Commands with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
4. Do NOT run `scripts/sdd/check_asset_sync.py --write` here — TASK-5183 regenerates `_assets/` once, after all prose tasks.
5. Commit only the listed files (`git add -f` for `.claude/`/`.agent/`/`.agents/` paths if a plain add refuses);
   `parrot sdd task close TASK-5182 worktree-root-under-parrot verified`; fill the Completion Note.

---

## Completion Note

Implemented by seat gemini-3.8-flash (google-compat), 1 attempt, merged cleanly.

**Completed by**: sdd-worker (orchestrator)
**Date**: 2026-11-05
**Notes**: Merge-tier: 171 passed, 1 pre-existing failure (test_no_command_hand_rolls_a_worktree[sdd-worker.md], also red on origin/dev). Closed via `parrot sdd task close`; finalize unavailable (coder_record_review tool error). Final cross-check of residual `.claude/worktrees` references is TASK-5183's guard test. feedback NOT recorded.

**Deviations from spec**:
