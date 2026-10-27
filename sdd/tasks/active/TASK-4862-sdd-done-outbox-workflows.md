# TASK-4862: /sdd-done delivers via the outbox on all three hosts; worker/coder ledger contracts

**Feature**: FEAT-758 — Durable Ledger Outbox and Independent Integration into dev
**Spec**: `sdd/specs/ledger-outbox-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4860, TASK-4861
**Assigned-to**: unassigned

---

## Context

Spec §2 "Coordination and workflow boundaries" and §3 Module 5. The three `/sdd-done` hosts (Claude, Codex,
Antigravity) currently reproduce a shell algorithm in step 9.1 that exports the snapshot, exports
`events.jsonl` and **rotates** logs from a throwaway worktree, pushes to `base_branch`, skips hotfixes, and
"never fails /sdd-done". FEAT-758 replaces it with the tested CLI (TASK-4860): deliver to **dev** for features
AND hotfixes, never rotate, and make pending/conflict/unsupported delivery block cleanup. Worker and coder
prompts must state that findings go through ledger services/MCP — never by writing or staging tracked JSONL.

---

## Scope

- **Three done hosts** — replace the 9.1 section (Claude/Antigravity) and step 11 (Codex) with identical
  outcomes:
  1. Before pushing the feature branch (Claude/Antigravity Step 8, Codex step 9) run
     `wikitoolkit ledger outbox status --repo-root <worktree> --json`; exit 4 with `contaminated_paths` →
     report the paths and point to `docs/sdd/ledger-outbox.md` § legacy recovery; **do not** restore or drop
     them, do not block the code PR.
  2. Step 9.1 "Deliver Ledger Events (FEAT-758)", for **every** flow type including hotfix:
     `wikitoolkit ledger outbox prepare --repo-root <worktree>` then
     `wikitoolkit ledger outbox integrate --repo-root <worktree>`; destination is always `origin/dev`, never
     `main`, regardless of `BASE_BRANCH`.
  3. Exit 0 → continue; report the receipt and any remaining pending events. Exit 2/3/4 → set
     `LEDGER_DELIVERY_PENDING=1`, print the batch location and the exact retry command
     (`wikitoolkit ledger outbox integrate --repo-root <worktree> --batch-id <id>`); the code PR (if already
     pushed/opened) stays open — no rollback.
  4. Step 11 Cleanup: first run one more `prepare` + `integrate` pass (captures closures recorded after 9.1,
     e.g. by a post-merge step); remove the worktree **only** when both passes exited 0 and
     `LEDGER_DELIVERY_PENDING` is unset; otherwise retain it and report "closeout incomplete: ledger delivery
     pending".
  5. Remove every mention of `ledger export-log`, `rotate-log`, "never fails /sdd-done", "Skip the snapshot
     entirely for hotfixes" and the `_ledger-snapshot-$$` shell loop from these sections. Rotation remains an
     explicit maintenance command documented in TASK-4863's doc, not in done.
- **Worker prompts** (`.claude/agents/sdd-worker.md` and its byte-identical package twin; `.codex/agents/
  sdd-worker.toml`): add a rule — ledger findings are recorded with `wikitoolkit ledger open` / MCP
  `ledger_open` carrying task/review attribution; never append to or stage `sdd/ledger/*.jsonl`; delivery is
  `/sdd-done`'s job.
- **Coder prompts** (`_subagent_data/sdd-coder.md` and its byte-identical `.claude/agents/sdd-coder.md` twin):
  extend rule 6 — a coder without a ledger tool returns findings to its worker in the `DevelopmentOutput`
  instead of writing ledger files.
- Update `tests/sdd/test_ledger_workflow_twins.py::TestDoneTwins` for the new contract.

**NOT in scope**: Python code (TASK-4857..4861); `docs/` (TASK-4863); `/sdd-codereview`, `/sdd-start`,
`/sdd-fix` twins; installing hooks on the real checkout.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Replace §9.1; status pre-check at Step 8; gate Step 11 |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | Replace step 11; pre-check in step 9; gate step 15 |
| `.agent/workflows/sdd-done.md` | MODIFY | Same as the Claude host |
| `.claude/agents/sdd-worker.md` | MODIFY | Ledger-findings rule |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Byte-identical twin of the above |
| `.codex/agents/sdd-worker.toml` | MODIFY | Same rule in the Codex worker |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` | MODIFY | Extend rule 6 |
| `.claude/agents/sdd-coder.md` | MODIFY | Byte-identical twin of the above |
| `tests/sdd/test_ledger_workflow_twins.py` | MODIFY | New `TestDoneTwins` assertions |

> Spec §3 M5 lists only one side of each prompt pair. `packages/ai-parrot/tests/flows/dev_loop/
> test_subagent_parity.py` requires `_subagent_data/<name>.md` and `.claude/agents/<name>.md` to stay
> byte-identical (verified: `cmp` reports both pairs identical today), so both copies are in scope.

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (all `grep -c` = 1 on the current dev tip)
```text
.claude/commands/sdd-done.md:429      ### 8. Push the Feature Branch
.claude/commands/sdd-done.md:475      ### 9.1. Snapshot Ledger Issues (FEAT-566)
.claude/commands/sdd-done.md:543      ### 9.2. Integrate Feature Branch (FEAT-145, flow-aware)
.claude/commands/sdd-done.md:868      ### 11. Cleanup the Worktree
.agent/workflows/sdd-done.md:341      ### 8. Push the Feature Branch
.agent/workflows/sdd-done.md:378      ### 9.1. Snapshot Ledger Issues (FEAT-566)
.agent/workflows/sdd-done.md:443      ### 9.2. Integrate Feature Branch (FEAT-145, flow-aware)
.agent/workflows/sdd-done.md:753      ### 11. Cleanup the Worktree
.agents/skills/sdd-done/SKILL.md:175  9. Push feature branch:
.agents/skills/sdd-done/SKILL.md:186  11. Snapshot ledger issues (feature flows only):
.agents/skills/sdd-done/SKILL.md:206  12. Integrate:
.agents/skills/sdd-done/SKILL.md:227  15. Cleanup:
.claude/agents/sdd-worker.md:95       6. **CODE AND STATE LIVE TOGETHER IN THE WORKTREE (FEAT-145).**
.codex/agents/sdd-worker.toml:138     Push:
packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md:78   6. **YOU NEVER TOUCH `sdd/tasks/` OR `sdd/ledger/`.**
tests/sdd/test_ledger_workflow_twins.py:87   class TestDoneTwins:
```
Re-run `grep -n` for each before editing; `.agent/workflows/sdd-done.md` Step 8's heading must be located
the same way (`grep -n '^### 8\.' .agent/workflows/sdd-done.md`).

### Existing test contract to keep or update (`tests/sdd/test_ledger_workflow_twins.py`)
- `TestDoneTwins.test_snapshot_uses_throwaway_worktree_and_excludes_hotfix` (asserts `"ledger export"` and
  `"hotfix"` in every twin) — **replace** it with `test_delivery_uses_outbox_for_every_flow` (below).
- `test_merge_gate_scopes_blockers_to_current_feature` and `test_closes_issues_resolved_by_verified_tasks`
  must keep passing (do not remove `ledger blockers`, `scripts.sdd.close_resolved_issues`,
  `shared ledger is read-only` from the done twins).
- The module reads files through `_WORKTREE_ROOT` (file-relative), never CWD — keep using `read_workflow_file`.

### CLI contract consumed (TASK-4860)
```text
wikitoolkit ledger outbox status    --repo-root PATH [--ledger-dir PATH] [--json]   exit 4 on contamination
wikitoolkit ledger outbox prepare   --repo-root PATH [--ledger-dir PATH] [--json]
wikitoolkit ledger outbox integrate --repo-root PATH [--ledger-dir PATH] [--batch-id UUID] [--json]
exit codes: 0 ok · 2 pending · 3 invalid/conflict · 4 unsupported/contamination
```

### Does NOT Exist
- ~~`wikitoolkit ledger outbox deliver` / `--force` / `discard`~~ — no such commands/flags (spec §2 step 6).
- ~~an MCP `ledger_outbox_*` tool~~ — local CLI only.
- ~~`.agents/agents/sdd-worker.*`~~ — not part of this change; only the files listed above.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-done.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-done/SKILL.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-done.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md", "action": "MODIFY"},
    {"path": ".codex/agents/sdd-worker.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-coder.md", "action": "MODIFY"},
    {"path": "tests/sdd/test_ledger_workflow_twins.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:tests/sdd/test_ledger_workflow_twins.py#TestDoneTwins"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit `.claude/commands/sdd-done.md` §9.1 / Step 8 / Step 11 — *why*: it is the reference host.
2. Mirror the same outcomes in `.agent/workflows/sdd-done.md` (bash) and `.agents/skills/sdd-done/SKILL.md`
   (bullets) — *why*: spec M5 "the three hosts must express identical outcomes".
3. Edit `.claude/agents/sdd-worker.md`, then `cp` it over the package twin; same for `sdd-coder.md` (edit the
   package copy, `cp` to `.claude/agents/`) — *why*: `test_subagent_parity.py` demands byte identity.
4. Edit the Codex worker TOML.
5. Update `TestDoneTwins`; run the parity test too.

### `.claude/commands/sdd-done.md` (MODIFY) — replace §9.1 (and identically `.agent/workflows/sdd-done.md`)
```markdown
<!-- occurrences: 1 (verified: grep -c '### 9.1. Snapshot Ledger Issues (FEAT-566)' .claude/commands/sdd-done.md)
     REPLACE from this heading down to (not including) `### 9.2. Integrate Feature Branch` -->
### 9.1. Deliver Ledger Events (FEAT-758)

Ledger events never travel in the feature PR. Deliver every pending local event to `origin/dev` through the
durable outbox — for **every** flow type, hotfixes included (ledger data never goes to `main`). The integrator
works in its own temporary checkout of `origin/dev`, retries a rejected push on a fresh base (max 3), never
force-pushes and never rotates logs. See `docs/sdd/ledger-outbox.md`.

```bash
LEDGER_DELIVERY_PENDING=0
wikitoolkit ledger outbox prepare --repo-root "<worktree-path>"
PREP_RC=$?
wikitoolkit ledger outbox integrate --repo-root "<worktree-path>"
INTEG_RC=$?
if (( PREP_RC != 0 || INTEG_RC != 0 )); then
    LEDGER_DELIVERY_PENDING=1
    # FILL IN: echo one line per exit code: 2 pending (I/O, lock, push/retry), 3 conflict/invalid content
    #   (review required), 4 unsupported source; then the retry command
    #   `wikitoolkit ledger outbox integrate --repo-root "<worktree-path>"` and "closeout will stay incomplete".
fi
```
Pending delivery does NOT undo the code PR; it blocks Step 11 cleanup only.
```
**Why**: spec §2 "On pending/conflict/unsupported delivery, retain the batch, report its location and retry
command, and do not declare closeout complete or remove the feature worktree."

### Step 8 pre-check (Claude + Antigravity; Codex step 9)
```markdown
<!-- AFTER the existing push command block of Step 8 -->
Report (never fix) legacy ledger contamination on the feature branch:
```bash
wikitoolkit ledger outbox status --repo-root "<worktree-path>" --json
# exit 4 + "contaminated_paths": list them and point to docs/sdd/ledger-outbox.md § "Legacy feature diff".
# Do not restore, drop or block — the code PR proceeds.
```
```

### Step 11 gate (Claude + Antigravity; Codex step 15)
```markdown
<!-- BEFORE the `git worktree remove` block of "### 11. Cleanup the Worktree" -->
First run one more delivery pass (closures recorded after 9.1, e.g. by a post-merge step, need it):
`wikitoolkit ledger outbox prepare --repo-root "<worktree-path>" && wikitoolkit ledger outbox integrate --repo-root "<worktree-path>"`.
Remove the worktree ONLY when that pass exited 0 and `LEDGER_DELIVERY_PENDING` is 0; otherwise keep it and
print `⚠️  Closeout incomplete: ledger delivery pending — retry with <command>`.
```

### `.agents/skills/sdd-done/SKILL.md` (MODIFY) — replace step 11
```markdown
<!-- occurrences: 1 (verified: grep -c '11. Snapshot ledger issues (feature flows only):')
     REPLACE step 11's bullets (lines 186-201) with: -->
11. Deliver ledger events (every flow, hotfixes included — FEAT-758):
    - `wikitoolkit ledger outbox prepare --repo-root <worktree>` then
      `wikitoolkit ledger outbox integrate --repo-root <worktree>`; destination is always `origin/dev`
    - exit 0: continue and report the receipt; exit 2/3/4: mark delivery pending, report the batch location and
      the retry command; never force-push, never rotate, never push ledger data to `main`
    - the code PR is not rolled back; cleanup (step 15) is blocked until a pass exits 0
```
Add to step 9 the `outbox status` contamination report bullet, and to step 15 the "second pass + gate" bullet.

### `.claude/agents/sdd-worker.md` (MODIFY) — then `cp` to the package twin
```markdown
<!-- occurrences: 1 (verified: grep -c '6. **CODE AND STATE LIVE TOGETHER IN THE WORKTREE (FEAT-145).**')
     AFTER the rule-6 paragraph (ends "Per-spec indexes mean each feature owns its own file.") insert: -->

7. **LEDGER FINDINGS GO THROUGH THE LEDGER SERVICE (FEAT-758).**
   Record deferred findings with `wikitoolkit ledger open` (or the `ledger_open` MCP tool) carrying the
   task/review attribution in `--discovered-from`. NEVER append to, edit or stage `sdd/ledger/events.jsonl`
   or `sdd/ledger/issues.jsonl` — feature commits must not change them. `/sdd-done` delivers events to
   `origin/dev` through the outbox. Coder findings returned in a `DevelopmentOutput` are registered by you.
```
FILL IN: renumber nothing else — if a rule 7 already exists in that list, insert as the next free number and
keep the list consistent. Then `cp .claude/agents/sdd-worker.md
packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md`.

### `.codex/agents/sdd-worker.toml` (MODIFY)
```text
# occurrences: 1 (verified: grep -c '^Push:' .codex/agents/sdd-worker.toml)
# BEFORE `Push:` insert:
Ledger findings:
- Record deferred findings with `wikitoolkit ledger open --discovered-from task:<TASK-ID>`.
- Never append to or stage `sdd/ledger/events.jsonl` or `sdd/ledger/issues.jsonl`; sdd-done delivers them.

```

### `_subagent_data/sdd-coder.md` (MODIFY) — then `cp` to `.claude/agents/sdd-coder.md`
```markdown
<!-- occurrences: 1 (verified: grep -c '6. **YOU NEVER TOUCH `sdd/tasks/` OR `sdd/ledger/`.**')
     APPEND to the end of rule 6's paragraph (after "...is a normal deliverable (FEAT-597)."): -->
   Out-of-scope findings you discover go in your `DevelopmentOutput` for the orchestrator to register in the
   ledger (FEAT-758); never write or stage ledger JSONL yourself.
```

### `tests/sdd/test_ledger_workflow_twins.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestDoneTwins:' tests/sdd/test_ledger_workflow_twins.py)
# REPLACE test_snapshot_uses_throwaway_worktree_and_excludes_hotfix with:
    def test_delivery_uses_outbox_for_every_flow(self):
        """Every twin delivers through the outbox, to dev, without rotation or a hotfix skip (FEAT-758)."""
        for path in (self.CLAUDE, self.ANTIGRAVITY, self.CODEX):
            content = read_workflow_file(path)
            assert "ledger outbox prepare" in content, path
            assert "ledger outbox integrate" in content, path
            assert "origin/dev" in content, path
            # FILL IN: assert "rotate-log" not in content and "export-log" not in content;
            #   assert "Skip the snapshot entirely for hotfixes" not in content

    def test_pending_delivery_blocks_cleanup(self):
        # FILL IN: each twin mentions the retry command `ledger outbox integrate --repo-root` and states that
        #   cleanup/worktree removal waits for a successful delivery pass ("ledger delivery pending").

    def test_contamination_is_reported_not_dropped(self):
        # FILL IN: each twin runs `ledger outbox status` and references docs/sdd/ledger-outbox.md
```

### FILL IN checklist
- [ ] Exit-code messages in the 9.1 bash block (both bash hosts) — bounded by spec §2 exit-code table
- [ ] Step 8 pre-check + Step 11 gate in all three hosts — bounded by AC "Pending delivery prevents successful closeout/cleanup"
- [ ] Worker rule numbering; both `cp` twin copies
- [ ] Three `TestDoneTwins` tests

---

## Acceptance Criteria

- [ ] All three done hosts: same destination (`origin/dev`), same pending outcome, hotfixes delivered, cleanup gated
- [ ] No `export-log`, `rotate-log` or ledger push to `main` remains in the done twins
- [ ] Worker/coder prompts forbid writing/staging ledger JSONL and route findings through the service
- [ ] `test_subagent_parity.py` still passes (twins byte-identical)

---

## Validation Commands

- `pytest tests/sdd/test_ledger_workflow_twins.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`

---

## Test Specification

See the `TestDoneTwins` blueprint above.

---

## Agent Instructions

1. Work in the feature worktree; TASK-4860 and TASK-4861 must be `done`.
2. Read spec §2 "Coordination and workflow boundaries" and §3 Module 5.
3. Re-locate every anchor with `grep -n` (these files change often) before editing.
4. Stage only the nine listed files; `.claude/` paths may need `git add -f` if a `.gitignore` rule matches.
5. Run the Validation Commands; close with `scripts/sdd/close_task.sh TASK-4862 ledger-outbox-integration verified`.

---

## Completion Note

*(Agent fills this in when done)*
