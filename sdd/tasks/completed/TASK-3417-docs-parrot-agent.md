# TASK-3417: Documentation — `docs/cli/parrot-agent.md` and the `agentd` attach note

**Feature**: FEAT-573 — Agent Terminal Workspace for `parrot agent`
**Spec**: `sdd/specs/new-ui-cli-agents.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3413, TASK-3415
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 17 / AC26. There is no user-facing documentation for
`parrot agent` today (`docs/` has no `cli/` directory; `docs/agent.md` is the
AgentTalk HTTP guide; `docs/agentd.md` documents the daemon and mentions the
console only in passing). This task writes the CLI guide covering everything
this feature adds and adds a one-line note to `docs/agentd.md` that `parrot
attach` now prints queued job events through `AgentREPL.add_post_turn_hook`
(TASK-3415). A tiny test pins the doc's presence and key terms so the guide
cannot silently drift from the flags.

---

## Scope

- Create `docs/cli/parrot-agent.md`: modes (`--ui auto|inline|tui`, detection
  rules, `TERM=dumb`), keybindings table, resume (`--session <id>|last`,
  `/resume`), history location (`$PARROT_HOME/cli/history/<slug>.txt`,
  `--no-history`), server mode (routes, `--token`/`PARROT_SERVER_TOKEN`, why
  `--user` is refused), non-TTY usage (line mode, exit codes), troubleshooting.
- Modify `docs/agentd.md`: one bullet under the console-engine line.
- Add `packages/ai-parrot/tests/cli/test_docs_parrot_agent.py`.

**NOT in scope**: any code change; `README` changes; MkDocs/nav configuration
(none exists for `docs/cli`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/cli/parrot-agent.md` | CREATE | User guide for the `parrot agent` workspace and inline console |
| `docs/agentd.md` | MODIFY | Note that `attach` uses `AgentREPL.add_post_turn_hook` |
| `packages/ai-parrot/tests/cli/test_docs_parrot_agent.py` | CREATE | Presence + key-term assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path   # stdlib
import pytest              # verified: tests/cli/test_integration.py:14
```

### Existing Signatures to Use
```text
# docs/agentd.md (verified 2026-09-18)
line 35  : `parrot attach my-agent`   (quickstart; occurrences of that exact text: 2 — lines 35 and 237)
line 405 : `- Console engine reused as-is: `parrot.cli.repl.AgentREPL` (see `parrot agent`)`   (occurrences: 1 — the anchor)

# Facts the guide must state (all fixed by the spec; do not invent others)
--ui auto|inline|tui   default auto — TUI iff stdin and stdout are TTYs and TERM != dumb           (spec §3 M2/M13, AC1)
--session ID|last      resume from bot memory; standalone only (server/daemon: resume=False)      (spec §8 Q9, AC9)
--user USER_ID         standalone only; refused with --server (exit 2)                            (spec §8 Q8, AC27)
--token TOKEN          env PARROT_SERVER_TOKEN; Authorization: Bearer                             (spec §3 M9, AC16)
--no-history           disables $PARROT_HOME/cli/history/<slug>.txt (0600)                        (spec §3 M2, AC10)
--list / --server URL / --no-stream   unchanged                                                    (G10)
Keys (TUI): enter send · ctrl+j / shift+enter newline · up/down history · tab complete `/` · pageup/pagedown scroll ·
            end follow · ctrl+c cancel (idle: twice quits) · ctrl+d quit · f2 tools · f3 logs · ctrl+l = /clear   (spec §3 M11)
