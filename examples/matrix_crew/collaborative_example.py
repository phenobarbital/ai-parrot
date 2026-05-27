"""
Matrix Collaborative Multi-Agent Crew Example
=============================================

Demonstrates the ``!investigate`` collaborative investigation mode.

How collaborative sessions work:
  1. A human user sends ``!investigate <question>`` in the general room.
  2. All non-summarizer agents investigate the question in parallel (INVESTIGATING).
  3. Agents refine their findings by seeing each other's results (CROSS_POLLINATING).
  4. A dedicated summarizer agent synthesises the final answer (SYNTHESIZING).
  5. The synthesis is posted to the room (COMPLETED).

Room topology:
  GENERAL ROOM
    Members: @parrot-bot, @analyst, @researcher, @summarizer
    Trigger: "!investigate <question>" → starts collaborative session
    Normal:  "@analyst question" → direct routing (unchanged)

Agents in this example:
  @analyst    — Financial Analyst (market analysis, equity research)
  @researcher — Web Researcher (web search, news retrieval)
  @summarizer — Synthesis Agent (produces final consolidated answer)

Prerequisites (same as matrix_crew_example.py):
  1. A Matrix homeserver (Synapse or Dendrite) running
  2. Application Service registration file generated and registered
  3. Rooms created with agents invited
  4. Environment variables set (see below)
  5. Agents configured in BotManager (or agents.yaml)

Usage:
    # Set required environment variables
    export MATRIX_AS_TOKEN=<your-as-token>
    export MATRIX_HS_TOKEN=<your-hs-token>

    # Run with the collaborative config
    python collaborative_example.py --config collaborative_crew.yaml

    # With debug logging
    python collaborative_example.py --config collaborative_crew.yaml --log-level DEBUG

Expected behaviour:
  - Sending "@analyst what is AAPL?" routes to the analyst directly (unchanged).
  - Sending "!investigate What are the growth prospects for renewable energy?"
    triggers all agents to investigate, cross-pollinate, and synthesise.
  - Sending a second "!investigate" while one is active returns a polite rejection.
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
        description="Matrix Collaborative Crew — AI-Parrot example",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default="collaborative_crew.yaml",
        help="Path to the crew YAML config file (default: collaborative_crew.yaml)",
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
    """Register the 3 example agents in the BotManager.

    In a real deployment, agents are pre-configured in ``agents.yaml``.
    Replace the stub with real AI-Parrot ``Agent`` or ``Chatbot`` instances.

    The three agents required for collaborative mode:
      - "financial-analyst"  → chatbot_id for the analyst agent
      - "web-researcher"     → chatbot_id for the researcher agent
      - "synthesis-agent"    → chatbot_id for the summarizer agent
    """
    logger = logging.getLogger(__name__)
    logger.info("Setting up BotManager agents for collaborative crew …")

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
        #       system_prompt=(
        #           "You are a financial analyst specialising in equity research "
        #           "and market analysis. When asked to investigate a question, "
        #           "provide a structured analysis with your key findings."
        #       ),
        #   )
        #   BotManager.register("financial-analyst", analyst)
        #
        #   researcher = Agent(
        #       name="web-researcher",
        #       client=client,
        #       system_prompt=(
        #           "You are a research specialist with web search capabilities. "
        #           "When investigating a question, retrieve and summarise relevant "
        #           "news and research findings."
        #       ),
        #   )
        #   BotManager.register("web-researcher", researcher)
        #
        #   summarizer = Agent(
        #       name="synthesis-agent",
        #       client=client,
        #       system_prompt=(
        #           "You are a synthesis specialist. Given findings from multiple "
        #           "analysts and researchers, produce a comprehensive, balanced "
        #           "summary highlighting agreements, discrepancies, and conclusions."
        #       ),
        #   )
        #   BotManager.register("synthesis-agent", summarizer)
        #
        logger.warning(
            "No real agents configured — edit _setup_bots() to register your agents."
        )

    except ImportError:
        logger.warning("BotManager not available — skipping agent setup")


async def _run_crew(config_path: str) -> None:
    """Load the collaborative crew config and run until interrupted.

    Validates that the collaborative section is present before starting.

    Args:
        config_path: Path to the YAML crew configuration file.
    """
    from parrot.integrations.matrix.crew import MatrixCrewTransport  # type: ignore

    logger = logging.getLogger(__name__)

    logger.info("Loading collaborative crew config from %s", config_path)
    transport = MatrixCrewTransport.from_yaml(config_path)

    # Validate collaborative config
    collab = transport._config.collaborative
    if collab is None:
        logger.error(
            "No 'collaborative:' section found in %s. "
            "The !investigate command will not be available.",
            config_path,
        )
    else:
        logger.info(
            "Collaborative mode enabled: command='%s', rounds=%d, summarizer='%s'",
            collab.command_prefix,
            collab.max_rounds,
            collab.summarizer_agent or "none",
        )
        logger.info(
            "Trigger a session: send '%s <question>' in the general room",
            collab.command_prefix,
        )

    # Set up graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received — stopping crew …")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    async with transport:
        logger.info("Matrix collaborative crew is running. Press Ctrl+C to stop.")
        logger.info(
            "Agents: %s",
            ", ".join(
                f"@{e.mxid_localpart}:{transport._config.server_name}"
                for e in transport._config.agents.values()
            ),
        )
        logger.info("General room: %s", transport._config.general_room_id)
        await stop_event.wait()

    logger.info("Crew stopped cleanly.")


def main() -> int:
    """Entry point for the collaborative crew example.

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
