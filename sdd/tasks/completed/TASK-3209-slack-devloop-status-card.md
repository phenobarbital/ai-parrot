# TASK-3209: Live status card in the run thread (debounced `chat.update`)

**Feature**: FEAT-555 — Dev-Loop Slack Kick-off
**Spec**: `sdd/specs/dev-loop-slack.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3207
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 13** — the "nice-to-have" from the original request, decided in for v1 as the
last, optional module: one message per run in the thread listing the flow's nodes with
✅ completed / 🔄 running / ⚪ idle / ❌ failed / ⏭ skipped, created on the first `node_changed`
event and edited in place. `chat.update` is Tier 3 rate-limited (~50/min per channel), so edits
are debounced to at most one per 2 s per run and coalesced (design research S10). The card is
best-effort: a failed edit never affects the run, and `config.status_card: false` disables it
with no other behaviour change (AC16).

`SlackDevLoopTransport.update_status` (TASK-3207) is a documented no-op until this task.

---

## Scope

- MODIFY `slack/devloop/blocks.py`: add `status_card_blocks(record, nodes)`.
- MODIFY `slack/devloop/transport.py`: implement `SlackDevLoopTransport.update_status(record, state)` with a
  2 s trailing-edge debounce per `run_id`, create-or-update of `record.status_message_ts`, `ratelimited` →
  back off using `Retry-After` and drop, gated by `config.status_card`.
- Unit tests in `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_status_card.py`.

**NOT in scope**: any change to `RunEvent`/`RunRecord` models (TASK-3200), the tail (TASK-3203),
the service (TASK-3204), other transport methods.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/blocks.py` | MODIFY | `status_card_blocks` |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/transport.py` | MODIFY | `update_status` implementation + debounce state |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_status_card.py` | CREATE | debounce/coalesce tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.integrations.slack.devloop.transport import SlackDevLoopTransport         # TASK-3207
from parrot.integrations.slack.devloop import blocks                                   # TASK-3206/3207
from parrot.integrations.devloop.models import RunRecord                               # TASK-3200 (spec §2)
from parrot.integrations.slack.wrapper import SlackAgentWrapper                        # verified: slack/wrapper.py:72
# stdlib: asyncio, time, typing
```

### Existing Signatures to Use
```python
# TASK-3205 — packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
class SlackAgentWrapper:
    async def post_message(self, channel, text, blocks=None, thread_ts=None) -> Optional[str]
    async def update_message(self, channel, ts, text, blocks=None) -> bool          # False on failure; rate-limit ⇒ log + False
    async def _slack_api(self, method, payload) -> Optional[dict]                   # returns None on error; FILL IN in TASK-3205 attaches retry_after
    #   self.config.devloop: DevLoopIntegrationConfig (TASK-3200) — .status_card: bool

# TASK-3207 — slack/devloop/transport.py
class SlackDevLoopTransport:
    def __init__(self, wrapper: SlackAgentWrapper) -> None
    async def _post_in_thread(self, record: RunRecord, text: str, kit: list[dict]) -> str | None
    async def update_status(self, record: RunRecord, state: dict[str, Any]) -> None   # currently `return None`

# spec §2 — RunRecord.status_message_ts: str = "" ; RunEvent(kind="node_changed", node_id, node_status, state?) ;
# DevLoopSessionState.model_dump()["nodes"] = {node_id: {"status": "idle|running|completed|failed|skipped", ...}}   # verified: session_state.py:243, :330
# NodeStatus = Literal["idle", "running", "completed", "failed", "skipped"]                                          # verified: flows/dev_loop/session_state.py:161
```

### Does NOT Exist
- ~~`SlackDevLoopTransport._status_debounce` / `_status_ts`~~ — created here.
- ~~a `Retry-After` value exposed by `wrapper.update_message`~~ — it returns `bool`; read the header/`retry_after` only if TASK-3205 completed its FILL IN on `_slack_api`; otherwise treat any `False` as "drop this edit and back off 5 s".
- ~~node order in `state["nodes"]`~~ — dict order is insertion order of first appearance in the reducer; render in the order of the dev-flow graph (`dev_intake`, `ideation`, `planner`, `development`, `synthesis`, `qa`, `feature_handoff`, `close` — `server_dev.py:1093-1096`) or dev-loop bug graph, then any unknown nodes last.
- ~~`RunRecord.status_message_ts` persisted by the transport~~ — the *service* saves records (TASK-3204); the transport mutates the field in memory and the next `registry.save` persists it.

---

## Implementation Notes

### Pattern to Follow
```python
# trailing-edge debounce with coalescing, one task per run_id
self._status_pending[run_id] = (record, nodes)
if run_id not in self._status_timers:
    self._status_timers[run_id] = asyncio.create_task(self._flush_status_later(run_id))
