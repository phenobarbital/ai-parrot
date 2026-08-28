"""Web-navigation agent example — WebBrowsingToolkit + Chrome profile.

Shows how to build an Agent whose browser runs on YOUR Google Chrome
profile: the constructor receives the Chrome user-data directory (and
optionally the profile folder inside it), so every catalogued action runs
with the profile's session cookies, saved logins and password keyring.
The browser binary itself is managed by the driver (SeleniumSetup /
Playwright) — only the profile paths are injected here.

The agent operates websites exclusively through the action catalog
(``examples/webbrowsing/catalog`` by default — regenerate it with
``examples/webbrowsing/seed_catalog.py``): from a natural-language
request it prepares ONE structured ``WebTaskRequest``
({site, action, data}) and calls ``execute_web_task``, which replays the
catalogued script deterministically.

Usage::

    python examples/agents/webbrowser/webbrowsing_agent.py "dame las citas del tag love"

    # Against your real Chrome profile (close Chrome first — it locks
    # the profile directory; or point at a copy):
    CHROME_USER_DATA=~/.config/google-chrome \\
    CHROME_PROFILE="Profile 1" \\
    python examples/agents/webbrowser/webbrowsing_agent.py "inicia sesión en quotes"
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional, Union

from parrot.bots.agent import Agent
from parrot_tools.browsing import WebBrowsingToolkit

DEFAULT_CATALOG = Path(__file__).parents[2] / "webbrowsing" / "catalog"

SYSTEM_PROMPT = """You are a web-navigation assistant that operates websites
through a catalog of pre-recorded, deterministic action scripts.

From the user's request, prepare ONE structured request and call
`execute_web_task`:
  {"site": <site ref>, "action": <action>, "data": {<params>}}
or, for multi-step flows:
  {"site": ..., "plan": [{"action": ..., "data": {...}}, ...]}

If it returns status="error", repair the request from the hints and retry
(`unknown_site` lists known sites, `unknown_action` lists the catalog,
`missing_params` names the fields to fill). Use `list_sites` /
`list_site_actions` when unsure what a site offers. Never improvise
selectors or navigation steps. Answer in the user's language.
"""


class WebNavigatorAgent(Agent):
    """Agent that drives websites through a catalogued-action toolkit.

    Args:
        user_data_dir: Chrome user-data directory whose cookies, saved
            sessions and keyring the browser should reuse (e.g.
            ``~/.config/google-chrome``). ``None`` starts a clean,
            profile-less browser. Close Chrome (or point at a copy)
            before running — Chrome locks a profile in use.
        profile_directory: Profile folder inside ``user_data_dir``
            (``"Default"``, ``"Profile 1"``, ...). Ignored when
            ``user_data_dir`` is not set.
        catalog_dir: Action-catalog root (one folder per site, one JSON
            per action).
        driver_type: ``"playwright"`` or ``"selenium"`` — fixed for the
            agent's lifetime.
        headless: Run the browser headless.
        **kwargs: Forwarded to :class:`~parrot.bots.agent.Agent`
            (``llm``, ``use_llm``, ...).
    """

    def __init__(
        self,
        user_data_dir: Optional[Union[str, Path]] = None,
        profile_directory: str = "Default",
        catalog_dir: Union[str, Path] = DEFAULT_CATALOG,
        driver_type: str = "playwright",
        headless: bool = True,
        **kwargs,
    ):
        self.browsing_toolkit = WebBrowsingToolkit(
            catalog_dir=catalog_dir,
            driver_type=driver_type,
            browser="chrome",
            headless=headless,
            user_data_dir=(
                str(Path(user_data_dir).expanduser()) if user_data_dir else None
            ),
            profile_directory=profile_directory if user_data_dir else None,
            # With a real profile, launch the system Chrome (Playwright
            # channel) so keyring-encrypted data is readable.
            browser_channel="chrome" if user_data_dir else None,
            confirm_runs=False,  # demo; keep True for production sites
        )
        super().__init__(
            name="WebNavigator",
            tools=[self.browsing_toolkit],
            system_prompt=SYSTEM_PROMPT,
            **kwargs,
        )

    async def close(self):
        """Shut down the persistent browser session with the agent."""
        await self.browsing_toolkit.close_browser()


async def main() -> None:
    question = (
        " ".join(sys.argv[1:])
        or "Inicia sesión en quotes y dime qué citas hay en la portada"
    )
    agent = WebNavigatorAgent(
        user_data_dir=os.getenv("CHROME_USER_DATA"),
        profile_directory=os.getenv("CHROME_PROFILE", "Default"),
        headless=os.getenv("HEADLESS", "1") != "0",
    )
    await agent.configure()
    try:
        answer, _response = await agent.invoke(question)
        print(answer)
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
