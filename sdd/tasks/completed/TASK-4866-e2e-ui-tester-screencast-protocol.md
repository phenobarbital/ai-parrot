# TASK-4866: `e2e-ui-tester` on-anomaly screencast protocol

**Feature**: FEAT-762 — Operational screencast logs for the E2E browser exploration flow
**Spec**: `sdd/specs/e2e-browser-screencast-logs.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-4865
**Assigned-to**: unassigned

## Context

Spec §3 Module 3. The exploration agent is Bash + Write only. To record, it must
write and run a short Playwright script that connects to the owned Obscura CDP
endpoint and wraps its investigation in `record_on_anomaly` (TASK-4865). A
DevTools MCP tool holds a different CDP connection and cannot be recorded.
`RunState.endpoint` is not populated by `parrot e2e up`, so the current step-1
instruction to read it is wrong and is corrected here.

## Scope

- Edit the "Exploration process" section and the report example of
  `.claude/agents/e2e-ui-tester.md` (prose only; no new top-level JSON field).
- Add a prose-contract unit test.

**NOT in scope**: recorder code, CLI changes, changes to other agents or to the
`e2e-exploration.json` schema beyond an additional `evidence_refs` entry.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/e2e-ui-tester.md` | MODIFY | Screencast step, endpoint correction, evidence_refs example. |
| `packages/ai-parrot-server/tests/unit/e2e/test_screencast_agent_protocol.py` | CREATE | Asserts the prose contract. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pathlib import Path   # stdlib; the test reads the agent file relative to the repo root
```

### Existing Signatures to Use

```text
.claude/agents/e2e-ui-tester.md:104   "1. Start the declared target and read its `RunState.endpoint` — for"   (occurrences: 1)
.claude/agents/e2e-ui-tester.md:116   "   Capture a screenshot on any unexpected finding."                     (occurrences: 1)
.claude/agents/e2e-ui-tester.md:148   '      "evidence_refs": ["artifacts/logs/e2e/browser-explore/screenshot.png"]'  (occurrences: 1)

# TASK-4865 public helper (spec §2):
record_on_anomaly(page, out_dir: Path, *, run_id: str, max_frames: int = 600) -> AnomalyRecorder
AnomalyRecorder.triggered: bool ; .path: Optional[Path] ; .error: Optional[E2EScreencastError]
```

Repo root from the test file: `Path(__file__).resolve().parents[5]`
(`e2e` → `unit` → `tests` → `ai-parrot-server` → `packages` → root).

### Does NOT Exist

- `parrot e2e screencast start|stop` CLI commands, daemons, tickets, `--page-target-id` — never mention them as usable.
- A populated `RunState.endpoint` — do not instruct the agent to read it.
- A way to record a DevTools-MCP-driven page.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/agents/e2e-ui-tester.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/e2e/test_screencast_agent_protocol.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Keep the agent's teardown rules intact: the recording script must finish (context manager exited)
  **before** `parrot e2e down --all --owner-id explore-e2e-ui-tester`.
- The CDP endpoint must come from explicit configuration (the plan/target's known port, e.g.
  `http://127.0.0.1:<port>`); if unknown, record `"recording unavailable"` and continue with screenshots.
- Label recordings as post-detection evidence; never claim they show events before the anomaly.
- Obscura only lets the most recently created page run JS: the script should create the page it
  investigates last.

## Implementation Blueprint

### Steps (in order)

1. Replace step 1's `RunState.endpoint` sentence with the explicit-endpoint rule — because `up` does not populate it.
2. After the screenshot sentence, add the recording paragraph + minimal script example.
3. Add a second, conditional `evidence_refs` entry to the JSON example.
4. Write the prose-contract test; run it.

### `.claude/agents/e2e-ui-tester.md` (MODIFY)

