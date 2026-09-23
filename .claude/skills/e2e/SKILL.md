---
name: e2e
description: Portable, host-agnostic manual walkthrough for FEAT-581's deterministic E2E gate CLI (run/verify/up/status/logs/down) and its optional, owner-scoped API/UI exploration workflow. Use when a human or agent needs to run/verify E2E evidence by hand, or manually explore a fixture target without a Claude subagent.
---

# E2E — Deterministic Gate CLI and Optional Exploration

Use this skill when you need to run or verify FEAT-581's deterministic E2E
evidence by hand, or manually start/probe/stop one fixture target for
exploration — with no dependency on a Claude subagent. Everything here is
plain `parrot e2e ...` CLI usage plus a documented report contract, so it
works identically whether you are Claude Code, Codex, or a human at a
terminal (spec §2, §3 M8: "portable manual skill").

## Purpose

- Give the exact CLI invocations for the deterministic gate
  (`run`/`verify`) and the lower-level lifecycle commands
  (`up`/`status`/`logs`/`down`) that both `parrot.e2e.cli` and the two
  Claude subagents (`e2e-api-tester`, `e2e-ui-tester`) are built on.
- Give the exploration report contract (`e2e-exploration.json`) so a manual
  session produces the same machine-readable artifact those subagents do.
- Make owner identity and teardown explicit, so a manual session never
  needs `.claude/hooks/e2e-teardown.sh` (a Claude-only, defense-in-depth
  safety net) to clean up after it.

## Guardrails

- `ai-parrot-server` must be installed for the `e2e` command group to exist
  at all (it is registered lazily by core's `LazyGroup`). Run
  `parrot e2e status` first; a "command not found"/install-hint error means
  this skill's CLI usage is unavailable in this environment — report that
  plainly, do not fabricate output.
- Never start a target the relevant `E2EPlan` does not declare, and never
  point a target at a non-fixture/production endpoint.
- Never claim exploration output (`e2e-exploration.json`, screenshots,
  candidate tests) is gate evidence. Only `parrot e2e run`/`parrot e2e
  verify` produce a PASS/FAIL/BLOCKED verdict (spec §2).
- Candidate test files always live outside pytest discovery (never under
  `tests/` or any existing `testpaths` root) and are promoted into a real
  test file by a human only — never automatically.
- Always scope teardown to your own owner ID and this worktree: `parrot e2e
  down --all --owner-id <id>` or a specific `RUN_ID`. Never a bare,
  unscoped kill, and never `--stale` as a substitute for your own explicit
  cleanup (`--stale` is the documented recovery path for an *abandoned*
  run from a *different*, earlier invocation, not your own bounded
  session).

## Running the deterministic gate

```bash
# Read-only: validate an existing run's evidence without executing anything.
parrot e2e verify --plan sdd/state/FEAT-<NNN>/e2e-plan.md

# Foreground, bounded run: executes the plan's declared scenarios and
# atomically records evidence; JSON verdict on stdout, diagnostics on stderr.
PARROT_TEST_E2E=1 parrot e2e run --plan sdd/state/FEAT-<NNN>/e2e-plan.md --owner-id <your-id>
```

Exit codes follow spec §2's table (`0` PASS / explicit `none` policy, `1`
FAIL, `2` invalid plan/config, `3` BLOCKED missing prerequisite, `4`
missing/stale evidence, `130`/`143` interrupted). A required live scenario
additionally needs `PARROT_TEST_REAL_LLM=1` and the provider key — never
run those without the explicit opt-in flags.

## Manually starting, probing and stopping one fixture target

```bash
# Start one target from the plan's own TargetConfig (or an ad hoc overlay);
# prints one RunState JSON line once ready.
parrot e2e up <target> --owner-id <your-id> --run-id <target>-explore

# Inspect state for one run, or every run in this worktree.
parrot e2e status <run-id>
parrot e2e status

# Tail a run's captured target log.
parrot e2e logs <run-id> --tail 200

# Stop exactly what you started, everything you own, or reconcile stale
# owned runs left over from an earlier invocation.
parrot e2e down <run-id> --owner-id <your-id>
parrot e2e down --all --owner-id <your-id>
parrot e2e down --stale --owner-id <your-id>
```

`up` targets carry a default 600-second lease (maximum 3600s, spec §2) — do
not fight it; stop and restart the target if you need longer. Omitting
`--owner-id` defaults to `$PARROT_E2E_OWNER_ID` or your OS user name
(sanitized); an explicit, stable ID is strongly preferred for a scripted or
repeatable manual session, and is required if you also intend the Claude
teardown hook's convention (`explore-<agent-type>`) to apply.

## Exploration report contract — `e2e-exploration.json`

If you are exploring (not just running the deterministic gate), write your
findings to
`sdd/state/<FEAT-ID>/e2e/exploration/<run-id>/e2e-exploration.json` — a
sibling of, never inside, the deterministic gate's own
`sdd/state/<FEAT-ID>/e2e/runs/<run-id>/` evidence tree. This schema carries
**no** `passed`/`status`/`gate_satisfied` field of any kind (spec §3 M8):

```json
{
  "schema_version": 1,
  "feature_id": "FEAT-<NNN>",
  "run_id": "<your ticket/run id>",
  "agent": "manual",
  "owner_id": "<your-id>",
  "started_at": "<UTC ISO-8601>",
  "finished_at": "<UTC ISO-8601>",
  "targets_probed": ["mcp-toolkit"],
  "observations": [
    {"target_id": "mcp-toolkit", "summary": "...", "evidence_refs": ["artifacts/logs/e2e/<run-id>/..."]}
  ],
  "reproduction_commands": ["parrot e2e up mcp-toolkit --owner-id <your-id> --run-id mcp-toolkit-explore"],
  "candidates": [
    {"path": "sdd/state/FEAT-<NNN>/e2e/exploration/<run-id>/candidates/test_new_case.py", "rationale": "..."}
  ],
  "unavailable": null
}
```

Set `"agent"` to whatever ran this session (`"manual"`, `"e2e-api-tester"`,
`"e2e-ui-tester"`, etc.) and set `"unavailable"` to a small
`{"reason": "..."}` object (instead of populating the rest of the report)
when a genuine prerequisite is missing — never fabricate an exploration
result to fill this field.