```

### Key Constraints
- Never raise from `update_status`; log at DEBUG on drop.
- Debounce 2 s trailing edge: the first event schedules a flush 2 s later; later events within the window only replace the pending payload.
- `ratelimited`: sleep `retry_after` (default 5 s) then drop; do NOT retry-storm.
- Glyph table: `completed` ✅, `running` 🔄, `idle` ⚪, `failed` ❌, `skipped` ⏭ (Slack emoji names `:white_check_mark:`, `:arrows_counterclockwise:`, `:white_circle:`, `:x:`, `:next_track_button:`).
- On terminal events the service calls `update_status` once more with the final state; flush immediately (no debounce) when `record.phase` is terminal.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py:628-711` — `_send_typing_indicator` (message create/update/delete pattern)
- `examples/dev_loop/static/dev.html` — the HTML console's node tiles (visual reference only)

---

## Implementation Blueprint

> Write each block below to its declared path nearly verbatim, then complete every
> `# FILL IN:` marker. Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `status_card_blocks` to `blocks.py` — *why*: pure rendering, testable without Slack.
2. Replace the no-op `update_status` in `transport.py` and add the debounce state to `__init__` — *why*: the service already calls it on every `node_changed`.
3. Tests, then `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_status_card.py -q`.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/blocks.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3207 lands: grep -c '^def terminal_blocks' packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/blocks.py)
# AFTER — append at END OF FILE (below `def terminal_blocks(...)`)
_NODE_GLYPH = {"completed": ":white_check_mark:", "running": ":arrows_counterclockwise:", "idle": ":white_circle:",
               "failed": ":x:", "skipped": ":next_track_button:"}
_NODE_ORDER = ["dev_intake", "ideation", "planner", "research", "intent_classifier", "bug_intake", "development",
               "synthesis", "qa", "feedback_router", "feature_handoff", "deployment_handoff", "close"]