```markdown
<!-- AT line 104 — replace "read its `RunState.endpoint`" (occurrences: 1) with: -->
1. Start the declared target and use its explicitly configured endpoint (the
   plan/target's known port; `RunState.endpoint` is not populated) — for

<!-- AFTER "   Capture a screenshot on any unexpected finding." (line 116, occurrences: 1) -->
   **Operational screencast (FEAT-762).** Recording is possible only from a
   Playwright script you write and run with Bash, because Obscura isolates pages
   per CDP connection (a DevTools MCP connection cannot be recorded). Wrap the
   investigation in `parrot.e2e.screencast.record_on_anomaly`; it starts on the
   first console error or HTTP 5xx and always stops when the block exits:
   ```python
   # FILL IN: ~15-line example — connect_over_cdp(<explicit endpoint>), create the
   # investigated page LAST, `async with record_on_anomaly(page, Path("artifacts/logs/e2e/<run-id>"),
   # run_id="<run-id>") as rec:` ... then print rec.triggered / rec.path / rec.error
   ```
   Add `rec.path` to that observation's `evidence_refs` only when it is not
   `None`; report `rec.error` as an `unavailable` note. The video is
   post-detection evidence of follow-up investigation, never of earlier events.
   The script must exit before `parrot e2e down`.

<!-- AT line 148 (occurrences: 1) — extend the example array: -->
      "evidence_refs": ["artifacts/logs/e2e/browser-explore/screenshot.png", "artifacts/logs/e2e/browser-explore/screencast.webm"]
```

**Why**: the spec's M3 requires these three prose changes and nothing else; the agent's report schema stays unchanged.

### `packages/ai-parrot-server/tests/unit/e2e/test_screencast_agent_protocol.py` (CREATE)

```python
"""Prose-contract test for e2e-ui-tester's on-anomaly screencast protocol (FEAT-762 M3)."""

from __future__ import annotations

from pathlib import Path

AGENT = Path(__file__).resolve().parents[5] / ".claude" / "agents" / "e2e-ui-tester.md"


def test_exploration_screencast_protocol() -> None:
    """Agent prose uses record_on_anomaly, post-detection wording, explicit endpoint, no daemon CLI."""
    text = AGENT.read_text(encoding="utf-8")
    # FILL IN: assert "record_on_anomaly" in text; "post-detection" in text;
    # "screencast.webm" in text; "RunState.endpoint` is not populated" (or equivalent) in text;
    # "parrot e2e screencast start" not in text; "page-target-id" not in text;
    # the recording paragraph appears before the teardown step ("parrot e2e down --all") of step 4.
```

### FILL IN checklist

- [ ] Script example in the agent prose (≤ 20 lines, explicit endpoint, page created last).
- [ ] Test assertions.

## Acceptance Criteria

- [ ] AC-1: the agent prose documents recording via `record_on_anomaly`, started only on the first anomaly and finished before `parrot e2e down`.
- [ ] AC-2: `RunState.endpoint` instruction replaced by the explicit-endpoint rule.
- [ ] AC-3: `evidence_refs` gains the screencast path only on success; no new top-level JSON field.
- [ ] AC-4: no daemon/CLI screencast commands mentioned; DevTools-MCP limitation stated.
- [ ] AC-5: `test_exploration_screencast_protocol` passes; `ruff check` clean on the test.

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/e2e/test_screencast_agent_protocol.py -q`

## Test Specification

A single text-contract test (above). It must fail on the current file (no `record_on_anomaly`)
and pass after the edit.

## Agent Instructions

1. Wait for TASK-4865 (final helper signature); verify the three anchors before editing.
2. Modify only the two listed files.
3. Commit code only.

## Completion Note

**Completed**: 2026-10-28 — seats mistral (2 attempts) and glm failed/timed out (max_turns, no final output; task-tier validation `0 failure(s)` glitch), so attempt 4 was implemented by the orchestrator (sonnet) in the feature worktree for this standard-classification S task.
**Verification**: `test_exploration_screencast_protocol` passes; ruff clean. Prose edits: endpoint rule replacing `RunState.endpoint`, screencast paragraph with a script example, extra `evidence_refs` entry.
**Notes**: attempt branches of the failed seats were discarded unmerged.
