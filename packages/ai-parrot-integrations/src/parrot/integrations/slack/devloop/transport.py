"""SlackDevLoopTransport — the only Slack-facing implementation of DevLoopTransport (FEAT-555 M11)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from aiohttp import ClientSession  # verified: slack/interactive.py:12 pattern

from parrot.integrations.devloop.models import GateView, Requester, RunEvent, RunRecord  # TASK-3200
from parrot.integrations.slack.devloop import blocks
from parrot.integrations.slack.wrapper import SlackAgentWrapper  # verified: slack/wrapper.py:72


class SlackDevLoopTransport:
    """Implements DevLoopTransport (spec §3 M8) over wrapper.post_message / update_message / open_dm. Never raises."""

    def __init__(self, wrapper: SlackAgentWrapper) -> None:
        self.wrapper = wrapper
        self.logger = logging.getLogger(__name__)
        # Card locations kept here (not on RunRecord/PendingConfirmation) — a Slack
        # detail the channel-neutral core does not need to know about.
        self._confirm_cards: Dict[str, Tuple[str, str]] = {}  # pending_id -> (channel, ts)
        self._gate_cards: Dict[Tuple[str, str], Tuple[str, str]] = {}  # (run_id, gate_id) -> (channel, ts)

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

    async def _post_in_thread(self, record: RunRecord, text: str, kit: list[dict[str, Any]]) -> Optional[str]:
        return await self.wrapper.post_message(record.channel_id, text, blocks=kit, thread_ts=record.thread_ts or None)

    # -- DevLoopTransport protocol --------------------------------------------------------------------------
    async def post_run_dispatched(self, record: RunRecord) -> str:
        """Thread root; falls back to a DM thread (open_dm) when the bot is not in the channel."""
        text = f"Development flow dispatched — {record.run_id}"
        kit = blocks.dispatch_root_blocks(record)
        ts = await self.wrapper.post_message(record.channel_id, text, blocks=kit)
        if ts is None:
            dm_channel = await self.wrapper.open_dm(record.requester.user_id)
            if dm_channel:
                ts = await self.wrapper.post_message(dm_channel, text, blocks=kit)
                if ts:
                    record.channel_id = dm_channel
        return ts or ""

    async def post_confirm(
        self, pending_id: str, kind: str, fields: Dict[str, str], requester: Requester, channel_id: str
    ) -> str:
        ts = await self.wrapper.post_message(
            channel_id, f"Confirm your {kind} request", blocks=blocks.confirm_blocks(pending_id, kind, fields)
        )
        if ts:
            self._confirm_cards[pending_id] = (channel_id, ts)
        return ts or ""

    async def update_confirm(self, pending_id: str, outcome: str, record: Optional[RunRecord]) -> None:
        """Edit the confirm card in place after confirm/discard/expiry."""
        location = self._confirm_cards.pop(pending_id, None)
        if location is None:
            return
        channel, ts = location
        text = {
            "confirmed": "Confirmed — dispatching…",
            "discarded": "Cancelled.",
        }.get(outcome, outcome)
        if outcome == "confirmed" and record is not None:
            text = f":white_check_mark: Confirmed — run `{record.run_id}` dispatching…"
        elif outcome == "discarded":
            text = ":no_entry_sign: Cancelled."
        await self.wrapper.update_message(
            channel, ts, text, blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
        )

    async def post_run_started(self, record: RunRecord) -> None:
        await self._post_in_thread(record, f"Run {record.run_id} started", blocks.run_started_blocks(record))

    async def post_spawn_failed(self, record: RunRecord, error: str) -> None:
        await self._post_in_thread(
            record,
            f"Could not start {record.run_id}",
            [{"type": "section", "text": {"type": "mrkdwn", "text": f":x: *Could not start*\n```{error[-2000:]}```"}}],
        )

    async def post_gate(self, record: RunRecord, gate: GateView) -> None:
        ts = await self._post_in_thread(record, gate.title, blocks.gate_blocks(record, gate))
        if ts:
            self._gate_cards[(record.run_id, gate.gate_id)] = (record.channel_id, ts)

    async def update_gate(self, record: RunRecord, gate: GateView) -> None:
        location = self._gate_cards.get((record.run_id, gate.gate_id))
        if location is None:
            return
        channel, ts = location
        await self.wrapper.update_message(channel, ts, gate.title, blocks=blocks.gate_resolved_blocks(record, gate))

    async def update_status(self, record: RunRecord, state: Dict[str, Any]) -> None:
        """No-op until TASK-3209 (status card)."""
        return None

    async def post_terminal(self, record: RunRecord, event: RunEvent) -> None:
        await self._post_in_thread(record, f"Run {record.run_id} finished", blocks.terminal_blocks(record, event))
