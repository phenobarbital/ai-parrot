"""Autonomous Data-Analyst — full harness service (aiohttp + Telegram).

Wires the complete AI-Parrot *autonomous agent harness* around a single
data-analyst agent and exposes it over a real Telegram bot:

    Telemetry (FEAT-177)        ── observability of every LLM/tool call
        │
    BotManager                  ── owns the agent + ephemeral lifecycle
        │
    Event Ledger (FEAT-212)     ── append-only typed log + crash resume
        │
    AutonomousOrchestrator      ── executes the agent on demand / on resume
        │
    HeartbeatManager (FEAT-209) ── wakes the agent on an interval (wake→assess→act)
        │
    GrantGuard (FEAT-211)       ── gates `publish_report` behind Telegram approval
        │
    SpawnSubAgentTool (FEAT-208)── delegates bounded work to ephemeral sub-agents
        │
    Telegram operator commands  ── /health /status /context /memory /mission
      (FEAT-210)                   /model /thread  (operator-only, fail-closed)

Run it:

    source .venv/bin/activate
    export GOOGLE_API_KEY=...                  # Gemini (real LLM)
    export TELEGRAM_BOT_TOKEN=...              # from @BotFather
    export OPERATOR_CHAT_IDS=123456789         # your Telegram numeric id
    python examples/autonomous_analyst/service.py

See README.md for the full deployment guide (Telegram setup, Postgres ledger,
systemd unit, observability stack).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

from aiohttp import web

# --- Harness building blocks (all merged on dev) ---------------------------
from parrot.manager import BotManager
from parrot.autonomous.orchestrator import AutonomousOrchestrator
from parrot.autonomous.heartbeat import (
    HeartbeatManager,
    HeartbeatConfig,
    DefaultHeartbeatStrategy,
)
from parrot.autonomous.ledger import (
    EventLedger,
    InMemoryLedgerBackend,
    PostgresLedgerBackend,
    LedgerRecorder,
)
from parrot.auth.grants import InMemoryGrantStore, GrantGuard, GrantConfig
from parrot.observability import ObservabilityConfig, setup_telemetry, shutdown_telemetry

# --- Telegram integration --------------------------------------------------
from parrot.integrations.telegram.manager import TelegramBotManager

from agent import AutonomousAnalystAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("demo.service")

CHATBOT_ID = "autonomous-analyst"
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "120"))  # seconds


# ---------------------------------------------------------------------------
# 1. Telemetry — zero-infra by default (structured logs), OTLP if configured.
# ---------------------------------------------------------------------------
def boot_telemetry() -> None:
    """Wire FEAT-177 observability to the global lifecycle registry.

    With ``OTLP_ENDPOINT`` set we ship GenAI spans + metrics + cost to an OTLP
    collector. Without it we fall back to the zero-infra ``usage_backend=logging``
    path: every LLM/tool call is recorded as a structured log line — no OTel SDK
    or collector required, perfect for a first run.
    """
    otlp = os.getenv("OTLP_ENDPOINT")
    if otlp:
        setup_telemetry(
            ObservabilityConfig(
                enabled=True,
                service_name="autonomous-analyst",
                otlp_endpoint=otlp,
                enable_traces=True,
                enable_metrics=True,
                enable_cost_tracking=True,
                usage_backend="otel",
            )
        )
        logger.info("Telemetry: OTLP → %s (traces+metrics+cost)", otlp)
    else:
        setup_telemetry(
            ObservabilityConfig(
                enabled=True,
                service_name="autonomous-analyst",
                enable_traces=False,
                enable_metrics=False,
                enable_cost_tracking=True,
                usage_backend="logging",  # structured log lines, no infra
            )
        )
        logger.info("Telemetry: zero-infra logging backend (set OTLP_ENDPOINT for OTLP)")


# ---------------------------------------------------------------------------
# 2. Ledger backend — Postgres when a DSN is present, else in-memory.
# ---------------------------------------------------------------------------
def build_ledger(app: web.Application) -> EventLedger:
    """Return a typed event ledger backend (FEAT-212).

    Uses ``PostgresLedgerBackend`` when ``app['database']`` is available (set
    ``LEDGER_PG_DSN`` and wire asyncdb), otherwise ``InMemoryLedgerBackend`` so
    the demo runs with no external dependency. Only Postgres survives restarts
    (and therefore enables real crash-resume).
    """
    db = app.get("database")
    if db is not None:
        logger.info("Ledger: PostgresLedgerBackend (durable, resume enabled)")
        return PostgresLedgerBackend(db)
    logger.info("Ledger: InMemoryLedgerBackend (volatile — resume is a no-op)")
    return InMemoryLedgerBackend()


# ---------------------------------------------------------------------------
# Heartbeat strategy: a tiny 'assess' step so the tick is more than a cron.
# ---------------------------------------------------------------------------
async def _has_pending_work() -> bool:
    """Demo gate: pretend there is analysis work to do.

    In a real deployment this would peek at a task queue, a 'new data arrived'
    flag, freshness of a dataset, etc. Returning True makes the heartbeat act
    on its mission; the DefaultHeartbeatStrategy also has an N-tick fallback.
    """
    return True


async def on_startup(app: web.Application) -> None:
    """Assemble and start every harness component, in dependency order."""
    # --- BotManager: owns agents + ephemeral lifecycle ---------------------
    bot_manager: BotManager = app["bot_manager"]

    # --- The analyst agent. Register it under its chatbot_id so both the
    #     orchestrator (_get_agent → bot_manager._bots) and the Telegram
    #     manager (get_bot(chatbot_id)) resolve THIS instance. ---------------
    agent = AutonomousAnalystAgent(bot_manager=bot_manager, chatbot_id=CHATBOT_ID)
    await agent.configure(app)
    bot_manager._bots[CHATBOT_ID] = agent  # noqa: SLF001 — programmatic registration
    logger.info("Registered agent %r (tools: %d)", CHATBOT_ID,
                len(agent.tool_manager.get_all_tools()))

    # --- Ledger + recorder: capture ALL lifecycle events globally ----------
    ledger = build_ledger(app)
    if isinstance(ledger, PostgresLedgerBackend):
        await ledger.ensure_schema()
    recorder = LedgerRecorder(ledger)
    recorder.start()  # subscribes to get_global_registry() (excludes stream chunks)
    app["event_ledger"] = ledger
    app["ledger_recorder"] = recorder

    # --- Orchestrator: executes the agent (heartbeat + resume both use it) -
    orchestrator = AutonomousOrchestrator(
        bot_manager=bot_manager,
        redis_url=os.getenv("REDIS_URL"),  # None → no Redis, fine for the demo
        use_event_bus=bool(os.getenv("REDIS_URL")),
        use_webhooks=False,
    )
    await orchestrator.start(ledger=ledger, resume_on_start=True)
    app["orchestrator"] = orchestrator

    # --- Grants: gate the agent's `publish_report` behind Telegram approval -
    #     The HumanInteractionManager (Telegram channel) is wired by the
    #     integration layer; without it the guard is fail-closed (denies).
    grant_store = InMemoryGrantStore()
    human_manager = app.get("human_manager")  # set up by HITL wiring if present
    guard = GrantGuard(
        grant_store,
        human_manager=human_manager,
        config=GrantConfig(window_seconds=900, default_channel="telegram"),
    )
    agent.tool_manager.set_grant_guard(guard)
    app["grant_guard"] = guard
    logger.info(
        "Grants: GrantGuard wired (HITL channel: %s)",
        "telegram" if human_manager else "none → fail-closed",
    )

    # --- Heartbeat: wake the agent on an interval (wake→assess→maybe-act) ---
    heartbeat = HeartbeatManager(
        orchestrator,
        strategy=DefaultHeartbeatStrategy(
            has_pending_work=_has_pending_work,
            act_every_n_ticks=5,
        ),
    )
    heartbeat.register(
        HeartbeatConfig(
            agent_name=CHATBOT_ID,
            interval=HEARTBEAT_INTERVAL,
            jitter=10.0,
            mission=(
                "Review working memory for any datasets stored since the last "
                "tick. If there is new data, compute summary statistics with the "
                "wm_compute_and_store tool and store the findings under a clear "
                "key. If a finding is significant, draft a short report and call "
                "publish_report (this needs operator approval). Otherwise, do "
                "nothing and report idle."
            ),
        )
    )
    await heartbeat.start()
    app["heartbeat_manager"] = heartbeat  # operator commands read this from app
    logger.info("Heartbeat: started (interval=%.0fs)", HEARTBEAT_INTERVAL)

    # --- Telegram: start polling the real bot -----------------------------
    #     TelegramBotManager reads {ENV_DIR}/telegram_bots.yaml, resolves the
    #     agent via bot_manager.get_bot(chatbot_id), and builds the wrapper
    #     with app=bot_manager.get_app() so operator commands see
    #     app['heartbeat_manager'] / app['bot_manager'].
    if os.getenv("TELEGRAM_BOT_TOKEN") or (app["bot_manager"].get_app()):
        telegram = TelegramBotManager(bot_manager)
        await telegram.startup()
        app["telegram_manager"] = telegram
        logger.info("Telegram: polling started")
    else:
        logger.warning("Telegram: TELEGRAM_BOT_TOKEN not set — skipping bot startup")


async def on_cleanup(app: web.Application) -> None:
    """Tear everything down in reverse order."""
    for key, stop in (
        ("telegram_manager", "shutdown"),
        ("heartbeat_manager", "stop"),
        ("orchestrator", "stop"),
        ("ledger_recorder", "stop"),
    ):
        comp = app.get(key)
        if comp is None:
            continue
        try:
            res = getattr(comp, stop)()
            if asyncio.iscoroutine(res):
                await res
        except Exception:  # pragma: no cover - best-effort shutdown
            logger.exception("Error stopping %s", key)
    shutdown_telemetry()
    logger.info("Harness stopped cleanly")


def build_app() -> web.Application:
    """Construct the aiohttp app with the BotManager + harness lifecycle hooks."""
    app = web.Application()

    # BotManager.setup(app) publishes app['bot_manager'] and registers its own
    # on_startup/on_shutdown (loads DB/registry bots, starts integrations).
    bot_manager = BotManager(
        enable_database_bots=False,
        enable_registry_bots=False,
        enable_crews=False,
    )
    bot_manager.setup(app)

    # Our harness wiring runs AFTER BotManager.on_startup (append order).
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        logger.warning(
            "GOOGLE_API_KEY not set — the Gemini agent will fail on real calls. "
            "Export it before chatting with the bot."
        )
    boot_telemetry()
    app = build_app()
    port = int(os.getenv("PORT", "8080"))
    logger.info("Autonomous Analyst harness listening on :%d", port)
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
