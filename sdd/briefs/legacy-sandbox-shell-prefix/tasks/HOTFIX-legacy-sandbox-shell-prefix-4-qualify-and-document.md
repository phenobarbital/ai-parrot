# HOTFIX-legacy-sandbox-shell-prefix-4: live qualification, before/after measurement, worker guidance, wiki

**Feature**: legacy-sandbox-shell-prefix — apply the SDD sandbox and RTK through `CLAUDE_CODE_SHELL_PREFIX`
**Spec**: `sdd/briefs/legacy-sandbox-shell-prefix.brief.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-legacy-sandbox-shell-prefix-3
**Assigned-to**: unassigned

---

## Context

Tasks 1–3 move the `bwrap` boundary and RTK into the prefix. This task proves it against a real Claude Code
session, measures the refusals that remain, writes the worker guidance for legacy mode (moved here from an
uncommitted note, brief Decision 3), and documents the prefix and the permission-mode finding.

## Scope

1. **Live test.** Create `packages/ai-parrot/tests/flows/dev_loop/test_shell_prefix_live.py`, skipped unless
   `PARROT_TEST_REAL_LLM=1` (same marker as `test_native_claude_sandbox_live.py`). In a scratch git repo under
   `tmp_path` with a generated legacy policy (`prepare_shell_prefix`), run `claude -p` (haiku,
   `--setting-sources local`, one allowed Bash command) and assert: the Bash command ran inside `bwrap`
   (writing a file next to the repo, outside the bound roots, fails); a configured hook ran unwrapped (it
   records the token); a configured stdio MCP server was started through a pass-through.

2. **Measurement.** Write `sdd/state/BRIEF-legacy-sandbox-shell-prefix/automode-rewrites.md`. Replay the Bash
   commands of the FEAT-860 legacy transcript (session `135df69e-0d8f-4032-8edc-9d61a6757d69`) and of the
   FEAT-793 native transcript (`03ebac40`, used by `sdd/state/BRIEF-sdd-native-sandbox-default/automode-rewrites.md`)
   through `hook_response`, before (dev) and after (this branch, with a valid prefix policy). Report rewritten
   commands per backend and the causes of what remains. Keep the replay script in the session scratchpad,
   uncommitted, as the earlier brief did.

3. **Worker guidance.** In `.claude/agents/sdd-worker.md` and its byte-identical twin
   `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md`, after the bullet "When auto mode
   reports that a hook changed a Bash call's input…" (line 59), add a legacy-mode bullet, and change line 63
   from "Under the supported launchers the Claude native sandbox…" to "Under the supported launchers in the
   default (native) mode the Claude native sandbox…". Start from the operator-approved draft below and adjust
   it to the measured behaviour (with the prefix there is no per-command refusal; a refusal still appears for
   scope-guard rewrites, explicit timeouts, or a session not started by the launcher):

   > - **Legacy sandbox mode** (`PARROT_SDD_SANDBOX_BACKEND=bubblewrap`): the operator launched with
   >   `sandbox=legacy`, the fallback for hosts where the Claude native sandbox is unavailable (for example,
   >   no AppArmor profile that lets `bwrap` create user namespaces). In this mode the guard hook wraps
   >   **every** Bash command in `/usr/bin/bwrap …`, because that wrapper is the filesystem boundary. Under
   >   auto mode each call is refused once and passes on the verbatim resend. This is expected and costs one
   >   extra round-trip per command. It is not a reason to stop, check in with the user, or suggest disabling
   >   the hook or auto mode. Keep going. To cut round-trips, batch related commands into one Bash call and
   >   use Read, Grep and Glob instead of Bash for read-only inspection (the hook never rewrites those).
   >   Stop and report only when the verbatim resend is refused again.

4. **Wiki.** In `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` § "Sandbox mode": how legacy uses
   `CLAUDE_CODE_SHELL_PREFIX` (one-argument contract, what it wraps, exact allowlist, token, exit 2, state
   directory), RTK in the prefix and the native decision from task 3's probe, and the finding that
   `permissionMode` in an agent's frontmatter does not apply to a `claude --agent` session (brief, Research
   findings; Decision 4: the launcher does not change the permission mode).

**NOT in scope**: code changes beyond the live test (tasks 1–3); the `.agents/agents/sdd-worker/agent.md`
copy (agy has no auto-mode classifier); the dev-loop dispatcher.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_shell_prefix_live.py` | CREATE | opt-in live test |
| `sdd/state/BRIEF-legacy-sandbox-shell-prefix/automode-rewrites.md` | CREATE | before/after measurement |
| `.claude/agents/sdd-worker.md` | MODIFY | legacy guidance |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md` | MODIFY | byte-identical twin |
| `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md` | MODIFY | prefix + permission-mode finding |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ 12a988cf3a, 2026-11-09)

- `.claude/agents/sdd-worker.md:59` — `- When auto mode reports that a hook changed a Bash call's input, resend the hook's command once and verbatim; …`
- `.claude/agents/sdd-worker.md:63` — `- Under the supported launchers the Claude native sandbox enforces the filesystem/network boundary …`
- `.claude/agents/sdd-worker.md:25` — `permissionMode: bypassPermissions`
- `wiki/sdd-tooling/dev_loop/claude-native-sandbox.md:79` — `## Sandbox mode`
- `tests/flows/dev_loop/test_native_claude_sandbox_live.py:29` — `pytestmark = pytest.mark.skipif(` on `PARROT_TEST_REAL_LLM`
- `sdd/state/BRIEF-sdd-native-sandbox-default/automode-rewrites.md` — prior measurement (65 commands; 41 RTK
  rewrites remained with the native launcher)

### Existing Signatures to Use

- `prepare_shell_prefix` (task 2), `hook_response` (`worktree_environment.py:979`)

### Does NOT Exist

- `test_shell_prefix_live.py`, `sdd/state/BRIEF-legacy-sandbox-shell-prefix/automode-rewrites.md`

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_shell_prefix_live.py", "action": "CREATE"},
    {"path": "sdd/state/BRIEF-legacy-sandbox-shell-prefix/automode-rewrites.md", "action": "CREATE"},
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": "wiki/sdd-tooling/dev_loop/claude-native-sandbox.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#hook_response"
  ]
}
```

## Acceptance Criteria

- [ ] With `PARROT_TEST_REAL_LLM=1` the live test passes on this host; without it, it is skipped.
- [ ] `automode-rewrites.md` reports before/after counts for the legacy and native transcripts and names
      every remaining cause.
- [ ] The two `sdd-worker.md` copies are byte-identical and describe legacy mode as it now behaves.
- [ ] The wiki page documents the prefix, the allowlist, the token, the native decision and the
      permission-mode finding.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_shell_prefix_live.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`

## Test Specification

`test_shell_prefix_live.py::test_legacy_prefix_live_session` (opt-in, `PARROT_TEST_REAL_LLM=1`).

## Agent Instructions

Read the brief first. Touch only the listed files. The live test and the replay use real `claude` runs:
haiku, one short prompt each.

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 354s, merged (lint 1fb7e4ca87). Merge-tier validation green: 20 passed, 1 skipped (the live test, skipped without PARROT_TEST_REAL_LLM=1). The two sdd-worker.md copies are byte-identical (cmp). NOT verified by the worker session: AC1 (live test passing with PARROT_TEST_REAL_LLM=1 on the host) and the before/after counts in automode-rewrites.md, whose replay script is uncommitted and whose transcripts are not reachable from the sandbox. Run the live test on the host and spot-check the counts before merging.
