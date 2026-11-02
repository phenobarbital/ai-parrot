# TASK-4891: Run the strict live qualification and write the report

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h, plus operator host remediation)
**Depends-on**: TASK-4890
**Assigned-to**: unassigned (requires the operator)

---

## Context

Spec §4 "Live qualification gate", §8 remaining gates, AC2/AC3/AC6/AC7/AC10. The preflight
answered the open questions with relaxed sockets; this task produces the evidence that gates the
merge: strict runs on BOTH executables (PATH `claude` and the SDK-bundled CLI) on the maintainer
workstation after the operator installs an AppArmor profile for Claude's seccomp helper, plus the
restricted-host failure evidence. The feature must not merge to `dev` without a QUALIFIED verdict
for both paths, because TASK-4888 makes the native sandbox mandatory for sandboxed seats.

---

## Scope

- Confirm the operator has installed the AppArmor profile (root action, outside this task — never
  run it yourself). Record the profile name, not its contents if they include local paths you have
  not confirmed with the operator.
- Record host facts: OS, `apparmor_restrict_unprivileged_userns`, bwrap/socat versions, both CLI
  versions, `claude-agent-sdk` version.
- Run `test_native_claude_sandbox_live.py` with `PARROT_TEST_REAL_LLM=1`, once per executable
  (`PARROT_NATIVE_QUAL_CLI=path` and `=bundled`), within the budget (8 sessions / USD 5 per run).
- Record restricted-host behavior (strict start failure before remediation, or reference the
  preflight/6756c929a450 evidence if remediation already happened, saying so).
- Write `sdd/state/FEAT-768/native-sandbox-qualification.md`: version, prerequisites, settings
  digest (sha256 of the compiled settings JSON with paths), exact commands, exit statuses, canary
  assertions, per-scenario verdict (PASS / FAIL / INCONCLUSIVE / NOT RUN), overall verdict per path.

**NOT in scope**: changing production code. If a scenario FAILS, stop: record it, open a ledger
issue (`wikitoolkit ledger open … --discovered-from spec:FEAT-768`), set this task
`done-with-issues` and report — do not weaken the policy to pass (spec §8 note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-768/native-sandbox-qualification.md` | CREATE | Qualification report (AC10) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none — this task runs the TASK-4890 harness and writes a report
```

### Existing Signatures to Use
```text
packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py   (TASK-4890)
  env: PARROT_TEST_REAL_LLM=1, PARROT_NATIVE_QUAL_CLI=path|bundled
  writes sanitized records to artifacts/logs/feat-768/
sdd/state/FEAT-768/native-sandbox-preflight.md   (host table, relaxed-socket results — reference, do not rewrite)
sdd/state/6756c929a450/native-sandbox-research.md (Q0: strict start failure on the unprofiled host)
```

### Does NOT Exist
- ~~an automated AppArmor installer in this repo~~ — the operator does it by hand (spec AC12: no system-security mutation by the feature).
- ~~a passing result from skipped or inconclusive scenarios~~ — they are NOT passes (AC10).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/state/FEAT-768/native-sandbox-qualification.md", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Exclusive (`parallel: false`): consumes the provider budget and depends on host state.
- Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-anthropic/src`.
- If either executable updates mid-task, the earlier run no longer qualifies that path (policy 9).

---

## Implementation Blueprint

### Steps (in order)
1. Ask the operator to confirm the AppArmor profile is installed — *why*: strict mode cannot start otherwise (preflight Q0).
2. Record host facts — *why*: AC10 needs exact versions per path.
3. Run the harness for `path`, then for `bundled` — *why*: the two executables are qualified separately (policy 9).
4. Write the report; commit only the report file.

### `sdd/state/FEAT-768/native-sandbox-qualification.md` (CREATE)
```markdown
# FEAT-768 native sandbox — qualification report

Date: <YYYY-MM-DD>. Verdict: interactive (PATH claude <ver>) <QUALIFIED|NOT QUALIFIED>;
programmatic (bundled <ver>, claude-agent-sdk <ver>) <QUALIFIED|NOT QUALIFIED>.

## Host
<!-- FILL IN: OS, userns sysctls, AppArmor profile name, bwrap, socat -->

## Restricted-host evidence
<!-- FILL IN: strict start failure before remediation (or cite the 6756c929a450 Q0 record) -->

## Settings
<!-- FILL IN: sha256 of compiled settings per path; confirm allowAllUnixSockets false -->

## Scenarios
| Scenario | Path | Command | Exit | Canary result | Verdict |
|---|---|---|---|---|---|
<!-- FILL IN: one row per spec §4 live scenario per path -->

## Budget
<!-- FILL IN: sessions and USD per run; remaining cases if the budget stopped a run -->
```

### FILL IN checklist
- [ ] host facts, restricted-host evidence, settings digests
- [ ] every scenario × path row with its verdict
- [ ] overall verdict per path

---

## Acceptance Criteria

- [ ] Report exists with both executables' versions and verdicts (AC10).
- [ ] Every spec §4 scenario has a row per path; skipped/inconclusive are not counted as passes.
- [ ] Strict settings used (no `allowAllUnixSockets: true`) in every QUALIFIED run.
- [ ] No raw transcript or credential committed.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py -q`

(Run it with `PARROT_TEST_REAL_LLM=1` and `PARROT_NATIVE_QUAL_CLI=path`, then `=bundled`; without the
variable it only skips.)

---

## Test Specification

No new tests; the TASK-4890 harness is the test.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4890 is `done`.
2. Confirm the AppArmor profile with the operator before spending budget.
3. Run, write the report, commit only `sdd/state/FEAT-768/native-sandbox-qualification.md`.
4. Close with `scripts/sdd/close_task.sh TASK-4891 sdd-claude-native-sandbox verified` (or `partial`
   with a ledger issue when a scenario failed or a path is NOT QUALIFIED).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
