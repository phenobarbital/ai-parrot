"""Hooba bookkeeping assistant (drafts only) — FEAT-602 example.

Usage::

    python examples/agents/finance/hooba_agent.py --smoke          # no LLM: whoami + draft invoices
    python examples/agents/finance/hooba_agent.py "crea un borrador de factura para ACME por 100 €"
"""
import argparse
import asyncio
import json
import logging
from typing import Any, Dict

from parrot.auth.broker import CredentialBroker
from parrot.bots.agent import Agent
from parrot_tools.hooba import HoobaSettings, HoobaToolkit
from parrot_tools.hooba.credentials import register_hooba_provider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You help a Spanish autónomo keep Hooba up to date. You can ONLY create drafts: sales-invoice drafts,
purchase-invoice (expense) drafts, and drafts from a BBVA movements Excel. You never issue, confirm, send or delete.
Always run a BBVA import with dry_run=true first, show the plan, and apply only after the user agrees.
Every expense draft needs human review before it is confirmed in Hooba."""


def build_toolkit(settings: HoobaSettings | None = None) -> HoobaToolkit:
    """HoobaToolkit with an env-backed broker provider."""
    broker = CredentialBroker()
    register_hooba_provider(broker)
    return HoobaToolkit(settings or HoobaSettings.from_env(), broker)


async def smoke(toolkit: HoobaToolkit) -> Dict[str, Any]:
    """Deterministic check without an LLM."""
    whoami_result = await toolkit.hooba_whoami()
    drafts_result = await toolkit.hooba_list_drafts("invoice")
    return {"whoami": whoami_result, "drafts": drafts_result}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Hooba bookkeeping assistant (drafts only)")
    parser.add_argument("--smoke", action="store_true", help="Run deterministic smoke test (no LLM)")
    parser.add_argument("prompt", nargs="*", help="User prompt for the agent")
    args = parser.parse_args()

    if args.smoke:
        toolkit = build_toolkit()
        result = await smoke(toolkit)
        # Log a JSON summary without personal fields
        summary = {
            "whoami_status": result["whoami"].get("status"),
            "drafts_status": result["drafts"].get("status"),
            "drafts_count": len(result["drafts"].get("result", [])),
        }
        logger.info("Smoke test result: %s", json.dumps(summary))
        print(json.dumps(summary, indent=2))
        return

    # Normal agent mode
    prompt_text = " ".join(args.prompt) if args.prompt else None
    if not prompt_text:
        parser.error("A prompt is required when not running --smoke")

    toolkit = build_toolkit()
    agent = Agent(
        name="HoobaAssistant",
        system_prompt=SYSTEM_PROMPT,
        tools=toolkit.get_tools(),
    )
    await agent.configure()
    response = await agent.ask(prompt_text)
    print(response)


if __name__ == "__main__":
    asyncio.run(main())
