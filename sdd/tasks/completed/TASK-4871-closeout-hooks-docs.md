# TASK-4871: Closeout hooks docs, example config, and `--resolve-jira` removal in SDD docs

**Feature**: FEAT-764 — `/sdd-done` closeout hooks
**Spec**: `sdd/specs/sdd-done-closeout-hooks.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-4867, TASK-4869
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5 plus the documentation side of the `--resolve-jira` hard cut (G6):
three SDD docs still advertise the flag.

---

## Scope

- `docs/sdd/closeout-hooks.md`: events table (when / blocking / dry-run), hook kinds, all `HookSpec`
  fields, the four builtins with their env vars (`JIRA_*`, `SDD_TELEGRAM_BOT_TOKEN`/`SDD_TELEGRAM_CHAT_ID`,
  `SDD_NTFY_URL`/`SDD_NTFY_TOPIC`/`SDD_NTFY_TOKEN`, `SDD_GOTIFY_URL`/`SDD_GOTIFY_TOKEN`, webhook
  `url_env`/`headers_env`), the agent record/finalize loop, exit codes, artifact location
  (`/tmp/claude-<uid>/sdd-hooks/<FEAT>/`, never committed, operator keeps them), the trust note
  (hooks run repo-committed shell), and a migration note: `--resolve-jira` → `jira.transition` hook.
- `sdd/templates/sdd_hooks.example.toml`: the spec §2 example (frontend-e2e agent, playwright
  command, jira, telegram) plus a `push.send` ntfy example. Must load with `load_hooks` — add a
  test case to `tests/sdd_scripts/test_closeout_hooks_config.py`? **No** — that file belongs to
  TASK-4867; instead validate manually (Validation Commands) and keep it parseable.
- Replace every `--resolve-jira` in `docs/sdd/GUIDE.md` (lines ~296, 313, 375), `docs/sdd/CODEX.md`
  (~358, 425), `docs/sdd/PLATFORM.md` (~249, 267, 350, 377, 403) with the hook equivalent, pointing to
  `docs/sdd/closeout-hooks.md`. Keep each doc's language (GUIDE.md is Spanish).

**NOT in scope**: the twins (TASK-4870); scripts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/sdd/closeout-hooks.md` | CREATE | User guide |
| `sdd/templates/sdd_hooks.example.toml` | CREATE | Example config (git add -f) |
| `docs/sdd/GUIDE.md` | MODIFY | Replace --resolve-jira usage |
| `docs/sdd/CODEX.md` | MODIFY | Replace --resolve-jira usage |
| `docs/sdd/PLATFORM.md` | MODIFY | Replace --resolve-jira usage |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.closeout_hooks_config import load_hooks   # created by TASK-4867; used only to validate the example
```

### Existing Signatures to Use
```
docs/sdd/GUIDE.md:296     /sdd-done FEAT-147 --resolve-jira    # transicionar el ticket a Done
docs/sdd/GUIDE.md:313     7. Si pides `--resolve-jira`, transiciona el ticket (y subtasks) a
docs/sdd/GUIDE.md:375     /sdd-done FEAT-NNN --resolve-jira
docs/sdd/CODEX.md:358     $sdd-done FEAT-NNN --resolve-jira
docs/sdd/CODEX.md:425     $sdd-done FEAT-NNN --resolve-jira
docs/sdd/PLATFORM.md:249  10. `--resolve-jira`: fetch available transitions and move the linked ticket to
docs/sdd/PLATFORM.md:267  enables `/sdd-done --resolve-jira`, `/pr-review` auto-detection, and idempotent
docs/sdd/PLATFORM.md:350  │ /sdd-done FEAT-071 --resolve-jira                                         │
docs/sdd/PLATFORM.md:377  6. **`/sdd-done FEAT-071 --resolve-jira`** — from `dev`: verify, close tasks,
docs/sdd/PLATFORM.md:403     `--resolve-jira` to `/sdd-done` if linked.)
```
`.gitignore` has a global `templates/` rule: stage the example with `git add -f`.

### Does NOT Exist
- ~~`docs/sdd/closeout-hooks.md`~~, ~~`sdd/templates/sdd_hooks.example.toml`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/sdd/closeout-hooks.md",
      "action": "CREATE"
    },
    {
      "path": "sdd/templates/sdd_hooks.example.toml",
      "action": "CREATE"
    },
    {
      "path": "docs/sdd/GUIDE.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/sdd/CODEX.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/sdd/PLATFORM.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the example TOML and validate it loads — *why*: a doc example that fails validation is worse than none.
2. Write the guide — *why*: consumer repos (navigator-frontend-next) adopt it from here.
3. Replace the ten `--resolve-jira` mentions — *why*: G6 hard cut.

### `sdd/templates/sdd_hooks.example.toml` (CREATE)
```toml
# /sdd-done closeout hooks (FEAT-764) — copy to .parrot/sdd_hooks.toml. Docs: docs/sdd/closeout-hooks.md
[[hooks.pre_pr]]
name = "frontend-e2e"
kind = "agent"
agent = "e2e-ui-tester"
prompt = "Run plan e2e/plans/checkout.yaml for {feat_id}; save a screencast to {artifact_dir}"
blocking = true
artifacts = "**/*.webm"
# FILL IN: playwright command hook; post_pr jira.transition, telegram.send, push.send (provider = "ntfy")
```

### `docs/sdd/closeout-hooks.md` (CREATE)
```markdown
# /sdd-done closeout hooks
# FILL IN: sections listed in Scope
```

### FILL IN checklist
- [ ] Example TOML complete and loadable
- [ ] Guide sections
- [ ] Ten doc replacements

---

## Acceptance Criteria

- [ ] `git grep -n -- --resolve-jira docs/sdd` is empty.
- [ ] Example loads: `python -c "..."` below prints the hook counts without error.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_closeout_hooks_config.py -q`

Manual: `python -c "import shutil,tempfile,pathlib;from scripts.sdd.closeout_hooks_config import load_hooks;d=pathlib.Path(tempfile.mkdtemp());(d/'.parrot').mkdir();shutil.copy('sdd/templates/sdd_hooks.example.toml',d/'.parrot/sdd_hooks.toml');c=load_hooks(d);print(len(c.pre_pr),len(c.post_pr))"`

---

## Test Specification

No new test file (docs task). The example is validated by the manual command above.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-done-closeout-hooks --feature-id FEAT-764`), never on `dev`.
2. Read the spec `sdd/specs/sdd-done-closeout-hooks.spec.md` (§2 Overview, Data Models, exit-code table).
3. Every `Depends-on` task must be `done` in `sdd/tasks/index/sdd-done-closeout-hooks.json`.
4. Verify the Codebase Contract before writing code; fix stale entries first.
5. Mark `in-progress` in the index, implement from the Blueprint, complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH=.` from the worktree root; `ruff check` the new files.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh <TASK-ID> sdd-done-closeout-hooks verified`.

---

## Completion Note


- Task: TASK-4871
- Feature: sdd-done-closeout-hooks
- Implementation SHA: 8ff5083c719ec2752e34025a239c3813e2d66a63
- Closed at (UTC): 2026-10-28T00:27:47+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 224s · Tokens: n/a |
