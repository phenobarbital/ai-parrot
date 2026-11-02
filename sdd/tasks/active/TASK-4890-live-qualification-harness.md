# TASK-4890: Opt-in live qualification harness

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4888, TASK-4889
**Assigned-to**: unassigned

---

## Context

Spec §3 M4 and §4 "Live qualification gate". Fake-CLI tests cannot prove what Claude's runtime
enforces. This task writes the opt-in pytest file that drives the REAL launch paths (the
interactive launcher and the dispatcher's SDK-bundled CLI) against fixture repositories with
canaries, under a hard budget. It only writes the harness; TASK-4891 runs it on a qualified host
and writes the report. The preflight harness (`sdd/state/FEAT-768/native-sandbox-preflight.md`,
"Harness") is the proven starting point — but it used relaxed sockets; this file never does.

---

## Scope

- Create `test_native_claude_sandbox_live.py`, skipped unless `PARROT_TEST_REAL_LLM=1`.
- Enforce the budget in code: ≤ 8 sessions per run, `--max-turns 12`, 180 s per session, stop when
  accumulated `total_cost_usd` reaches USD 5; report remaining cases instead of running them.
- Cover every scenario row of spec §4's live table, on a selectable executable
  (`PARROT_NATIVE_QUAL_CLI=path|bundled`, default `path`).
- Write sanitized per-scenario JSON (command, exit status, canary results, settings digest, CLI
  version, cost) under `artifacts/logs/feat-768/`; never write raw transcripts with credentials.

**NOT in scope**: running the gate (TASK-4891), host remediation (AppArmor), docs, any production code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py` | CREATE | Opt-in live probes with budget guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop import native_claude_sandbox as native        # TASK-4885/4889
from parrot.flows.dev_loop import worktree_environment as policy         # dispatchers/claude.py:66
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher  # test_worktree_environment.py:20
from parrot.flows.dev_loop.models import ClaudeCodeDispatchProfile       # models/__init__.py:64
```

### Existing Signatures to Use
```python
# From TASK-4885/4888/4889:
def native_sandbox_settings(cwd: Path, *, allowed_domains: Sequence[str] = ()) -> dict[str, Any]: ...
def launch_worker(argv: Sequence[str]) -> int: ...            # exec's PATH `claude`
ClaudeCodeDispatcher._resolve_run_options(profile, cwd) -> ClaudeAgentRunOptions   # dispatchers/claude.py:562
# Executables (preflight): PATH `claude` 2.1.312; SDK-bundled
#   <venv>/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude  (2.1.301, claude-agent-sdk 0.2.168)
# CLI probe form proven by the preflight:
#   claude -p <prompt> --model haiku --max-turns 12 --setting-sources <src> --settings <json>
#          --permission-mode bypassPermissions --output-format stream-json --verbose < /dev/null
# stream-json: `tool_result` text is the evidence (transcript tool_use.input keeps the PRE-rewrite command);
#   final {"type":"result","total_cost_usd":...}
```

### Does NOT Exist
- ~~a native sandbox attestation API~~ — prove isolation with canaries and command results only.
- ~~`PARROT_NATIVE_QUAL_CLI`~~ — new env var defined by this file.
- ~~an existing `artifacts/logs/feat-768/` directory~~ — create it at run time.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/claude.py#ClaudeCodeDispatcher._resolve_run_options"
  ]
}
```

---

## Implementation Notes

- Programmatic path: build the exact argv the SDK would run from `_resolve_run_options` output
  (`extra_args["settings"]`, `env`) and invoke the bundled CLI with it; do not call a provider SDK
  directly (spec: AbstractClient path or the launcher under test).
- Interactive path: run `scripts/sdd/launch_worker.sh -p <prompt> --model haiku --max-turns 12
  --permission-mode bypassPermissions --output-format stream-json --verbose` from the fixture
  linked worktree, with PATH pointing at the selected executable.
- Competing rewrite: a fixture `local` settings hook (outside the compiled policy) that prefixes
  `echo COMPETING_MARK;` — a scenario without that marker in the result is INCONCLUSIVE, not pass.
- Native child: prompt the parent to use the `Agent` tool; inconclusive without a child tool call
  (`parent_tool_use_id` set). Children must `cd <pool worktree> &&` (spec policy 4).
- Egress: one allowed test host via `allowed_domains`, one unlisted host, one proxy-bypassing
  direct request (e.g. `curl --noproxy '*'`).
- Retry: model asked to retry with `dangerouslyDisableSandbox: true` under `bypassPermissions`.
- Missing prerequisites (strict sandbox cannot start) → record NOT QUALIFIED and skip the rest.

---

## Implementation Blueprint

### Steps (in order)
1. Module-level skip + budget object — *why*: no accidental provider spend.
2. Fixture: temp primary repo (`git init`), linked feature + pool worktrees (`git worktree add`),
   fake shared `.venv` with sentinel `.pth` and a symlink to it, fake RTK data dir via
   `XDG_DATA_HOME`, disposable bare remote — *why*: canaries never touch operator files.
3. One helper that runs a session and returns parsed results; one test per scenario row.
4. Each test writes its sanitized record to `artifacts/logs/feat-768/`.

### `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py` (CREATE)
```python
"""FEAT-768 live native-sandbox qualification probes (opt-in, spends provider budget).

Run only with PARROT_TEST_REAL_LLM=1. Strict settings only — never allowAllUnixSockets.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
import subprocess

import pytest

from parrot.flows.dev_loop import native_claude_sandbox as native

pytestmark = pytest.mark.skipif(
    os.environ.get("PARROT_TEST_REAL_LLM") != "1", reason="live provider probes require PARROT_TEST_REAL_LLM=1"
)

MAX_SESSIONS = 8
MAX_TURNS = 12
SESSION_TIMEOUT_SECONDS = 180
MAX_COST_USD = 5.0
LOG_DIR = Path("artifacts/logs/feat-768")


@dataclass
class Budget:
    """Process-wide spend guard shared by every live test."""

    sessions: int = 0
    cost_usd: float = 0.0
    skipped: list[str] = field(default_factory=list)

    def admit(self, scenario: str) -> None:
        """Skip `scenario` once the session or cost budget is spent, recording it as remaining."""
        if self.sessions >= MAX_SESSIONS or self.cost_usd >= MAX_COST_USD:
            self.skipped.append(scenario)
            pytest.skip(f"live budget exhausted before {scenario}")
        self.sessions += 1


BUDGET = Budget()


@dataclass
class SessionResult:
    """Sanitized outcome of one live session."""

    exit_status: int
    tool_results: list[str]
    child_tool_calls: int
    cost_usd: float


def run_session(argv: list[str], cwd: Path, env: dict[str, str]) -> SessionResult:
    """Run one CLI session (stream-json) under the timeout and parse tool results and cost."""
    # FILL IN: subprocess.run(argv, cwd=cwd, env=env, stdin=DEVNULL, capture_output=True, text=True,
    # timeout=SESSION_TIMEOUT_SECONDS); parse stream-json lines; add cost to BUDGET.cost_usd —
    # bounded by spec §4 (tool results are evidence, not tool_use.input)
    raise NotImplementedError


# FILL IN: fixtures (qual_repo with canaries + positive controls) and one test per row of spec §4's
# live table: competing rewrite, native Agent child, filesystem matrix, Git controls, file-tool
# bypass, settings widening, retry/failure, egress, compatibility; each test calls BUDGET.admit(),
# records its sanitized JSON in LOG_DIR, and marks INCONCLUSIVE (pytest.xfail with reason) when the
# required observation (marker / child call) is absent — bounded by spec §4 and AC2-AC8
```
**Why**: the budget guard and skip are mechanical and must not be weakened; scenario bodies need
investigation against the real runtime, so they stay `FILL IN`.

### FILL IN checklist
- [ ] `run_session` parsing and cost accounting
- [ ] fixture repo with canaries and positive controls (each denied target writable without isolation)
- [ ] one test per live scenario row, both launch paths selectable
- [ ] sanitized JSON records; no credentials

---

## Acceptance Criteria

- [ ] Without `PARROT_TEST_REAL_LLM=1` every test is skipped and no subprocess starts.
- [ ] Budget: a 9th session or cost ≥ USD 5 skips with the scenario listed as remaining.
- [ ] Every spec §4 live scenario has a test; missing marker/child call → inconclusive, never pass.
- [ ] Strict settings only (assert `allowAllUnixSockets` is false in the compiled settings used).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py -q`

(Without `PARROT_TEST_REAL_LLM=1` this must report only skips.)

---

## Test Specification

```python
async def test_live_native_rewrite_and_child_boundary(tmp_path: Path) -> None:
    """Opt-in real Claude probe: rewritten parent/child commands cannot mutate protected canaries."""

def test_live_filesystem_matrix(qual_repo) -> None: ...
def test_live_git_controls(qual_repo) -> None: ...
def test_live_file_tool_bypass(qual_repo) -> None: ...
def test_live_settings_widening(qual_repo) -> None: ...
def test_live_retry_and_failure(qual_repo) -> None: ...
def test_live_egress(qual_repo) -> None: ...
def test_live_compatibility(qual_repo) -> None: ...
```

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-4888 and TASK-4889 are `done`.
2. Do NOT run the file with `PARROT_TEST_REAL_LLM=1` — that is TASK-4891.
3. Run the Validation Command (skips only) with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the listed file; close with `scripts/sdd/close_task.sh TASK-4890 sdd-claude-native-sandbox verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
