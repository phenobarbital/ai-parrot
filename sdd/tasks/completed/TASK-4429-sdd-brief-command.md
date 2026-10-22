# TASK-4429: The `/sdd-brief` command

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4425, TASK-4427, TASK-4428
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 — the heart of the feature. `/sdd-brief <source>` replaces
`/sdd-spec --type hotfix` with a research-first flow: detect and fetch the
source, research to a root cause, ask ≤5 questions, provision the worktree
through `ensure_worktree --brief-key`, then write and commit (inside the
worktree) the brief, the materialized task files, and the per-brief index.
This is a procedure document executed by an agent, so its numbered steps,
exact bash blocks and refusal messages ARE the implementation.

---

## Scope

Create `.claude/commands/sdd-brief.md` with these numbered steps:

1. **Parse input** — usage line
   `/sdd-brief <source> [--base-branch main|dev|staging] [--no-interview] [--split] [--research full|light]`;
   cannot ask ⇒ behave as `--no-interview`.
2. **Detect + fetch the source** — table from spec §2: code-scanning
   (`cs:<n>` or `.../security/code-scanning/<n>` URL →
   `gh api repos/{owner}/{repo}/code-scanning/alerts/<n>`; refuse alerts
   whose `state` is `dismissed` or `fixed`), GitHub issue/PR (`gh issue view`
   / `gh pr view --json`), Jira key (jiratoolkit), ledger id (`issue:<hex>`
   or bare hex → `wikitoolkit ledger show <id>` + `wikitoolkit ledger
   plan-fix --json`), text, file.
3. **Resolve base + identity** — ledger ⇒ `dev` and refuse an explicit
   `--base-branch main` (exact message below); others default `main`.
   KEY = Jira key | ledger short id | slug. Derive the slug.
4. **Ledger claim (ledger sources only, S7)** —
   `wikitoolkit ledger claim <id> --actor agent:sdd-brief` before research;
   every later abort before step 8 must release it
   (`wikitoolkit ledger release <id>` — verify the subcommand name in
   `wikitoolkit ledger --help`; if absent, print the exact manual command).
5. **Research** — wiki-first (`wikitoolkit symbols lookup`, `symbols blast`,
   `wikitoolkit query`), `wikitoolkit ledger context <files>`; `--research
   light` bounds breadth, never the floor.
6. **Research floor (S9)** — STOP before any worktree unless the draft has:
   the fetched source, a root-cause statement, ≥1 verified `path:line`
   anchor (`test -e` + `sed -n` the line).
7. **Q&A** — ≤5 questions, single batch, only for decisions research could
   not settle; `--no-interview` ⇒ record them under `## Assumptions`.
8. **Stage the draft** in `sdd/state/.brief/<slug>-<RUN_ID>/` (git-ignored —
   add the rule to `.gitignore` next to `sdd/state/.intake/`).
9. **Provision the worktree** —
   `python -m scripts.sdd.ensure_worktree --json --slug <slug> --brief-key <KEY> --base-branch <base>`
   (never `git worktree add`; the worktree comes out with no upstream,
   TASK-4426).
10. **Write inside the worktree** — brief from `sdd/templates/brief.md`;
    one task file per fix chunk from `sdd/templates/task.md` at
    `sdd/briefs/<slug>/tasks/HOTFIX-<KEY>-<N>-<task-slug>.md` (`--split` or
    >1 independent chunk ⇒ several); per-brief index via
    `scripts.sdd.brief_meta.write_brief_index`; persist `ledger_issue` in the
    brief frontmatter. Validate the graph:
    `python -m scripts.sdd.check_task_graph <worktree>/sdd/briefs/<slug>.index.json`.
11. **Commit in the worktree** — `git -C <wt> add` the explicit paths only;
    message `sdd: add brief for <KEY> — <slug>`; then
    `git -C <wt> push -u origin <branch>` (setting the upstream to the
    feature branch itself is correct and intended here).
12. **Handoff output** — worktree path, brief path, task ids, next step
    (`cd <wt> && claude --agent sdd-worker --model sonnet --verbose`, or
    manual implementation), then `/sdd-done <KEY>`.

Also:
- Add `".claude/commands/sdd-brief.md": True` to `_CREATORS` in
  `tests/sdd_scripts/test_command_contracts.py` (it provisions worktrees).
- Create `tests/sdd_scripts/test_sdd_brief_command_contract.py`.

**NOT in scope**: the codex twin (TASK-4430); `/sdd-done` changes (TASK-4435);
removing `/sdd-spec --type hotfix` (TASK-4436); dev-loop agents (TASK-4433).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-brief.md` | CREATE | The command procedure |
| `.gitignore` | MODIFY | ignore `sdd/state/.brief/` staging |
| `tests/sdd_scripts/test_command_contracts.py` | MODIFY | register `/sdd-brief` as a worktree creator |
| `tests/sdd_scripts/test_sdd_brief_command_contract.py` | CREATE | contract guards for the command text |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.brief_meta import BriefMeta, emit_brief_frontmatter, brief_task_id, write_brief_index  # TASK-4425
```

### Existing Signatures to Use
```text
python -m scripts.sdd.ensure_worktree --json --slug <s> --brief-key <K> [--base-branch <b>]   # TASK-4427
python -m scripts.sdd.check_task_graph <index.json>                                           # used by /sdd-task §4b
wikitoolkit ledger show <id> | plan-fix --json | claim <id> --actor <a> | context <files…>     # .claude/commands/sdd-fix.md:20,29
gh api repos/{owner}/{repo}/code-scanning/alerts/<n>                                          # GitHub REST
```
```python
# tests/sdd_scripts/test_command_contracts.py
_CREATORS: dict[str, bool] = {      # line 23 (anchor) — file -> must name scripts.sdd.ensure_worktree
    ".claude/commands/sdd-task.md": False,
    ...
}
```
- `.gitignore` anchor: `sdd/state/.intake/` (line 418, occurrences 1).

