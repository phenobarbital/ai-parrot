"""SlackDevLoopTransport — the only Slack-facing implementation of DevLoopTransport (FEAT-555 M11).

FEAT-555 NOTE (written by TASK-3206): TASK-3207 had not landed yet when
this file was created, so this is a **minimal stub** — just enough to
satisfy the ``DevLoopTransport`` protocol and ``register_devloop()``'s
wiring contract for the confirm-card flow (post_confirm/post_run_dispatched/
post_run_started/post_spawn_failed/render_status/ephemeral/permalink are
fully functional). ``post_gate``/``update_gate``/``update_confirm``/
``post_terminal`` are simplified until TASK-3207 (which needs the
``gate_blocks``/``gate_resolved_blocks``/``terminal_blocks`` builders it
adds to ``blocks.py``) replaces this file with the full implementation.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientSession  # verified: slack/interactive.py:12 pattern

from parrot.integrations.devloop.models import GateView, Requester, RunEvent, RunRecord  # TASK-3200
from parrot.integrations.slack.devloop import blocks
from parrot.integrations.slack.wrapper import SlackAgentWrapper  # verified: slack/wrapper.py:72


class SlackDevLoopTransport:
    """Implements DevLoopTransport (spec §3 M8) over wrapper.post_message / update_message / open_dm. Never raises."""

    def __init__(self, wrapper: SlackAgentWrapper) -> None:
        self.wrapper = wrapper
        self.logger = logging.getLogger(__name__)

    # -- adapter helpers (used by commands.py / actions.py) ---------------------------------------------------
    async def ephemeral(self, response_url: str, text: str) -> None:
        """POST an ephemeral reply to a Slack response_url (pattern: interactive.py:255-270)."""
        if not response_url:
            return
        try:
            async with ClientSession() as session:
                await session.post(
                    response_url, json={"response_type": "ephemeral", "text": text, "replace_original": False}
                )
        except Exception:  # noqa: BLE001
            self.logger.exception("ephemeral reply failed")

    def permalink(self, record: RunRecord) -> str:
        """https://slack.com/archives/<channel>/p<ts without dot> — works without knowing the team domain."""
        if not record.thread_ts:
            return ""
        return f"https://slack.com/archives/{record.channel_id}/p{record.thread_ts.replace('.', '')}"

    def render_status(self, records: list[RunRecord]) -> str:
        return blocks.status_list_text(records, self.permalink)

    async def _post_in_thread(self, record: RunRecord, text: str, kit: list[dict[str, Any]]) -> str | None:
        return await self.wrapper.post_message(record.channel_id, text, blocks=kit, thread_ts=record.thread_ts or None)

    # -- DevLoopTransport protocol --------------------------------------------------------------------------
    async def post_run_dispatched(self, record: RunRecord) -> str:
        """Thread root. TASK-3207 adds the DM fallback for ``not_in_channel``."""
        ts = await self.wrapper.post_message(
            record.channel_id,
            f"Development flow dispatched — {record.run_id}",
            blocks=blocks.dispatch_root_blocks(record),
        )
        return ts or ""

    async def post_confirm(
        self, pending_id: str, kind: str, fields: dict[str, str], requester: Requester, channel_id: str
    ) -> str:
        ts = await self.wrapper.post_message(
            channel_id, f"Confirm your {kind} request", blocks=blocks.confirm_blocks(pending_id, kind, fields)
        )
        return ts or ""

    async def update_confirm(self, pending_id: str, outcome: str, record: RunRecord | None) -> None:
        """FEAT-555 stub: TASK-3207 tracks the confirm card's (channel, ts) to edit it in place."""
        self.logger.debug("update_confirm (stub): pending_id=%s outcome=%s", pending_id, outcome)

    async def post_run_started(self, record: RunRecord) -> None:
        await self._post_in_thread(record, f"Run {record.run_id} started", blocks.run_started_blocks(record))

    async def post_spawn_failed(self, record: RunRecord, error: str) -> None:
        await self._post_in_thread(
            record,
            f"Could not start {record.run_id}",
            [{"type": "section", "text": {"type": "mrkdwn", "text": f":x: *Could not start*\n```{error[-2000:]}```"}}],
        )

    async def post_gate(self, record: RunRecord, gate: GateView) -> None:
        """FEAT-555 stub: TASK-3207 renders the real gate_blocks() card and remembers its ts."""
        self.logger.debug("post_gate (stub): run=%s gate=%s", record.run_id, gate.gate_id)

    async def update_gate(self, record: RunRecord, gate: GateView) -> None:
        """FEAT-555 stub: TASK-3207 edits the gate card in place via gate_resolved_blocks()."""
        self.logger.debug("update_gate (stub): run=%s gate=%s", record.run_id, gate.gate_id)

    async def update_status(self, record: RunRecord, state: dict[str, Any]) -> None:
        """No-op until TASK-3209 (status card)."""
        return None

    async def post_terminal(self, record: RunRecord, event: RunEvent) -> None:
        """FEAT-555 stub: TASK-3207 renders the real terminal_blocks() summary."""
        await self._post_in_thread(
            record,
            f"Run {record.run_id} finished ({event.kind})",
            [{"type": "section", "text": {"type": "mrkdwn", "text": f"Run `{record.run_id}` finished: {event.kind}"}}],
        )