Slash commands: /tools /info /clear /export [path] /stream /resume <id|last> /help /quit (/exit) /create_agent ; agentd adds /status /schedules /invoke
Server routes: GET /api/v1/bots · GET /api/v1/chatbots/{name} · POST /api/v1/agents/chat/{agent_id} · POST /bots/{bot_id}/stream/sse
Non-TTY: name required (exit 2); --ui tui refused (exit 2); one query per stdin line; plain output; exit 1 if any turn failed
Exit codes: 0 ok · 1 load/REPL error or failed batch turn · 2 usage error
```

### Does NOT Exist
- ~~`docs/cli/`~~ — directory does not exist yet; create it.
- ~~a MkDocs `nav` entry to update~~ — no `mkdocs.yml` governs `docs/cli`; do not add one.
- ~~`--resume` flag~~ — the flag is `--session`; the slash command is `/resume`.
- ~~server-mode resume or daemon live tool events~~ — explicitly out of v1 (spec §8 Q9/Q10); the guide must say so, not promise them.
- ~~`shift+enter` guaranteed~~ — terminal-dependent; `ctrl+j` is the guaranteed newline key (spec §7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/cli/parrot-agent.md", "action": "CREATE"},
    {"path": "docs/agentd.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/cli/test_docs_parrot_agent.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Inside a worktree run `PYTHONPATH=packages/ai-parrot/src pytest ...`; never `uv sync` there. This task's test imports nothing from `parrot` and does not need `textual` (no `importorskip` required), but keep the venv rules anyway.
- Document only behaviour that TASK-3413/3415 actually shipped; when a flag or key differs from the table above, the code wins — update the guide and note the deviation in the Completion Note.
- The docs test resolves the repo root from `Path(__file__)` (`parents[4]` from `packages/ai-parrot/tests/cli/`) — verify the depth before relying on it.

### References in Codebase
- `docs/agentd.md:230-245, 400-410` — existing tone and the `parrot attach` description.
- `docs/guides/cli-agent-daemon.md` — sibling CLI guide to match in style.
- `sdd/specs/new-ui-cli-agents.spec.md` §3 M11 (bindings), §3 M13 (options), §8 Q8/Q9/Q10 (limits).

---

## Implementation Blueprint

### Steps (in order)
1. Write `docs/cli/parrot-agent.md` from the facts table — *why*: every statement must trace to a spec decision; nothing speculative.
2. Add the `docs/agentd.md` bullet — *why*: `attach` behaviour changed in TASK-3415 and the daemon doc claims "reused as-is".
3. Write the docs test — *why*: AC26 is otherwise unverifiable by `pytest`.

### `docs/cli/parrot-agent.md` (CREATE)
```markdown
# `parrot agent` — Agent Terminal Workspace

`parrot agent <name>` opens an interactive session with a registered agent. On a
real terminal it starts a full-screen **workspace** (Textual); when piped, or
with `--ui inline`, it runs the classic **inline console** (Rich + prompt_toolkit).

## Usage

    parrot agent [NAME] [--ui auto|inline|tui] [--session ID|last] [--user USER_ID]
                 [--server URL] [--token TOKEN] [--no-stream] [--no-history] [--list]

| Option | Default | Meaning |
|---|---|---|
| `--ui` | `auto` | `auto` picks `tui` when stdin **and** stdout are TTYs and `TERM` is not `dumb`, else `inline`. |
| `--session ID\|last` | — | Resume a prior conversation from the agent's memory (`last` = the last session used with this agent). Standalone mode only. |
| `--user` | `cli-user` | Identity sent with each request. **Refused with `--server`** (exit 2): identity there comes from the token. |
| `--server URL` / `--token` | — | Talk to a running server; `--token` (or `PARROT_SERVER_TOKEN`) is sent as `Authorization: Bearer`. |
| `--no-stream` | off | Wait for the full answer instead of streaming. |
| `--no-history` | off | Do not persist composer history. |
| `--list` | — | List registered agents and exit. |

## Keys (workspace)
<!-- FILL IN: table of the spec §3 M11 bindings from the facts table; state that ctrl+j is the guaranteed newline key -->

## Slash commands
<!-- FILL IN: list from the facts table; note /clear starts a new session id, /export keeps its JSON shape -->

## Conversation resume vs. input history
<!-- FILL IN: resume = bot-owned memory via --session//resume; history = $PARROT_HOME/cli/history/<slug>.txt (mode 0600), independent -->

## Server mode
<!-- FILL IN: the four routes, token, why --user is refused, "resume not available in server mode", live tool progress via SSE -->

