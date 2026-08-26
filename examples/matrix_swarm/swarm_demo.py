#!/usr/bin/env python3
"""
Matrix Swarm Sample Demo (FEAT-464)
===================================

A runnable demo of a 4-agent swarm with multi-provider LLMs and
collaborative sessions on a local Matrix homeserver.

This example:
  - Loads 4 agents from agents.yaml with different LLM providers
  - Registers them in BotManager
  - Starts a MatrixCrewTransport with swarm config
  - Runs until Ctrl+C (graceful shutdown)

The agents:
  1. Web Researcher (OpenAI gpt-4o) — searches & compiles information
  2. Financial Analyst (Anthropic Claude) — analyzes data & trends
  3. Report Writer (Google Gemini) — synthesizes findings into prose
  4. Synthesizer (NVIDIA Llama) — integrates perspectives & concludes

Quick start:
  1. Set up local Matrix (see ../../docker-compose.matrix.yml and
     ../../scripts/matrix/bootstrap.sh)
  2. Copy .env.example → .env and fill in API keys + Matrix tokens
  3. Run: python swarm_demo.py

See README.md for full step-by-step guide.
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Any

import yaml

# Third-party imports
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed argument namespace with config and agents paths.
    """
    parser = argparse.ArgumentParser(
        description="Matrix Swarm Sample — 4-agent demo (FEAT-464)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("Example:\n" "  python swarm_demo.py\n" "  python swarm_demo.py --agents custom_agents.yaml"),
    )
    parser.add_argument(
        "--config",
        default="swarm_config.yaml",
        help="Path to swarm config YAML (default: swarm_config.yaml)",
    )
    parser.add_argument(
        "--agents",
        default="agents.yaml",
        help="Path to agents YAML (default: agents.yaml)",
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
    # Suppress verbose dependency logs
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("mautrix").setLevel(logging.WARNING)


def _load_agents_from_yaml(agents_path: str) -> dict[str, dict[str, Any]]:
    """Load agent definitions from YAML.

    Args:
        agents_path: Path to agents.yaml.

    Returns:
        Dict mapping chatbot_id → agent definition dict.

    Raises:
        FileNotFoundError: If agents.yaml does not exist.
        yaml.YAMLError: If YAML is malformed.
    """
    path = Path(agents_path)
    if not path.exists():
        raise FileNotFoundError(f"Agents file not found: {agents_path}")

    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("agents", {})


def _setup_agents(agents_config: dict[str, dict[str, Any]]) -> list[str]:
    """Create and register agents in BotManager.

    For each agent in agents_config, instantiate a BasicAgent with
    the specified LLM provider, system prompt, and tools.

    Args:
        agents_config: Dict mapping chatbot_id → agent definition.

    Returns:
        List of successfully registered chatbot_ids.

    Raises:
        ImportError: If required modules are not available.
    """
    from parrot.bots.agent import BasicAgent  # type: ignore
    from parrot.manager import BotManager  # type: ignore

    logger = logging.getLogger(__name__)
    registered = []

    for chatbot_id, agent_def in agents_config.items():
        try:
            name = agent_def.get("name", chatbot_id)
            llm = agent_def.get("llm")
            system_prompt = agent_def.get("system_prompt", "")
            tools_list = agent_def.get("tools", [])

            # Determine if agent has tools
            use_tools = len(tools_list) > 0

            logger.info(
                "Creating agent %s (llm=%s, tools=%s)",
                chatbot_id,
                llm,
                ", ".join(tools_list) if tools_list else "none",
            )

            # Instantiate BasicAgent
            # - llm: "provider:model" string is handled by BasicAgent internally
            # - chatbot_id: passed via **kwargs (required for BotManager lookup)
            # - use_tools: enables the ToolManager
            agent = BasicAgent(
                name=name,
                agent_id=chatbot_id,
                use_llm=llm,  # BasicAgent uses 'use_llm', not 'llm'
                system_prompt=system_prompt,
                use_tools=use_tools,
                chatbot_id=chatbot_id,  # Passed as **kwargs
            )

            # Register in BotManager by chatbot_id
            BotManager.add_agent(agent)
            registered.append(chatbot_id)
            logger.info("✓ Registered agent %s", chatbot_id)

        except Exception:
            logger.exception("Failed to create agent %s", chatbot_id)

    if not registered:
        logger.warning("No agents were successfully registered!")
    return registered


async def _run_swarm(config_path: str) -> None:
    """Load the swarm config and run until interrupted.

    Args:
        config_path: Path to the swarm_config.yaml file.

    Raises:
        FileNotFoundError: If config file does not exist.
    """
    from parrot.integrations.matrix.crew import MatrixCrewTransport  # type: ignore

    logger = logging.getLogger(__name__)

    # Load config
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.info("Loading swarm config from %s", config_path)
    transport = MatrixCrewTransport.from_yaml(str(path))

    # Log channel info
    for ch in transport._config.channels:
        logger.info(
            "Channel #%s (%s, policy=%s): agents=%s",
            ch.name,
            ch.visibility,
            ch.answer_policy,
            ", ".join(ch.agents) or "(none declared)",
        )

    # Log tunnel info
    if transport._config.tunnels.enabled:
        logger.info(
            "Tunnels enabled: ttl_minutes=%d, max_hops=%d, echo=%s",
            transport._config.tunnels.ttl_minutes,
            transport._config.tunnels.max_hops,
            transport._config.tunnels.echo_summary_to_channel,
        )

    # Log collaborative settings
    collab = transport._config.collaborative
    if collab:
        logger.info(
            "Collaborative mode: max_concurrent=%d, cooldown=%.0f, summarizer=%s",
            collab.max_concurrent_sessions,
            collab.cooldown_seconds,
            collab.summarizer_agent or "none",
        )
    else:
        logger.warning("No 'collaborative:' section — swarm-policy channels disabled")

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received — stopping swarm …")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # Run the transport
    async with transport:
        logger.info("Matrix swarm is running. Press Ctrl+C to stop.")
        logger.info("General room: %s", transport._config.general_room_id)
        logger.info(
            "Agents: %s",
            ", ".join(
                f"@{agent.mxid_localpart}:{transport._config.server_name}"
                for agent in transport._config.agents.values()
            ),
        )
        logger.info("Coordinator commands (any room): !channels, !agents, !tunnels, !investigate")
        await stop_event.wait()

    logger.info("Swarm stopped cleanly.")


def main() -> int:
    """Entry point for the swarm demo.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    args = _parse_args()

    # Load environment variables from .env
    if load_dotenv is not None:
        env_file = Path(".env")
        if env_file.exists():
            load_dotenv(".env")

    _configure_logging(args.log_level)
    logger = logging.getLogger(__name__)

    try:
        # Load agents from YAML
        logger.info("Loading agents from %s", args.agents)
        agents_config = _load_agents_from_yaml(args.agents)
        if not agents_config:
            logger.error("No agents found in %s", args.agents)
            return 1

        logger.info("Found %d agent(s)", len(agents_config))

        # Create and register agents in BotManager
        registered = _setup_agents(agents_config)
        if not registered:
            logger.error("Failed to register any agents")
            return 1

        logger.info("Successfully registered %d agent(s)", len(registered))

        # Run the swarm
        asyncio.run(_run_swarm(args.config))
        return 0

    except FileNotFoundError as exc:
        logger.error("File not found: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception:
        logger.exception("Fatal error occurred")
        return 1


if __name__ == "__main__":
    sys.exit(main())
