"""NotificationSubscriber — severity alerting via parrot.notifications.

FEAT-310 Module 5 (goal G3, alerting half). Subscribes to a
:class:`~parrot.core.events.bus.core.BusCore` with severity-threshold
and sliding-window rules and delivers alerts through
``NotificationMixin.send_notification()`` (async-notify:
email/Slack/Telegram/Teams).

Rate-limiting / dedup defaults (spec §2, resolved in brainstorm):

- **Dedup**: identical ``(rule_id, topic_class)`` alerts suppressed for
  300 s after first delivery; the repeat count is appended to the next
  alert once the window closes.
- **Channel throttle**: max 10 notifications/min per channel; overflow is
  folded into a single digest message.
- **Storm guard**: > 25 ERROR+ events / 30 s collapse into one CRITICAL
  "event storm" alert until the rate drops.

All knobs are configurable via :class:`AlertsConfig` — populated from
``[bus.alerts]`` TOML (navconfig flattened ``BUS_ALERTS_*`` keys) or
programmatically (``[[bus.alerts]]`` rule tables map to
:class:`AlertRule` entries via :meth:`AlertsConfig.from_dict`).

Loop safety (spec §7 "Alert storms"): internal ``bus.*`` topics never
trigger alerts with default config, and delivery failures are logged —
never raised into the dispatch path (model B).
"""
from __future__ import annotations

import asyncio
import fnmatch
from collections import deque
from typing import Any, Optional, Union

from navconfig import config as nav_config
from navconfig.logging import logging
from pydantic import BaseModel, ConfigDict, Field

from parrot.core.events.bus.core import BusCore
from parrot.core.events.bus.envelope import EventEnvelope, Severity