### Does NOT Exist
- ~~`.claude/commands/sdd-brief.md`~~ — created here.
- ~~`wikitoolkit ledger release`~~ — UNVERIFIED; check `wikitoolkit ledger --help` before writing it into the procedure.
- ~~`sdd/briefs/` in the main checkout~~ — never write there; only inside the worktree.
- ~~`reserve_ids.py` for briefs~~ — briefs reserve nothing.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-brief.md", "action": "CREATE"},
    {"path": ".gitignore", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_command_contracts.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_sdd_brief_command_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Structure and tone of `.claude/commands/sdd-spec.md` and `sdd-fix.md`:
`# /sdd-brief — …` title, `## Usage`, `## Guardrails`, `## Steps` with
`### N.` headings, exact bash blocks, `⚠️` refusal messages, `## Output`.

### Key Constraints
- Exact ledger refusal text (the contract test greps it):
  `⚠️  Ledger-sourced briefs always base on dev; --base-branch main is refused.`
- Guardrails must state: never write/commit under the main checkout's
  `sdd/`; never `git worktree add`; never `reserve_ids.py`; never push to or
  merge into `main`.
- No `git checkout <base>` in the main checkout — the shared tree stays on
  whatever branch it is on (worktree-management rule).

---

## Implementation Blueprint

### Steps (in order)
1. Verify `wikitoolkit ledger --help` for the release subcommand — *why*: the procedure must not name a command that does not exist.
2. Write `.claude/commands/sdd-brief.md` per Scope steps 1–12 — *why*: the doc is the implementation.
3. Add the `.gitignore` rule and the `_CREATORS` entry — *why*: staging must never be committed; the shared contract test must cover the new creator.
4. Write the contract test — *why*: AC-1..AC-5 keep the procedure honest.

### `.gitignore` (MODIFY)
```gitignore
# occurrences: 1 (verified: grep -c '^sdd/state/.intake/$' .gitignore)
# AFTER — insert below `sdd/state/.intake/` (verified: .gitignore:418)
# FEAT-698: /sdd-brief draft staging; the committed brief lives only inside the worktree
sdd/state/.brief/
```

### `tests/sdd_scripts/test_command_contracts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_CREATORS: dict\[str, bool\] = {' tests/sdd_scripts/test_command_contracts.py)
# AFTER — insert below `    ".claude/commands/sdd-start.md": True,` inside _CREATORS (verified: test_command_contracts.py:25)
    ".claude/commands/sdd-brief.md": True,
```

### `.claude/commands/sdd-brief.md` (CREATE)
```markdown
# /sdd-brief — Research-First Brief for a Hotfix or Single-Issue Fix

Turn one bug, alert, or ledger issue into a worktree holding an actionable
brief — research first, a short Q&A, no FEAT/TASK id reservation (FEAT-698).
Replaces `/sdd-spec --type hotfix`.

## Usage
/sdd-brief <source> [--base-branch main|dev|staging] [--no-interview] [--split] [--research full|light]

## Guardrails
<!-- FILL IN: the five never-rules from Key Constraints, as bullets -->

## Steps
### 1. Parse Input
<!-- FILL IN: Scope step 1 -->
### 2. Detect and Fetch the Source
<!-- FILL IN: Scope step 2, as a table + bash per source kind -->
<!-- … FILL IN: ### 3 … ### 12 exactly as Scope lists them … -->

## Output
<!-- FILL IN: the handoff block from Scope step 12 -->
```
**Why**: the heading skeleton is fixed so the contract test can address
steps by number; the bodies are the judgment-bearing part.

### `tests/sdd_scripts/test_sdd_brief_command_contract.py` (CREATE)
```python
"""Contract guards for .claude/commands/sdd-brief.md — FEAT-698 / TASK-4429."""

from __future__ import annotations

from pathlib import Path

_DOC = Path(__file__).resolve().parents[2] / ".claude/commands/sdd-brief.md"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_provisions_through_ensure_worktree_brief_key() -> None:
    assert "scripts.sdd.ensure_worktree" in _text() and "--brief-key" in _text()

# FILL IN: test_ledger_main_refusal_text_present (AC-2)
# FILL IN: test_research_floor_stated — "path:line" + refusal to create the worktree (AC-3)
# FILL IN: test_never_reserves_ids — "reserve_ids" appears only inside a "never" guardrail line (AC-4)
# FILL IN: test_never_hand_rolls_worktree — "git worktree add" absent (AC-5; also covered by _CREATORS)
```

### FILL IN checklist
- [ ] Guardrails bullets
- [ ] Steps 1–12 bodies
- [ ] Output block
- [ ] contract tests AC-2..AC-5

---

## Acceptance Criteria

- [ ] AC-1: the command provisions only via `python -m scripts.sdd.ensure_worktree … --brief-key` and is registered in `_CREATORS`.
- [ ] AC-2: the ledger + `--base-branch main` refusal is present verbatim.
- [ ] AC-3: the S9 research floor is a hard stop before step 9.
- [ ] AC-4: no step calls `reserve_ids.py`; no step writes under the main checkout's `sdd/`.
- [ ] AC-5: no `git worktree add`, no push/merge to `main`.
- [ ] AC-6: `sdd/state/.brief/` is git-ignored (`git check-ignore sdd/state/.brief/x` succeeds).

---

## Validation Commands

- `pytest tests/sdd_scripts/test_sdd_brief_command_contract.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-brief-hotfix-flow --feature-id FEAT-698`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-brief-hotfix-flow.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands from the worktree root
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4429 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
