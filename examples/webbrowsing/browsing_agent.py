"""Example Agent wired with the WebBrowsingToolkit and a pre-built catalog.

The agent receives natural-language requests ("inicia sesión en quotes",
"dame las citas del tag love"), matches them against the catalogued
actions of the site (via ``list_sites`` / ``list_site_actions``) and then
executes the chosen script deterministically with ``run_site_action`` /
``run_site_sequence`` — the LLM decides WHICH guion to run and with WHAT
parameters, never HOW to click.

Requires an LLM provider credential (e.g. ``GOOGLE_API_KEY`` for the
default Google client). For a no-LLM, fully deterministic run of the same
catalog, see ``local_demo.py``.

Usage::

    python examples/webbrowsing/browsing_agent.py "¿Cuáles son los top tags?"
"""
import asyncio
import sys
from pathlib import Path

from parrot.bots.agent import Agent
from parrot_tools.browsing import WebBrowsingToolkit

CATALOG_DIR = Path(__file__).parent / "catalog"

SYSTEM_PROMPT = """You are a web-navigation assistant that operates websites
through a catalog of pre-recorded, deterministic action scripts.

Workflow — ALWAYS follow it in this order:
1. Resolve the site: call `list_sites` and match the user's wording
   against site titles/aliases (e.g. "quotes" -> quotes-toscrape-com).
2. Discover capabilities: call `list_site_actions` for that site and pick
   the action whose description matches the user's intent. Fill its
   declared params from the user's request.
3. Execute: call `run_site_action` (single intent) or `run_site_sequence`
   (multi-step plan). Prerequisites like login are injected automatically.
4. Answer with the extracted data, in the user's language.

Never invent selectors or improvise navigation steps: if no catalogued
action covers the request, say so and list what IS available.
"""


async def build_agent(headless: bool = True) -> Agent:
    """Create and configure the browsing agent.

    Args:
        headless: Run the browser headless. Use ``False`` to watch the
            catalogued scripts drive the page.

    Returns:
        A configured :class:`~parrot.bots.agent.Agent`.
    """
    toolkit = WebBrowsingToolkit(
        catalog_dir=CATALOG_DIR,
        driver_type="playwright",   # fixed at construction
        browser="chrome",
        headless=headless,
        # Point at a real Chrome profile to reuse logged-in sessions:
        # user_data_dir="~/.config/google-chrome",
        # profile_directory="Default",
        # browser_channel="chrome",
        confirm_runs=False,  # demo sandbox — enable HITL for real sites
    )
    agent = Agent(
        name="WebNavigator",
        tools=[toolkit],
        system_prompt=SYSTEM_PROMPT,
    )
    await agent.configure()
    return agent


async def main() -> None:
    question = (
        " ".join(sys.argv[1:])
        or "Inicia sesión en quotes y dime qué citas hay en la portada"
    )
    agent = await build_agent()
    answer, _response = await agent.invoke(question)
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())
