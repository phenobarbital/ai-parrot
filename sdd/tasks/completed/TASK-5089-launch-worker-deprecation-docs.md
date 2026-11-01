# TASK-5089: Deprecate `launch_worker.sh`; document legacy mode, platforms and `parrot devloop launch-worker`

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5088
**Assigned-to**: unassigned

---

## Context

Spec §2 policies 11–13 and AC11/AC17 (rev 0.4). TASK-5086..5088 add the `legacy` mode, per-platform probes
and the `parrot devloop launch-worker` command. The operator-facing docs and agent guidance still point at
`scripts/sdd/launch_worker.sh` and the hand-made tmux recipe. This task makes `parrot devloop launch-worker`
the documented entry point and turns the shell script into a warning alias.

---

## Scope

- `scripts/sdd/launch_worker.sh`: before the `exec`, print exactly one line to stderr:
  `launch_worker.sh: DEPRECATED — use 'parrot devloop launch-worker <FEAT-ID> [--tmux]' (this alias keeps launching sdd-worker in the current worktree)`.
  Behaviour, argument handling and exit codes are otherwise unchanged.
- `docs/dev_loop/claude-native-sandbox.md`:
  - "Supported launch paths": first row becomes `parrot devloop launch-worker <FEAT-ID|slug> [--tmux] [--detach] [--sandbox MODE] [--sandbox-allow-domain HOST]... [--no-upstream] [-- claude args]` with what it does on the host (feature resolution, `ensure_worktree`, upstream rules incl. the diverged refusal, `run <FEAT-ID>` prompt, tmux session `sdd-<FEAT-ID>` and why `-e` is used); keep `launch_worker.sh` as a deprecated row.
  - "Sandbox mode" table: add `legacy` (env / `--sandbox` only, Bubblewrap hook boundary, no network isolation, fails closed without `bwrap` or off Linux) and update the resolution paragraph (`off` **and** `legacy` are env-only).
  - New section "Platforms": Linux/WSL2 (qualified), macOS Seatbelt (implemented, **not certified**, the stderr notice), native Windows (no sandbox; the exact refusal text; `preferred` degrades), legacy hook message when `bwrap` is missing.
  - "Failure handling and rollback": rollback ladder `required` → `legacy` (native misbehaves, bwrap works) → `preferred` (no OS boundary, declared) → code revert; replace the sentence that says rollback is only a revert or `required`.
- `CLAUDE.md` § "Autonomous Agent (`sdd-worker`)" (lines ~229–252): replace the `launch_worker.sh` and hand-made `tmux new -s … "scripts/sdd/launch_worker.sh --verbose"` recipe with `parrot devloop launch-worker FEAT-<NNN>` and `parrot devloop launch-worker FEAT-<NNN> --tmux` (+ `--detach`, reattach = run it again); keep the Typical Workflow comment line consistent.
- `docs/sdd/GUIDE.md` (lines ~463–467) and `docs/sdd/PLATFORM.md` (lines ~303, ~345): same replacement.
- `.claude/rules/worktree-management.md` (lines 51, 55) and its twin `.agent/skills/worktree-management/SKILL.md` (lines 49, 52): name `parrot devloop launch-worker` as the interactive launcher (it also sets the upstream on the host); keep wording parallel in both files.
- `.claude/commands/sdd-task.md:570` and its twin `.agent/workflows/sdd-task.md:566`: the "or, unattended" hint becomes `parrot devloop launch-worker FEAT-<NNN> --tmux`.

