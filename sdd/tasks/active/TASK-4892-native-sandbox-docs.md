# TASK-4892: Operator and agent guidance for the native sandbox

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4889, TASK-4891
**Assigned-to**: unassigned

---

## Context

Spec §3 M5, AC8, AC11. Operators and agents need one description of the supported entry points,
host prerequisites, domain configuration, the Git push contract, trusted surfaces, safe failure
handling and rollback — using the CLI from TASK-4889 and the tested version/host matrix from
TASK-4891's report.

Found at task time (spec §6 listed only the `.claude/` copies): `sdd-worker.md` and `sdd-coder.md`
have byte-identical package twins under `_subagent_data/` that dispatch actually loads
(`load_subagent_definition`), enforced by `test_subagent_parity.py`; the worktree rule has a
twin skill `.agent/skills/worktree-management/SKILL.md` (not byte-identical, but documents the
same policy and is covered by `test_feat722_doc_contract.py`). All twins are in scope.

---

## Scope

- Create `docs/dev_loop/claude-native-sandbox.md`: supported launch paths, `launch_worker.sh`
  CLI (`--sandbox-allow-domain HOST`, exit codes 1/2, rejected options), version/host matrix
  copied from the qualification report, AppArmor prerequisite (operator, root, outside the feature),
  network domain configuration (`sandbox_allowed_domains` / launcher flag; no wildcards, no SSH),
  Git sequence (host sets upstream before launch; native sessions push with `git push origin <branch>`,
  never `-u`), residual trusted surfaces (hooks, MCP servers, plugins, LSPs run outside the
  sandbox; no secret confidentiality), failure handling (never restart unprotected) and rollback
  (code/deployment revert, not a runtime switch).
- Update the "Shared environment policy" sections of `sdd-worker.md` and `sdd-coder.md` (both
  copies each): native sandbox is the enforcement boundary; the hook still guards/rewrites; the
  native `sdd-coder` seat prefixes every Bash command with `cd <its sub-worktree> &&`.
- Update "4. Work inside" of the worktree rule (both copies): native-session push without `-u`,
  host-side upstream setup, launch via `launch_worker.sh`; remove contradictory `push -u`
  guidance for native sessions while keeping strings the doc-contract tests require.

**NOT in scope**: code, tests, the spec, `CLAUDE.md`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/claude-native-sandbox.md` | CREATE | Operator guide |
| `.claude/agents/sdd-worker.md` | MODIFY | Native policy in "Shared environment policy" |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Byte-identical twin |
| `.claude/agents/sdd-coder.md` | MODIFY | Native policy + `cd <sub-worktree> &&` rule |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md` | MODIFY | Byte-identical twin |
| `.claude/rules/worktree-management.md` | MODIFY | Native push/launch guidance in §4 |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | Same guidance in its §4 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none — documentation only
```

### Existing Signatures to Use
```text
.claude/agents/sdd-worker.md:47                 "## Shared environment policy" (1 occurrence)
_subagent_data/sdd-worker.md:47                 same line (files are byte-identical today)
.claude/agents/sdd-coder.md:34                  "## Shared environment policy" (1 occurrence)
_subagent_data/sdd-coder.md:34                  same line (byte-identical today)
.claude/rules/worktree-management.md:49         "## 4. Work inside" (1 occurrence); push -u at :30 and :51
.agent/skills/worktree-management/SKILL.md:47   "## 4. Work inside" (1 occurrence); push -u at :49
Doc-contract tests that must keep passing:
  tests/sdd_scripts/test_feat722_doc_contract.py        (required strings in worker files + both rule files)
  tests/sdd_scripts/test_pr_policy_wording_contract.py  (rule must contain "--brief-key" and "clears the auto-set upstream")
  packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py  (repo vs package byte parity)
