"""SlackDevLoopTransport — the only Slack-facing implementation of DevLoopTransport (FEAT-555 M11)."""

from __future__ import annotations

import asyncio
import logging
import time
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
        # TASK-3209: status-card debounce state, keyed by run_id.
        self._status_pending: Dict[str, Tuple[RunRecord, Dict[str, Any]]] = {}
        self._status_timers: Dict[str, "asyncio.Task"] = {}
        self._status_backoff_until: Dict[str, float] = {}
        self.status_debounce_seconds = 2.0

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
            "expired": "Expired.",
        }.get(outcome, outcome)
        if outcome == "confirmed" and record is not None:
            text = f":white_check_mark: Confirmed — run `{record.run_id}` dispatching…"
        elif outcome == "discarded":
            text = ":no_entry_sign: Cancelled."
        elif outcome == "expired":
            # Code review fix (FEAT-555): the card used to stay live forever
            # with clickable Confirm/Edit/Cancel buttons past its 15-minute
            # TTL — the service now proactively schedules this flush.
            text = ":hourglass_flowing_sand: This request expired (15 min timeout)."
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
        """Create-or-update the run's status card.

        Debounced to at most one ``chat.update`` per
        ``status_debounce_seconds`` (trailing edge) per run, gated by
        ``config.status_card``. Best-effort: never raises. Terminal
        phases flush immediately instead of waiting for the debounce
        window, so the last state is always shown.

        Args:
            record: The run the status update belongs to.
            state: The folded ``DevLoopSessionState.model_dump()``.
        """
        cfg = getattr(self.wrapper.config, "devloop", None)
        if cfg is None or not getattr(cfg, "status_card", True):
            return
        nodes = dict(state.get("nodes") or {})
        self._status_pending[record.run_id] = (record, nodes)
        if record.phase in ("completed", "failed", "cancelled"):
            timer = self._status_timers.pop(record.run_id, None)
            if timer is not None:
                timer.cancel()
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
                ok = await self.wrapper.update_message(
                    record.channel_id, record.status_message_ts, f"Run {run_id} status", blocks=kit
                )
                if not ok:
                    # wrapper.update_message returns a plain bool — it does not
                    # expose the Slack `retry_after` header (see TASK-3205's
                    # _slack_api), so every failure (including rate-limiting)
                    # gets the same fixed 5s backoff rather than a retry-storm.
                    self._status_backoff_until[run_id] = time.monotonic() + 5.0
                    self.logger.debug("status card update failed for %s; backing off 5s", run_id)
            else:
                record.status_message_ts = await self._post_in_thread(record, f"Run {run_id} status", kit) or ""
        except Exception:  # noqa: BLE001 — the card is best-effort
            self.logger.debug("status card update failed for %s", run_id, exc_info=True)

    async def post_terminal(self, record: RunRecord, event: RunEvent) -> None:
        await self._post_in_thread(record, f"Run {record.run_id} finished", blocks.terminal_blocks(record, event))