**NOT in scope**: `.claude/commands/sdd-brief.md` (brief worktrees are keyed by brief, which `launch-worker`
does not resolve; the deprecated alias still works there and `tests/sdd_scripts/test_sdd_brief_twin_contract.py`
pins that text); removing `launch_worker.sh`; any code outside the script; `sdd/state/FEAT-768/native-sandbox-qualification.md`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/launch_worker.sh` | MODIFY | deprecation line |
| `tests/sdd/test_launch_worker.py` | MODIFY | assert the deprecation line on stderr; behaviour unchanged |
| `docs/dev_loop/claude-native-sandbox.md` | MODIFY | launcher, legacy, platforms, rollback ladder |
| `CLAUDE.md` | MODIFY | Autonomous Agent section |
| `docs/sdd/GUIDE.md` | MODIFY | launcher recipe |
| `docs/sdd/PLATFORM.md` | MODIFY | launcher references |
| `.claude/rules/worktree-management.md` | MODIFY | launcher wording |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | twin of the rule |
| `.claude/commands/sdd-task.md` | MODIFY | unattended hint |
| `.agent/workflows/sdd-task.md` | MODIFY | twin of the command |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```text
(no Python imports — script + docs)
```

### Existing Signatures to Use
```text
scripts/sdd/launch_worker.sh: final statement `exec "$python_bin" "$repo_root/packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py" launch-worker "$@"`
CLAUDE.md:229 `/sdd-start TASK-<NNN+1> …                  # or: scripts/sdd/launch_worker.sh`; :240 and :250 the two `launch_worker.sh --verbose` recipes
docs/sdd/GUIDE.md:463, :467; docs/sdd/PLATFORM.md:303, :345
.claude/rules/worktree-management.md:51, :55; .agent/skills/worktree-management/SKILL.md:49, :52
.claude/commands/sdd-task.md:570; .agent/workflows/sdd-task.md:566
docs/dev_loop/claude-native-sandbox.md sections: "## Supported launch paths", "## Sandbox mode", "### `launch_worker.sh` reference", "## Failure handling and rollback"
tests/sdd/test_launch_worker.py: helper _run(path, cwd, *args) (56) runs the script with /bin/bash
Doc contract tests that must stay green: tests/sdd_scripts/test_feat722_doc_contract.py, tests/sdd_scripts/test_pr_policy_wording_contract.py,
  packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py
```

### Does NOT Exist
- ~~a byte-identity test between `.claude/rules/worktree-management.md` and `.agent/skills/worktree-management/SKILL.md`~~ — they are wording twins, not copies; keep them consistent by hand.
- ~~a `--verbose` option on `parrot devloop launch-worker`~~ — pass claude flags after `--` (`parrot devloop launch-worker FEAT-1 -- --verbose`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/launch_worker.sh", "action": "MODIFY"},
    {"path": "tests/sdd/test_launch_worker.py", "action": "MODIFY"},
    {"path": "docs/dev_loop/claude-native-sandbox.md", "action": "MODIFY"},
    {"path": "CLAUDE.md", "action": "MODIFY"},
    {"path": "docs/sdd/GUIDE.md", "action": "MODIFY"},
    {"path": "docs/sdd/PLATFORM.md", "action": "MODIFY"},
    {"path": ".claude/rules/worktree-management.md", "action": "MODIFY"},
    {"path": ".agent/skills/worktree-management/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-task.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-task.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Write the docs from the code that TASK-5086..5088 actually merged (read it), not from this task's wording;
  copy exact stderr strings from the source.
- Keep the docs' existing claims about qualification untouched (Linux only is qualified).

---

## Acceptance Criteria

- [ ] `launch_worker.sh` prints the deprecation line once on stderr and otherwise behaves as before (existing launcher tests green).
- [ ] `docs/dev_loop/claude-native-sandbox.md` documents `parrot devloop launch-worker`, `legacy`, the platform matrix (macOS uncertified) and the rollback ladder.
- [ ] No remaining doc in the Files table recommends `launch_worker.sh` or the hand-made tmux recipe as the primary launcher.
- [ ] All Validation Commands green.

---

## Validation Commands

- `pytest tests/sdd/test_launch_worker.py -q`
- `pytest tests/sdd_scripts/test_feat722_doc_contract.py -q`
- `pytest tests/sdd_scripts/test_pr_policy_wording_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`
- `pytest tests/sdd_scripts/test_sdd_brief_twin_contract.py -q`

---

## Test Specification

One new launcher test: run the script through `_run` with the existing fixtures and assert the deprecation line
appears exactly once in `result.stderr`. Docs are covered by the existing doc-contract tests.

---

## Agent Instructions

1. Work only in the worktree you are given; commit only the files in the table.
2. Verify every Codebase Contract entry before editing; stop and report if one is stale.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note


- Task: TASK-5089
- Feature: sdd-claude-native-sandbox
- Implementation SHA: 7d450cb544cdd5e3a3c79ba7df93d41f2c659347
- Closed at (UTC): 2026-11-01T01:16:15+00:00
- Fix commits: 7d450cb544cdd5e3a3c79ba7df93d41f2c659347

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| feedback | coder-feedback:dc23cce56f1b6e7d288382a3 (ascii-diagram-misaligned) |
| review | docs match merged code (exact stderr strings); one fix: PLATFORM.md lifecycle box row overflow (7d450cb544) |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 216.9s · Tokens: n/a |
| validation | merge tier green (test_launch_worker 33 passed); doc contracts 41 passed/1 skipped after fix |