CLI (TASK-4889): scripts/sdd/launch_worker.sh [--sandbox-allow-domain HOST]... [safe Claude arguments]
Report (TASK-4891): sdd/state/FEAT-768/native-sandbox-qualification.md
```

### Does NOT Exist
- ~~`.agent/agents/sdd-coder/`~~ — no Antigravity coder twin; `.agent/agents/sdd-worker/agent.md` has no "Shared environment policy" section — leave it alone.
- ~~an unsandboxed escape flag~~ — never document one.
- ~~agent frontmatter that sets a child's session sandbox~~ — do not claim it (spec integration table).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/dev_loop/claude-native-sandbox.md", "action": "CREATE"},
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-coder.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md", "action": "MODIFY"},
    {"path": ".claude/rules/worktree-management.md", "action": "MODIFY"},
    {"path": ".agent/skills/worktree-management/SKILL.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Edit the `.claude/agents/*.md` copy, then copy it byte-for-byte over its `_subagent_data/` twin
  (`cp`), so parity holds.
- Keep the existing `git push -u origin <branch>` sentence for host/non-native use only if it is
  clearly scoped; the native rule is "no `-u` inside a native session" (spec policy 8).
- Do not paste version numbers that the qualification report did not confirm.

---

## Implementation Blueprint

### Steps (in order)
1. Write the operator guide from the spec §2 policies + the report — *why*: AC11.
2. Edit the `.claude` agent sections, copy to the package twins — *why*: dispatch loads the package copy.
3. Edit both worktree-rule copies — *why*: AC8 (explicit push without `-u`).
4. Run the doc-contract and parity tests.

### `docs/dev_loop/claude-native-sandbox.md` (CREATE)
```markdown
# Native Claude sandbox for SDD sessions (FEAT-768)

## What it protects
<!-- FILL IN: Bash and descendants only; the retained hook (guard → RTK → bounded shell, file-tool
checks); trusted surfaces outside the sandbox; no secret confidentiality — spec non-goals -->

## Supported launch paths
<!-- FILL IN: scripts/sdd/launch_worker.sh (PATH claude) and the dev-loop dispatcher (SDK-bundled CLI);
direct `claude --agent` is not a qualified native launch -->

## Host prerequisites and qualified matrix
<!-- FILL IN: Linux, bwrap, socat, AppArmor profile for the seccomp helper (operator, root);
table copied from sdd/state/FEAT-768/native-sandbox-qualification.md; a CLI/SDK version change
requires re-qualification -->

## Network
<!-- FILL IN: empty default; sandbox_allowed_domains / --sandbox-allow-domain; exact hosts only;
HTTPS git/gh need github.com + api.github.com; no SSH in v1 -->

## Git inside a native session
<!-- FILL IN: host sets upstream before launch; push with `git push origin <branch>`; config and
hooks are read-only by design -->

## Failures and rollback
<!-- FILL IN: exit 1 / exit 2 meanings; never restart without protection; rollback = revert deploy -->
```

### Agent sections (MODIFY, both copies each)
```markdown
<!-- FILL IN (sdd-worker.md and sdd-coder.md, under "## Shared environment policy"): replace the
"Native Claude Bash calls are wrapped by the environment hook…" bullet with: under the supported
launchers the Claude native sandbox enforces the filesystem/network boundary and the hook keeps
the test-scope guard, RTK rewrite and file-tool checks; nested bwrap is not used; never request
dangerouslyDisableSandbox. sdd-coder only: "In a native session, start every Bash command with
`cd <your sub-worktree> && …` — `cd` does not persist between calls and the hook uses that prefix
to pick your worktree's imports." -->
```

### Worktree rule (MODIFY, both copies)
```markdown
<!-- FILL IN (under "## 4. Work inside"): add a bullet — native Claude sessions (launch_worker.sh /
dispatcher) cannot write Git config, so the host sets the upstream before launch and the session
pushes with `git push origin <branch>`; scope the existing `push -u` advice to host shells.
Keep "--brief-key", "clears the auto-set upstream" and the FEAT-722 strings intact. -->
```

### FILL IN checklist
- [ ] operator guide sections
- [ ] agent sections in 4 files (2 pairs, byte parity)
- [ ] rule §4 in 2 files

---

## Acceptance Criteria

- [ ] Guide covers entry points, prerequisites, matrix, domains, Git sequence, trusted surfaces, failure handling, rollback (AC11).
- [ ] No native-session guidance tells agents to `git push -u` (AC8).
- [ ] `sdd-coder` guidance carries the `cd <sub-worktree> &&` rule.
- [ ] Parity and doc-contract tests pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`
- `pytest tests/sdd_scripts/test_feat722_doc_contract.py -q`
- `pytest tests/sdd_scripts/test_pr_policy_wording_contract.py -q`

---

## Test Specification

No new tests; the parity and doc-contract tests above are the specification.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4889 and TASK-4891 are `done` (read the report first).
2. Edit, copy twins, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4892 sdd-claude-native-sandbox verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
