# TASK-4515: /sdd-brainstorm — delegate Code Context checks to sdd-contract-probe

**Feature**: FEAT-708 — sdd-proposal-parallel-research
**Spec**: `sdd/specs/sdd-proposal-parallel-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none (cross-feature: **PR #1742 must be merged into `dev` first** — still OPEN on 2026-10-20)
**Assigned-to**: unassigned

---

## Context

Spec Module 7 (M7), brainstorm half. Step 4 of `/sdd-brainstorm` verifies every
import/path/signature by hand on the thinking model. M7 hands those mechanical
checks to the shared Haiku subagent `sdd-contract-probe` (PR #1742, already used
by `/sdd-task` §3), launched at the Step 4 → 5 boundary and collected before
Step 10.

**Gate**: before starting, `test -f .claude/agents/sdd-contract-probe.md` on
`origin/dev`. If it is absent, STOP — do not write a probe of your own.

## Scope

- Step 4: add "Delegate flat checks" — claim → probe-check mapping, one-message dispatch, ≤ ~40 checks per probe, < ~10 checks → inline.
- Step 5: one line — options generation proceeds while the probe runs.
- Step 10: before saving, collect + verify reports (rules from `/sdd-task` §3, referenced, not copied), classify verified/stale/missing, update Code Context.

**NOT in scope**: `/sdd-proposal` (TASK-4516), `.agent/workflows/sdd-brainstorm.md` twin (TASK-4517), the probe agent file itself.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-brainstorm.md` | MODIFY | Steps 4, 5, 10 |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — Markdown only.

### Existing Signatures to Use
```markdown
<!-- .claude/commands/sdd-brainstorm.md (verified 2026-10-20 @ 9e8092778) -->
:121  ### 4. Research the Codebase & Build Code Context
:142  ### 5. Generate Options
:180  ### 10. Save and Commit
```
From PR #1742 (verify on `dev` before use):
- `.claude/agents/sdd-contract-probe.md` — `model: haiku`; section `## Check kinds and their fixed commands`; kinds `symbol`, `import`, `anchor`, `absent`, `sha256`, `outline`, `file`; report `{repo_root, head, results[{id, kind, status, command, output, count, lines, signature, truncated, note}]}`.
- `.claude/commands/sdd-task.md` §3 "Delegating flat checks to `sdd-contract-probe`" — the verification rules (HEAD match; re-run every negative + 1 in 10 `found`; discard a report with any non-reproducing re-run).

### Does NOT Exist
- ~~a verification **fork**~~ — must not be added
- ~~`model: "haiku"` on an Agent fork call~~ — forks ignore it
- ~~a `contract-validator` agent~~ / ~~`verified|stale|missing` probe statuses~~ — classification is the caller's job

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [{"path": ".claude/commands/sdd-brainstorm.md", "action": "MODIFY"}],
  "contract_symbols": []
}
```

## Implementation Blueprint

### Steps (in order)
1. Gate check (PR #1742 on dev). Read the probe agent file; use its exact field names.
2. Append the delegation block at the end of Step 4 (just above `### 5. Generate Options`).
3. Add a one-line note under `### 5. Generate Options`.
4. Insert the collect block as the first item under `### 10. Save and Commit`.

### `.claude/commands/sdd-brainstorm.md` (MODIFY) — end of Step 4
```markdown
<!-- occurrences: 1 (verified: grep -c '^### 5. Generate Options' .claude/commands/sdd-brainstorm.md) -->
<!-- BEFORE — insert above `### 5. Generate Options` (verified :142) -->
**Delegate the flat checks (FEAT-708).** Turn every reference you intend to put in
Code Context into a probe check, then hand them to the shared read-only Haiku
subagent `sdd-contract-probe` (the same one `/sdd-task` §3 uses):

| Claim | Probe check |
|---|---|
| `from parrot.X import Y` | `{"id": "cN", "kind": "import", "module": "parrot.X", "name": "Y"}` |
| `path/file.py:42` | `{"id": "cN", "kind": "file", "path": "<repo-relative>", "line": 42}` |
| `class Foo(Bar):` | `{"id": "cN", "kind": "symbol", "path": "<file>", "name": "Foo"}` — keep `expected` yourself |
| "Does NOT exist: X" | `{"id": "cN", "kind": "absent", "name": "X", "scope": "<whole module dir>"}` |
| `path:NN` + verbatim line | `{"id": "cN", "kind": "anchor", "path": "<file>", "anchor": "<line>"}` |

Launch the probes in ONE message (groups of ≤ ~40 checks, grouped by file):
`Agent({subagent_type: "sdd-contract-probe", description: "Verify codebase claims",
prompt: "Repository root: <abs path>\nProbe sheet: <JSON array>"})`.
Do not wait — continue with Step 5. With fewer than ~10 checks, or without the
Agent tool, verify inline as above instead.
```

### `.claude/commands/sdd-brainstorm.md` (MODIFY) — Step 10
```markdown
<!-- occurrences: 1 (verified: grep -c '^### 10. Save and Commit' .claude/commands/sdd-brainstorm.md) -->
<!-- AFTER — insert directly below `### 10. Save and Commit` (verified :180), before item 1 -->
0. **Collect the contract probes** (if launched in Step 4). Verify each report
   with `/sdd-task` §3's rules for `sdd-contract-probe` (HEAD match, re-run
   negatives + one `found` in ten; a non-reproducing re-run discards the report
   and its checks run inline). Classify each claim:
   FILL IN: classification table
   Then fix Code Context: add `lines` to verified refs, drop `missing` refs,
   replace `stale` signatures with the probe's `signature`, and remove a
   "Does NOT Exist" entry whose `absent` check came back `present`.
```

### FILL IN checklist
- [ ] Classification table — copy spec M7 "Classification" table verbatim (5 rows)
- [ ] Step 5 one-liner: "If contract probes are running (Step 4), generate options now; their results are applied in Step 10."
- [ ] Confirm the `/sdd-task` §3 heading text on dev and cite it exactly

## Acceptance Criteria

- [ ] Step 4 dispatches `sdd-contract-probe` (not a fork, no `model:` override)
- [ ] Inline fallback: no Agent tool, < ~10 checks, or discarded report
- [ ] Step 10 verifies reports with `/sdd-task` §3 rules before use
- [ ] Classification table identical to spec M7
- [ ] Stale signatures corrected, missing refs dropped before commit

## Validation Commands

- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-proposal-parallel-research --feature-id FEAT-708`)
2. **Read the spec** at `sdd/specs/sdd-proposal-parallel-research.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-proposal-parallel-research.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` anchor check before editing;
   if an anchor moved, fix the blueprint first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `FILL IN`
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (`.claude/` paths need `git add -f`)
9. **Close** with `scripts/sdd/close_task.sh <TASK-ID> sdd-proposal-parallel-research verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
