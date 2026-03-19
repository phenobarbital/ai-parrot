"""
Matrix Multi-Agent Crew Example
================================

Launches a crew of 3 agents on a Matrix homeserver:

1. Financial Analyst  — @analyst    — dedicated room + general room
2. Research Assistant  — @researcher — dedicated room + general room
3. General Assistant   — @assistant  — general room only (default handler)

Architecture:
  - Each agent uses a virtual MXID via the Matrix Application Service protocol
  - The coordinator bot maintains a pinned status board in the general room
  - Messages are routed by @mention in the general room
  - Messages in dedicated rooms go directly to that agent (no @mention needed)

Room topology:
  GENERAL ROOM
    Members: @parrot-coordinator, @analyst, @researcher, @assistant
    Routing: @mention → specific agent; no mention → @assistant (default)
    Pinned: live status board (updated on every status change)

  ANALYST ROOM:   @analyst only — direct conversations about finance
  RESEARCHER ROOM: @researcher only — direct conversations about research

Prerequisites:
  1. A Matrix homeserver (Synapse or Dendrite) running and accessible
  2. Application Service registration file (generate with registration.py):
       python -m parrot.integrations.matrix.registration \
           --server-name example.com \
           --output registration.yaml
  3. Register the AS with Synapse: add the registration.yaml path to the
     homeserver.yaml ``app_service_config_files`` list and restart Synapse.
  4. Create the rooms:
       - General room: invite @parrot-coordinator:example.com + agents
       - Analyst room: create, invite @analyst:example.com
       - Researcher room: create, invite @researcher:example.com
  5. Set environment variables (see matrix_crew.yaml)
  6. Configure agents in parrot/agents/agents.yaml (or BotManager)

Usage:
    # Export required environment variables
    export MATRIX_HOMESERVER_URL=https://matrix.example.com
    export MATRIX_SERVER_NAME=example.com
    export MATRIX_AS_TOKEN=<your-as-token-from-registration.yaml>
    export MATRIX_HS_TOKEN=<your-hs-token-from-registration.yaml>
    export MATRIX_GENERAL_ROOM_ID=!general-room-id:example.com
    export MATRIX_ANALYST_ROOM_ID=!analyst-room-id:example.com
    export MATRIX_RESEARCHER_ROOM_ID=!researcher-room-id:example.com

    # Run the example
    python matrix_crew_example.py --config matrix_crew.yaml

    # With custom log level
    python matrix_crew_example.py --config matrix_crew.yaml --log-level DEBUG

Expected behavior:
  - Agents appear as virtual Matrix users (their own avatars, display names)
  - The coordinator posts a pinned status board in the general room
  - When a user sends "@analyst what is AAPL P/E?" the analyst responds
  - When a user sends a message in the analyst's dedicated room, no @mention needed
  - Messages with no @mention in the general room go to the general assistant
"""
import argparse
import asyncio
import logging
import signal
import sys
from typing import Optional


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed argument namespace with ``config`` and ``log_level`` fields.
    """
    parser = argparse.ArgumentParser(
        description="Matrix Multi-Agent Crew — AI-Parrot example",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default="matrix_crew.yaml",
        help="Path to the crew YAML config file (default: matrix_crew.yaml)",
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
    # Quiet down noisy third-party loggers
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("mautrix").setLevel(logging.WARNING)


def _setup_bots() -> None:
    """Register the 3 example agents in the BotManager.

    In a real deployment, agents are already configured in ``agents.yaml``.
    This function shows how to register them programmatically.

    The agents created here are minimal stubs; replace them with real
    AI-Parrot ``Agent`` or ``Chatbot`` instances backed by actual LLM clients.
    """
    logger = logging.getLogger(__name__)
    logger.info("Setting up BotManager agents …")

    try:
        from parrot.manager import BotManager  # type: ignore

        # Each agent must be registered with its chatbot_id matching the YAML.
        # Example with real agents:
        #
        #   from parrot.clients.openai import OpenAIClient
        #   from parrot.bots.agent import Agent
        #
        #   client = OpenAIClient(model="gpt-4o")
        #   analyst = Agent(
        #       name="finance-analyst",
        #       client=client,
        #       system_prompt="You are a financial analyst specializing in equity research.",
        #   )
        #   BotManager.register("finance-analyst", analyst)
        #
        # For this example we just log a warning that real bots are not configured.
        logger.warning(
            "No real agents configured. "
            "Edit _setup_bots() in matrix_crew_example.py to register your agents."
        )

    except ImportError:
        logger.warning("BotManager not available — skipping agent setup")


async def _run_crew(config_path: str) -> None:
    """Load the crew config and run until interrupted.

    Args:
        config_path: Path to the YAML crew configuration file.
    """
    from parrot.integrations.matrix.crew import MatrixCrewTransport  # type: ignore

    logger = logging.getLogger(__name__)

    # Load config and create transport
    logger.info("Loading crew config from %s", config_path)
    transport = MatrixCrewTransport.from_yaml(config_path)

    # Set up graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received — stopping crew …")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # Start the crew (async context manager handles lifecycle)
    async with transport:
        logger.info("Matrix crew is running. Press Ctrl+C to stop.")
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
    """Entry point for the matrix crew example.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    args = _parse_args()
    _configure_logging(args.log_level)
    logger = logging.getLogger(__name__)

    # Register agents (replace with real agents in production)
    _setup_bots()

    # Run the crew
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