def status_card_blocks(record: RunRecord, nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One line per node in graph order: '<glyph> `node_id`' — completed green, running spinning, remaining idle."""
    ordered = [n for n in _NODE_ORDER if n in nodes] + [n for n in nodes if n not in _NODE_ORDER]
    lines = [f"{_NODE_GLYPH.get(nodes[n].get('status', 'idle'), ':white_circle:')} `{n}`" for n in ordered]
    # FILL IN: append error text for failed nodes (nodes[n].get("error")) truncated to 120 chars — bounded by AC16
    return [_section(f"*Run `{record.run_id}` — {record.phase}*\n" + "\n".join(lines))]
```
**Why**: the reducer's `nodes` dict (`session_state.py:330`) is the only input; ordering by the known graph keeps the card stable across edits.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop/transport.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3207 lands: grep -c '        self.logger = logging.getLogger(__name__)' …/slack/devloop/transport.py)
# AFTER — insert below `        self.logger = logging.getLogger(__name__)` inside SlackDevLoopTransport.__init__
        # TASK-3209: status-card debounce state, keyed by run_id.
        self._status_pending: dict[str, tuple[RunRecord, dict[str, Any]]] = {}
        self._status_timers: dict[str, asyncio.Task] = {}
        self._status_backoff_until: dict[str, float] = {}
        self.status_debounce_seconds = 2.0

# occurrences: 1 (verified after TASK-3207 lands: grep -c '        """No-op until TASK-3209 (status card)."""' …/slack/devloop/transport.py)
# REPLACE the whole `update_status` method (its docstring is the anchor) with:
    async def update_status(self, record: RunRecord, state: dict[str, Any]) -> None:
        """Create-or-update the run's status card; 2 s trailing-edge debounce per run_id; best-effort (never raises)."""
        cfg = getattr(self.wrapper.config, "devloop", None)
        if cfg is None or not getattr(cfg, "status_card", True):
            return
        nodes = dict(state.get("nodes") or {})
        self._status_pending[record.run_id] = (record, nodes)
        if record.phase in ("completed", "failed", "cancelled"):
            await self._flush_status(record.run_id)  # terminal: flush now
            return
        if record.run_id not in self._status_timers:
            self._status_timers[record.run_id] = asyncio.create_task(self._flush_status_later(record.run_id))

    async def _flush_status_later(self, run_id: str) -> None:
        await asyncio.sleep(self.status_debounce_seconds)
        self._status_timers.pop(run_id, None)
        await self._flush_status(run_id)

    async def _flush_status(self, run_id: str) -> None:
        pending = self._status_pending.pop(run_id, None)
        if pending is None or time.monotonic() < self._status_backoff_until.get(run_id, 0.0):
            return
        record, nodes = pending
        kit = blocks.status_card_blocks(record, nodes)
        try:
            if record.status_message_ts:
                ok = await self.wrapper.update_message(record.channel_id, record.status_message_ts, f"Run {run_id} status", blocks=kit)
                # FILL IN: on not ok — read retry_after if TASK-3205 exposes it, else 5 s; set _status_backoff_until — bounded by AC16
            else:
                record.status_message_ts = await self._post_in_thread(record, f"Run {run_id} status", kit) or ""
        except Exception:  # noqa: BLE001 — the card is best-effort
            self.logger.debug("status card update failed for %s", run_id, exc_info=True)
```
**Why**: trailing-edge debounce keeps `chat.update` under Tier 3 (S10); the terminal flush guarantees the last state is shown; `record.status_message_ts` persists via the service's next `registry.save` (spec §2 `RunRecord`). Add `import asyncio, time` to the module imports (verified: only `logging` is imported there by TASK-3207).

### `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_status_card.py` (CREATE)
```python
"""Status card debounce tests (TASK-3209)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.slack.devloop.blocks import status_card_blocks
from parrot.integrations.slack.devloop.transport import SlackDevLoopTransport


def test_status_card_blocks_glyphs_and_order():
    """completed/running/idle/failed/skipped map to the five glyphs, known nodes first in graph order."""
    # FILL IN: nodes = {"qa": {"status": "idle"}, "ideation": {"status": "completed"}, "planner": {"status": "running"}} — bounded by AC16


@pytest.mark.asyncio
async def test_status_card_debounce():
    """10 node events within 1 s produce exactly ONE chat.update (after the first create)."""
    # FILL IN: wrapper = MagicMock(config=MagicMock(devloop=MagicMock(status_card=True)), post_message=AsyncMock(return_value="1.0"),
    #          update_message=AsyncMock(return_value=True)); transport.status_debounce_seconds = 0.05; fire 10 updates; await asyncio.sleep(0.2);
    #          assert update_message.await_count == 1 — bounded by AC16


@pytest.mark.asyncio
async def test_status_card_disabled_and_never_raises():
    """status_card=False ⇒ no Slack call; a failing wrapper is swallowed."""
    # FILL IN — bounded by AC16
```
**Why**: spec §4 row `test_status_card_debounce` plus the two AC16 guarantees (disable switch, best-effort).

### FILL IN checklist
- [ ] `blocks.py::status_card_blocks` — failed-node error text; bounded by AC16
- [ ] `transport.py::_flush_status` — backoff on `ratelimited`/`False`; bounded by AC16
- [ ] tests — three bodies; bounded by AC16

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_status_card.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/slack/devloop`
- [ ] Imports work: `from parrot.integrations.slack.devloop.blocks import status_card_blocks`
- [ ] ≤1 `chat.update` per 2 s per run; final state flushed on terminal events; `status_card: false` changes nothing else (spec AC16)

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/slack/test_slack_devloop_status_card.py — see blueprint block.
```

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
4. **Update status** in `sdd/tasks/index/dev-loop-slack.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3209-slack-devloop-status-card.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-12
**Notes**: Added `status_card_blocks` to `blocks.py` (graph-ordered node
lines with the five glyphs, unknown nodes last, failed-node error text
truncated to 120 chars). Replaced the `update_status` no-op in
`transport.py` with the full debounce implementation: `_status_pending`/
`_status_timers`/`_status_backoff_until` dicts + `status_debounce_seconds`
(2.0) added to `__init__`; `update_status` gates on
`config.devloop.status_card`, flushes immediately on a terminal phase
(cancelling any pending timer first) and otherwise schedules a single
trailing-edge flush per `run_id`; `_flush_status` creates the card via
`_post_in_thread` (first call) or edits it via `update_message`
(subsequent calls), applying a fixed 5s backoff on any failure — since
`wrapper.update_message` returns a plain `bool` and (per TASK-3205's own
implementation) never exposes the Slack `retry_after` value to the
caller, every failure (rate-limited or not) gets the same fixed backoff
rather than a distinct one, exactly as the task's own "Does NOT Exist"
section anticipated. `test_slack_devloop_status_card.py` (5 tests, two
more than the blueprint's three) covers glyph/order rendering with
truncation, the debounce/coalesce behavior (fixed my own first draft: the
*first* `update_status` call also goes through the debounce — it does not
post synchronously — my initial test assumed otherwise and had to be
corrected to match the actual, correct implementation), immediate flush
on a terminal phase even with the debounce window at 60s, the
`status_card=False` disable switch, and a missing `devloop` config
treated as disabled.
`pytest packages/ai-parrot-integrations/tests/integrations/slack -q`:
93 passed. `ruff check` and `black --check` clean on all three files
(only new/modified-by-me sections; no pre-existing drift in these files
since TASK-3207 wrote them fresh). Import verified: `from
parrot.integrations.slack.devloop.blocks import status_card_blocks`.

**Deviations from spec**: none.