class AlertRule(BaseModel):
    """A single alerting rule.

    A rule is a *threshold* rule by default (every matching envelope at or
    above ``min_severity`` alerts, subject to dedup/throttle). Setting BOTH
    ``window_seconds`` and ``count_threshold`` turns it into a
    *sliding-window* rule ("N events ≥ severity in M seconds") that fires
    once when the window crosses the threshold.

    Attributes:
        rule_id: Unique rule identifier (dedup key component).
        pattern: Topic glob the rule applies to (default ``*``).
        min_severity: Severity floor (default ``ERROR``).
        window_seconds: Sliding-window length in seconds (window rules).
        count_threshold: Events required inside the window (window rules).
        provider: async-notify provider name (``email``/``slack``/
            ``telegram``/``teams``).
        recipients: Recipients forwarded to ``send_notification``.
        subject: Optional subject line (mainly email).
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    pattern: str = "*"
    min_severity: Severity = Severity.ERROR
    window_seconds: Optional[float] = None
    count_threshold: Optional[int] = None
    provider: str = "email"
    recipients: Union[str, list[str]]
    subject: Optional[str] = None

    @property
    def is_window_rule(self) -> bool:
        """Whether this rule uses sliding-window semantics."""
        return self.window_seconds is not None and self.count_threshold is not None


class AlertsConfig(BaseModel):
    """``[bus.alerts]`` configuration with spec §2 defaults.

    Attributes:
        dedup_window_seconds: Suppression window for identical
            ``(rule_id, topic_class)`` alerts (default 300 s).
        channel_throttle_max: Max notifications per channel per throttle
            window (default 10).
        channel_throttle_window_seconds: Throttle window (default 60 s —
            i.e. 10/min).
        storm_threshold_events: ERROR+ events that activate the storm
            guard (default 25).
        storm_window_seconds: Storm counting window (default 30 s).
        include_bus_internal: Alert on internal ``bus.*`` topics
            (default False — loop guard, spec §7).
        rules: Alert rules (``[[bus.alerts]]`` TOML tables).
    """

    model_config = ConfigDict(extra="forbid")

    dedup_window_seconds: float = 300.0
    channel_throttle_max: int = 10
    channel_throttle_window_seconds: float = 60.0
    storm_threshold_events: int = 25
    storm_window_seconds: float = 30.0
    include_bus_internal: bool = False
    rules: list[AlertRule] = Field(default_factory=list)

    @classmethod
    def from_navconfig(cls) -> "AlertsConfig":
        """Build scalar knobs from navconfig ``BUS_ALERTS_*`` keys.

        Rule tables (``[[bus.alerts]]``) cannot travel through flattened
        env keys — supply them via :meth:`from_dict` or programmatically.

        Returns:
            AlertsConfig with env-driven scalar overrides.
        """
        def _get(key: str, fallback: Any, cast: Any) -> Any:
            value = nav_config.get(key, fallback=fallback)
            try:
                return cast(value)
            except (TypeError, ValueError):
                return fallback

        return cls(
            dedup_window_seconds=_get("BUS_ALERTS_DEDUP_WINDOW", 300.0, float),
            channel_throttle_max=_get("BUS_ALERTS_CHANNEL_THROTTLE", 10, int),
            channel_throttle_window_seconds=_get(
                "BUS_ALERTS_THROTTLE_WINDOW", 60.0, float
            ),
            storm_threshold_events=_get("BUS_ALERTS_STORM_THRESHOLD", 25, int),
            storm_window_seconds=_get("BUS_ALERTS_STORM_WINDOW", 30.0, float),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AlertsConfig":
        """Build from a parsed ``[bus.alerts]`` TOML mapping.

        Args:
            data: Mapping with scalar knobs and/or a ``rules`` list of
                ``[[bus.alerts]]``-style rule tables.

        Returns:
            Validated AlertsConfig.
        """
        return cls.model_validate(data)


class _RuleState:
    """Mutable runtime state for one rule (window timestamps)."""

    __slots__ = ("times",)

    def __init__(self) -> None:
        self.times: deque[float] = deque()


class _DedupEntry:
    """Dedup-window state for one ``(rule_id, topic_class)`` key."""

    __slots__ = ("first", "suppressed")

    def __init__(self, first: float) -> None:
        self.first = first
        self.suppressed = 0


class NotificationSubscriber:
    """Bus subscriber that turns severe events into notifications.

    Composed WITH a ``NotificationMixin``-derived sender (or any injected
    object exposing an async ``send_notification``) so tests can inject a
    mock.

    Args:
        sender: Object exposing
            ``async send_notification(message, recipients, provider=...,
            subject=..., **kwargs)`` (e.g. a ``NotificationMixin`` host).
        rules: Alert rules (merged after ``config.rules``).
        config: Rate-limit/dedup knobs (defaults = spec §2).
        send_timeout: Per-delivery ``asyncio.timeout`` in seconds — a hung
            provider must not stall anything.
    """

    def __init__(
        self,
        sender: Any,
        *,
        rules: Optional[list[AlertRule]] = None,
        config: Optional[AlertsConfig] = None,
        send_timeout: float = 10.0,
    ) -> None:
        self._sender = sender
        self._config = config or AlertsConfig()
        self._rules: list[AlertRule] = [*self._config.rules, *(rules or [])]
        self._send_timeout = send_timeout

        self._rule_state: dict[str, _RuleState] = {
            rule.rule_id: _RuleState() for rule in self._rules
        }
        self._dedup: dict[tuple[str, str], _DedupEntry] = {}
        self._channel_sent: dict[str, deque[float]] = {}
        self._channel_overflow: dict[str, list[str]] = {}
        self._digest_tasks: dict[str, asyncio.Task[None]] = {}
        self._error_times: deque[float] = deque()
        self._storm_active = False
        self._subscription_id: Optional[str] = None
        # Strong refs to fire-and-forget delivery tasks (asyncio GC gotcha).
        self._background_tasks: set[asyncio.Task[None]] = set()

        self.logger = logging.getLogger(
            "parrot.core.events.bus.subscribers.notification"
        )

    # ------------------------------------------------------------------
    # Bus wiring
    # ------------------------------------------------------------------

    def attach(self, bus: BusCore) -> Optional[str]:
        """Subscribe this alerter on *bus*.

        A single wildcard subscription is used, floored at the lowest
        ``min_severity`` among the rules (severity filtering never affects
        scheduling — spec G3).

        Args:
            bus: The BusCore to attach to — or the ``EventBus`` facade
                (resolved via its ``.core`` property).

        Returns:
            The subscriber id, or ``None`` when no rules are configured.
        """
        core: BusCore = getattr(bus, "core", bus)
        if not self._rules:
            self.logger.warning(
                "NotificationSubscriber has no rules — not attaching"
            )
            return None
        floor = min(rule.min_severity for rule in self._rules)
        self._subscription_id = core.subscribe(
            "*", self._on_envelope, min_severity=floor
        )
        return self._subscription_id

    def detach(self, bus: BusCore) -> bool:
        """Remove this alerter's subscription from *bus*."""
        core: BusCore = getattr(bus, "core", bus)
        if self._subscription_id is None:
            return False
        removed = core.unsubscribe(self._subscription_id)
        self._subscription_id = None
        return removed

    # ------------------------------------------------------------------
    # Envelope handling
    # ------------------------------------------------------------------

    async def _on_envelope(self, envelope: EventEnvelope) -> None:
        """Evaluate rules for one envelope (never raises — model B)."""
        try:
            self._evaluate(envelope)
        except Exception:  # noqa: BLE001 — alerting must not cascade
            self.logger.exception(
                "NotificationSubscriber failed on %s", envelope.topic
            )

    def _evaluate(self, envelope: EventEnvelope) -> None:
        """Run storm guard + rule matching for one envelope."""
        if (
            envelope.topic.startswith("bus.")
            and not self._config.include_bus_internal
        ):
            return

        now = asyncio.get_running_loop().time()

        # --- Storm guard (global, ERROR+) --------------------------------
        if envelope.severity >= Severity.ERROR:
            self._error_times.append(now)
        self._prune(self._error_times, now, self._config.storm_window_seconds)
        if len(self._error_times) > self._config.storm_threshold_events:
            if not self._storm_active:
                self._storm_active = True
                self._schedule_delivery(
                    provider=self._storm_provider(),
                    recipients=self._storm_recipients(),
                    subject="Event storm detected",
                    message=(
                        f"[CRITICAL] Event storm: "
                        f">{self._config.storm_threshold_events} ERROR+ "
                        f"events in {self._config.storm_window_seconds:.0f}s "
                        f"(last topic: {envelope.topic}). Individual alerts "
                        "suppressed until the rate drops."
                    ),
                    bypass_throttle=True,
                )
            return  # collapse: nothing else fires during a storm
        if self._storm_active:
            self._storm_active = False
            self.logger.info("Event storm subsided — alerting resumed")

        # --- Per-rule evaluation -----------------------------------------
        for rule in self._rules:
            if envelope.severity < rule.min_severity:
                continue
            if not fnmatch.fnmatch(envelope.topic, rule.pattern):
                continue
            if rule.is_window_rule:
                state = self._rule_state[rule.rule_id]
                state.times.append(now)
                self._prune(state.times, now, rule.window_seconds)
                if len(state.times) >= rule.count_threshold:
                    state.times.clear()  # fire once per crossing
                    self._fire(rule, envelope, now, windowed=True)
            else:
                self._fire(rule, envelope, now, windowed=False)

    def _fire(
        self,
        rule: AlertRule,
        envelope: EventEnvelope,
        now: float,
        *,
        windowed: bool,
    ) -> None:
        """Apply dedup + throttle, then schedule delivery for one alert."""
        topic_class = envelope.topic.split(".", 1)[0]
        key = (rule.rule_id, topic_class)
        entry = self._dedup.get(key)
        repeat_note = ""
        if entry is not None:
            if now - entry.first < self._config.dedup_window_seconds:
                entry.suppressed += 1
                return  # suppressed inside the dedup window
            if entry.suppressed:
                repeat_note = (
                    f" ({entry.suppressed} identical alert(s) suppressed in "
                    f"the previous {self._config.dedup_window_seconds:.0f}s "
                    "window)"
                )
        self._dedup[key] = _DedupEntry(now)

        if windowed:
            headline = (
                f"[{envelope.severity.name}] rule '{rule.rule_id}': "
                f"{rule.count_threshold}+ events >= "
                f"{rule.min_severity.name} within "
                f"{rule.window_seconds:.0f}s (last: {envelope.topic})"
            )
        else:
            headline = (
                f"[{envelope.severity.name}] {envelope.topic} "
                f"(rule '{rule.rule_id}', event {envelope.event_id})"
            )
        self._schedule_delivery(
            provider=rule.provider,
            recipients=rule.recipients,
            subject=rule.subject or f"Parrot alert: {envelope.topic}",
            message=headline + repeat_note,
        )

    # ------------------------------------------------------------------
    # Delivery: throttle + digest + timeout
    # ------------------------------------------------------------------

    def _schedule_delivery(
        self,
        *,
        provider: str,
        recipients: Union[str, list[str]],
        subject: str,
        message: str,
        bypass_throttle: bool = False,
    ) -> None:
        """Throttle-check and dispatch one notification off-path."""
        now = asyncio.get_running_loop().time()
        sent = self._channel_sent.setdefault(provider, deque())
        self._prune(sent, now, self._config.channel_throttle_window_seconds)

        if not bypass_throttle and len(sent) >= self._config.channel_throttle_max:
            # Fold into the per-channel digest.
            overflow = self._channel_overflow.setdefault(provider, [])
            overflow.append(message)
            if provider not in self._digest_tasks:
                wait = (
                    sent[0]
                    + self._config.channel_throttle_window_seconds
                    - now
                )
                self._digest_tasks[provider] = asyncio.create_task(
                    self._flush_digest(
                        provider, recipients, max(wait, 0.01)
                    ),
                    name=f"bus-alert-digest-{provider}",
                )
            return

        sent.append(now)
        task = asyncio.create_task(
            self._deliver(provider, recipients, subject, message),
            name=f"bus-alert-deliver-{provider}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _flush_digest(
        self,
        provider: str,
        recipients: Union[str, list[str]],
        delay: float,
    ) -> None:
        """Send ONE digest for all alerts folded during a throttle window."""
        try:
            await asyncio.sleep(delay)
            overflow = self._channel_overflow.pop(provider, [])
            if not overflow:
                return
            message = (
                f"[DIGEST] {len(overflow)} alert(s) throttled on channel "
                f"'{provider}' (max "
                f"{self._config.channel_throttle_max} per "
                f"{self._config.channel_throttle_window_seconds:.0f}s):\n- "
                + "\n- ".join(overflow)
            )
            now = asyncio.get_running_loop().time()
            self._channel_sent.setdefault(provider, deque()).append(now)
            await self._deliver(
                provider, recipients, "Parrot alert digest", message
            )
        finally:
            self._digest_tasks.pop(provider, None)

    async def _deliver(
        self,
        provider: str,
        recipients: Union[str, list[str]],
        subject: str,
        message: str,
    ) -> None:
        """Call ``send_notification`` with a timeout; failures only log."""
        try:
            async with asyncio.timeout(self._send_timeout):
                await self._sender.send_notification(
                    message=message,
                    recipients=recipients,
                    provider=provider,
                    subject=subject,
                )
        except Exception as exc:  # noqa: BLE001 — model B, never cascade
            self.logger.error(
                "Alert delivery failed on channel '%s': %s", provider, exc
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prune(times: deque[float], now: float, window: float) -> None:
        """Drop timestamps older than *window* seconds from the left."""
        cutoff = now - window
        while times and times[0] < cutoff:
            times.popleft()

    def _storm_provider(self) -> str:
        """Channel used for the storm alert (first rule's provider)."""
        return self._rules[0].provider if self._rules else "email"

    def _storm_recipients(self) -> Union[str, list[str]]:
        """Recipients for the storm alert (first rule's recipients)."""
        return self._rules[0].recipients if self._rules else []
