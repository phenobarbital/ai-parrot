"""
Matrix Agents Swarm Example (FEAT-463)
=======================================

Demonstrates the full swarm: declared channels with answer policies,
private agent-to-agent tunnels, concurrent collaborative sessions, and
the coordinator listing commands.

How the swarm works:
  1. Declared channels are materialised as Matrix rooms at ``start()``
     (alias, join rule, membership, ``m.parrot.channel`` state).
  2. In a ``swarm``-policy channel, un-mentioned human text starts a
     collaborative session automatically (no ``!investigate`` needed) —
     up to ``collaborative.max_concurrent_sessions`` run concurrently per
     room, subject to ``cooldown_seconds``.
  3. Agents can privately ask each other questions via the ``ask_agent``
     tool (through a lazily-created private tunnel room) — this happens
     both during a session's cross-pollination phase and whenever the
     LLM decides to call the tool directly.
  4. Coordinator commands work from any room: ``!channels``, ``!agents``,
     ``!tunnels``, ``!investigate <question>``.

Room topology (matches swarm_crew.yaml):
  GENERAL CHANNEL (public, answer_policy: swarm)
    Members: @researcher, @analyst, @writer
    Un-mentioned text        → starts a swarm session automatically
    "!investigate <question>" → starts a session explicitly, any room
    "@analyst <question>"     → direct routing (unchanged)

  FINANCE CHANNEL (private, answer_policy: mention)
    Members: @analyst
    Only responds to "@analyst <question>"

Prerequisites (same as matrix_crew_example.py):
  1. A Matrix homeserver running — see ../../docker-compose.matrix.yml and
     ../../scripts/matrix/bootstrap.sh for a one-command dev stack.
  2. Application Service registration file generated and registered.
  3. Environment variables set (see below).
  4. Agents configured in BotManager (or agents.yaml).

Usage:
    export MATRIX_AS_TOKEN=<your-as-token>
    export MATRIX_HS_TOKEN=<your-hs-token>
    export MATRIX_GENERAL_ROOM_ID=<room-id-or-leave-unset-to-auto-create>

    python swarm_example.py --config swarm_crew.yaml

    # With debug logging
    python swarm_example.py --config swarm_crew.yaml --log-level DEBUG

Expected behaviour:
  - Sending "@analyst what is AAPL?" in either channel routes directly
    to the analyst (unchanged FEAT-044 behaviour).
  - Sending "What's the Q2 outlook?" (no @mention) in the general channel
    starts a swarm session automatically (answer_policy: swarm).
  - Sending "!investigate <question>" starts a session explicitly in any
    room, honoring the same concurrency cap and cooldown.
  - Sending "!channels" / "!agents" / "!tunnels" lists the current swarm
    topology from the coordinator bot.
"""
import argparse
import asyncio
import logging
import signal
import sys


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed argument namespace with ``config`` and ``log_level`` fields.
    """
    parser = argparse.ArgumentParser(
        description="Matrix Agents Swarm — AI-Parrot example (FEAT-463)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default="swarm_crew.yaml",
        help="Path to the crew YAML config file (default: swarm_crew.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    return parser.parse_args()


def _configure_logging(level: str) -> None:
    """Configure root logger with the given level.

    Args:
        level: Logging level string (DEBUG, INFO, WARNING, ERROR).
    """
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("mautrix").setLevel(logging.WARNING)


def _setup_bots() -> None:
    """Register the 4 example agents in the BotManager.

    In a real deployment, agents are pre-configured in ``agents.yaml``.
    Replace the stub with real AI-Parrot ``Agent`` or ``Chatbot`` instances.

    The four agents required by swarm_crew.yaml:
      - "web-researcher"     → chatbot_id for the researcher agent
      - "financial-analyst"  → chatbot_id for the analyst agent
      - "report-writer"      → chatbot_id for the writer agent
      - "synthesis-agent"    → chatbot_id for the summarizer agent
    """
    logger = logging.getLogger(__name__)
    logger.info("Setting up BotManager agents for the swarm …")

    try:
        from parrot.manager import BotManager  # type: ignore

        # Example: registering real agents looks like:
        #
        #   from parrot.clients.openai import OpenAIClient
        #   from parrot.bots.agent import Agent
        #
        #   client = OpenAIClient(model="gpt-4o")
        #
        #   analyst = Agent(
        #       name="financial-analyst",
        #       client=client,
        #       system_prompt="You are a financial analyst ...",
        #   )
        #   BotManager.register("financial-analyst", analyst)
        #
        # Agents that should be able to ask peers questions automatically
        # get an AgentSwarmToolkit attached by MatrixCrewTransport.start()
        # (as long as BotManager.get_bot(chatbot_id) resolves and the bot
        # exposes .tool_manager) — no extra wiring needed here.
        logger.warning(
            "No real agents configured — edit _setup_bots() to register your agents."
        )

    except ImportError:
        logger.warning("BotManager not available — skipping agent setup")


async def _run_crew(config_path: str) -> None:
    """Load the swarm crew config and run until interrupted.

    Args:
        config_path: Path to the YAML crew configuration file.
    """
    from parrot.integrations.matrix.crew import MatrixCrewTransport  # type: ignore

    logger = logging.getLogger(__name__)

    logger.info("Loading swarm crew config from %s", config_path)
    transport = MatrixCrewTransport.from_yaml(config_path)

    for ch in transport._config.channels:
        logger.info(
            "Channel #%s (%s, policy=%s): agents=%s",
            ch.name,
            ch.visibility,
            ch.answer_policy,
            ", ".join(ch.agents) or "(none declared)",
        )

    if transport._config.tunnels.enabled:
        logger.info(
            "Tunnels enabled: ttl_minutes=%d, max_hops=%d, echo=%s",
            transport._config.tunnels.ttl_minutes,
            transport._config.tunnels.max_hops,
            transport._config.tunnels.echo_summary_to_channel,
        )

    collab = transport._config.collaborative
    if collab is None:
        logger.warning(
            "No 'collaborative:' section found — swarm-policy channels and "
            "'!investigate' will not start sessions."
        )
    else:
        logger.info(
            "Collaborative mode: command='%s', max_concurrent_sessions=%d, "
            "cooldown_seconds=%.0f, summarizer='%s'",
            collab.command_prefix,
            collab.max_concurrent_sessions,
            collab.cooldown_seconds,
            collab.summarizer_agent or "none",
        )

    # Set up graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received — stopping swarm …")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    async with transport:
        logger.info("Matrix agents swarm is running. Press Ctrl+C to stop.")
        logger.info(
            "Agents: %s",
            ", ".join(
                f"@{e.mxid_localpart}:{transport._config.server_name}"
                for e in transport._config.agents.values()
            ),
        )
        logger.info("General room: %s", transport._config.general_room_id)
        logger.info(
            "Coordinator commands (any room): !channels, !agents, !tunnels, "
            "!investigate <question>"
        )
        await stop_event.wait()

    logger.info("Swarm stopped cleanly.")


def main() -> int:
    """Entry point for the swarm example.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    args = _parse_args()
    _configure_logging(args.log_level)
    logger = logging.getLogger(__name__)

    _setup_bots()

    try:
        asyncio.run(_run_crew(args.config))
        return 0
    except FileNotFoundError as exc:
        logger.error("Config file not found: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