## Non-interactive use (pipes and scripts)
<!-- FILL IN: name required, one query per line, plain output without escape sequences, exit codes 0/1/2, --ui tui refused -->

## Troubleshooting
<!-- FILL IN: TERM=dumb → inline; garbled screen → --ui inline; "No previous session" → run once without --session -->
```
**Why this shape**: headings mirror AC26's checklist (modes, keys, resume, history location, server mode, non-TTY); the option table is complete because it is what the test greps.

### `docs/agentd.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c 'Console engine reused as-is' docs/agentd.md)
# AFTER — insert below `- Console engine reused as-is: `parrot.cli.repl.AgentREPL` (see `parrot agent`)` (verified: docs/agentd.md:405)
- Queued job events (`event.job_executed`, `event.job_error`, `event.shutdown`) are printed between turns via
  `AgentREPL.add_post_turn_hook` (FEAT-573); the former instance-level `send`/`send_stream` wrapper is gone.
```
**Why**: keeps the daemon doc truthful after TASK-3415 deletes `_wrap_with_event_drain`.

### `packages/ai-parrot/tests/cli/test_docs_parrot_agent.py` (CREATE)
```python
"""AC26 — the `parrot agent` guide exists and names the feature's flags and keys (FEAT-573)."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]  # packages/ai-parrot/tests/cli/ → repo root
DOC = REPO_ROOT / "docs" / "cli" / "parrot-agent.md"


def test_guide_exists() -> None:
    assert DOC.is_file(), f"missing {DOC}"


@pytest.mark.parametrize(
    "term",
    ["--ui", "--session", "--token", "PARROT_SERVER_TOKEN", "PARROT_HOME", "--no-history", "/resume", "--server"],
)
def test_guide_mentions_flag(term: str) -> None:
    assert term in DOC.read_text(encoding="utf-8")


def test_guide_documents_newline_key() -> None:
    text = DOC.read_text(encoding="utf-8").lower()
    assert "ctrl+j" in text


def test_agentd_doc_mentions_post_turn_hook() -> None:
    assert "add_post_turn_hook" in (REPO_ROOT / "docs" / "agentd.md").read_text(encoding="utf-8")
```
**Why**: cheap, deterministic, no `parrot` import; `parents[4]` is verified by the path depth `packages/ai-parrot/tests/cli/test_*.py`.

### FILL IN checklist
- [ ] `docs/cli/parrot-agent.md` — the six commented sections; bounded by the facts table (spec §3 M2/M11/M13, §8 Q8–Q10)

---

## Acceptance Criteria

- [ ] `docs/cli/parrot-agent.md` documents modes, keys, resume, history location, server mode and non-TTY usage (AC26)
- [ ] `docs/agentd.md` mentions `add_post_turn_hook` (AC15 companion)
- [ ] `pytest packages/ai-parrot/tests/cli/test_docs_parrot_agent.py -q` passes

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_docs_parrot_agent.py -q`

---

## Test Specification

See the blueprint: guide exists; eight key terms present; `ctrl+j` documented; agentd note present.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in the per-spec index → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3417-docs-parrot-agent.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: MCP seat `gemini` (backend google-compat, model gemini-3.5-flash, attempt ac2a456c8517476a87472bd589393357)
**Date**: 2026-09-18
**Notes**: Created `docs/cli/parrot-agent.md` (usage, keybindings, slash
commands, resume vs. history, server mode routes, non-interactive rules,
troubleshooting) and updated `docs/agentd.md` with the `add_post_turn_hook`
migration note (TASK-3415). Added `test_docs_parrot_agent.py` guard test.

Orchestrator spot-checked the documented keybindings against
`AgentWorkspaceApp.BINDINGS` (`app.py`) — exact match (pageup/pagedown,
end, ctrl+c, ctrl+d, f2, f3, ctrl+l). Merge clean via the engine (auto
lint fix applied). `pytest test_docs_parrot_agent.py`: 11 passed.

**Feedback recorded**: none — clean delivery, spot-checked accurate.
**Deviations from spec**: none.
