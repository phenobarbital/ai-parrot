"""OdooHelpdesk — test agent for the TROC helpdesk on Odoo 19 (staging).

Wires two toolkits against ``https://pokemon.helpdesk.staging.trocdigital.io/``:

* :class:`~parrot_tools.odoo.OdooToolkit` with the **JSON-2 transport**
  (Odoo 19+ External API) authenticated by ``ODOO_HELPDESK_APIKEY`` — the
  key carries administrative rights, so every ORM-level tool (search, read,
  create, update, aggregate, diagnostics) runs through it.
* :class:`~parrot_tools.browsing.WebBrowsingToolkit` driving a Playwright
  browser through a catalog of deterministic actions. The ``login`` action
  authenticates with ``ODOO_HELPDESK_USER`` / ``ODOO_HELPDESK_PASSWORD`` via a
  ``credential_resolver`` — the catalog never stores credentials.

Environment (``env/.env`` through ``navconfig``, or the process env)::

    ODOO_HELPDESK_URL       base URL (default: the staging helpdesk)
    ODOO_HELPDESK_USER      web login (email)
    ODOO_HELPDESK_PASSWORD  web password (browser flows only)
    ODOO_HELPDESK_APIKEY    API key (JSON-2 bearer, admin)
    ODOO_HELPDESK_DATABASE  database name (default ``pokemon_staging``). It must
                            be explicit: ``OdooToolkit`` falls back to the global
                            ``ODOO_DATABASE`` when it receives an empty value
    ODOO_HELPDESK_HEADLESS  ``0`` shows the browser window (default ``1``)

The helpdesk app on this instance is Softhealer's ``sh_all_in_one_helpdesk``
(``sh.helpdesk.ticket``), not Odoo Enterprise's ``helpdesk.ticket``.

Three knowledge toolkits complete the agent (all data lives under
``agents/odoo_hd/``):

* :class:`~parrot.tools.working_memory.WorkingMemoryToolkit` (``wm_*``) —
  scratch store for intermediate results (ticket lists, aggregates) so the
  agent can chain analyses without re-querying Odoo.
* :class:`~parrot.knowledge.wiki.toolkit.LLMWikiToolkit` (``wiki_*``) — the
  agent's own knowledge graph (SQLite plane in ``odoo_hd/wiki/``, wiki name
  ``odoo_helpdesk``), seeded with the instance profile on first configure.
* :class:`~parrot.knowledge.bookstore.toolkit.BookstoreToolkit`
  (``bookstore_*``) — read-only research over the library in
  ``odoo_hd/library/``, which holds the *Odoo 19 Development Cookbook, 6E*
  code companion (one "book" per chapter, generated from
  https://github.com/PacktPublishing/Odoo-19-Development-Cookbook-6E into
  ``odoo_hd/library_sources/``) and the official Odoo 19 documentation scraped
  from https://www.odoo.com/documentation/19.0/ by ``odoo_hd/scrape_odoo_docs.py``
  (one Markdown "book" per section under ``library_sources/odoo-docs/``).
  Build the library once with::

      export PARROT_LIBRARY_DIR=$PWD/agents/odoo_hd/library
      python agents/odoo_hd/scrape_odoo_docs.py --section developer
      python agents/odoo_hd/scrape_odoo_docs.py --section administration
      bookstore add-folder agents/odoo_hd/library_sources -r --llm google:gemini-3.1-flash-lite
      PARROT_NO_AUTO_LLM=1 python agents/odoo_hd/retitle_library.py


Usage::

    python agents/odoo_hd.py --check            # verify API + web login, no LLM
    python agents/odoo_hd.py --check --no-web   # API verification only
    python agents/odoo_hd.py "¿Cuántos tickets abiertos hay?"
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from parrot.bots.agent import Agent
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore
from parrot.knowledge.bookstore.toolkit import BookstoreToolkit
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
from parrot.registry import register_agent
from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot_tools.browsing import WebBrowsingToolkit
from parrot_tools.odoo import OdooToolkit
from parrot_tools.scraping.models import Authenticate

__all__ = (
    "OdooHelpdesk",
    "OdooHelpdeskSettings",
    "build_odoo_toolkit",
    "build_browsing_toolkit",
    "HelpdeskBrowsingToolkit",
    "build_working_memory_toolkit",
    "build_wiki_toolkit",
    "build_bookstore_toolkit",
    "resolve_helpdesk_credentials",
    "seed_catalog",
)

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://pokemon.helpdesk.staging.trocdigital.io/"
DEFAULT_DATABASE = "pokemon_staging"
SITE_NAME = "odoo-helpdesk"
CREDENTIAL_PROVIDER = "odoo-helpdesk"
TICKET_MODEL = "sh.helpdesk.ticket"
TICKETS_ACTION = "sh_all_in_one_helpdesk.sh_helpdesk_ticket_action"
SLA_ACTION = "sh_all_in_one_helpdesk.sh_helpdesk_ticket_sla_action"
ADMIN_GROUPS = ("base.group_system", "base.group_erp_manager")
AGENT_HOME = Path(__file__).parent / "odoo_hd"
CATALOG_DIR = AGENT_HOME / "catalog"
LIBRARY_DIR = AGENT_HOME / "library"
LIBRARY_SOURCES_DIR = AGENT_HOME / "library_sources"
WIKI_DIR = AGENT_HOME / "wiki"
WIKI_NAME = "odoo_helpdesk"
DEFAULT_BOOKSTORE_LLM = "google:gemini-3.1-flash-lite"

SYSTEM_PROMPT = f"""You are the test assistant for the TROC Helpdesk, an Odoo 19
instance at {DEFAULT_URL}. You have two complementary ways to operate it.

1. ODOO API (preferred for data): the Odoo tools (search_records, get_record,
   aggregate_records, create_record, update_record, fields_get, get_odoo_profile,
   diagnose_access, ...) run over the JSON-2 External API with an ADMIN API key.
   The helpdesk model is `{TICKET_MODEL}` (Softhealer All-in-One Helpdesk):
   tickets have `name`, `stage_id`, `team_id`, `user_id`, `partner_id`,
   `priority_new`, `category_id`, `create_date`. Related models:
   `helpdesk.stages`, `sh.helpdesk.team`, `helpdesk.category`, `helpdesk.tags`,
   `sh.helpdesk.ticket.type`, `sh.helpdesk.sla`. Call `fields_get` when unsure
   about a field. NEVER guess field names.

2. WEB BROWSER — ONLY ON EXPLICIT REQUEST: use the browsing tools solely when
   the user literally asks to open, navigate, show or check something "in the
   browser" / "en el navegador" / "en la web" / "en la interfaz". Never browse
   to double-check, confirm or complement data you already obtained from the
   API, and never browse for data questions (counts, lists, fields, records):
   the API is the single source of truth for those. The browsing tools replay
   catalogued, deterministic actions on site "{SITE_NAME}" with the web
   user's session. Every run result carries `current_url` (where the browser
   ended): report that value verbatim and NEVER invent or reconstruct an Odoo
   URL. Prepare ONE structured request and call `execute_web_task`:
     {{"site": "{SITE_NAME}", "action": <action>, "data": {{<params>}}}}
   Available actions: login, home, tickets, ticket (param ticket_id),
   sla-analysis. Login is injected automatically as a prerequisite. If the
   tool returns status="error", repair the request from its hints and retry.
   Never improvise selectors or navigation steps.

3. WORKING MEMORY (`wm_*` tools): park intermediate results (ticket lists,
   aggregates, ids you will need again) with `wm_store_result` and read them
   back with `wm_get_result` / `wm_search_stored` instead of re-querying Odoo.

4. KNOWLEDGE WIKI (`wiki_*` tools, wiki name "{WIKI_NAME}"): your own knowledge
   graph about this instance. Before exploring, `wiki_query` / `wiki_search`
   it. When you learn a durable fact (a field mapping, a stage workflow, a
   team convention, a gotcha), FILE IT with `wiki_remember` (short note) or
   `wiki_create_page` (structured page) and cross-link related pages.

5. BOOKSTORE (`bookstore_*` tools): the library holds (a) the OFFICIAL Odoo
   19 documentation (developer reference backend/frontend/user interface/
   standard modules/upgrades, tutorials, howtos, administration/Odoo.sh/
   on-premise — one book per section, each page a chapter with its source
   URL) and (b) the *Odoo 19 Development Cookbook, 6th Edition* code
   companion — one book per chapter of worked recipes. Use the docs for the
   authoritative API/semantics and the cookbook for complete examples. Follow
   the funnel: `bookstore_catalog_search` → `bookstore_get_toc` →
   `bookstore_search_book` → `bookstore_read_section`. Cite book + section
   title (and the page URL when the docs provide it).

Rules: read before you write; confirm destructive operations (delete, mass
update) with the user first; never open the browser unless explicitly asked;
answer in the user's language with concrete ids/names taken from the tool
results.
"""


def _env(name: str, default: str = "") -> str:
    """Read a setting from the process env, then ``navconfig`` (``env/.env``)."""
    value = os.environ.get(name)
    if value is None:
        try:
            from navconfig import config  # noqa: PLC0415

            value = config.get(name, fallback=None)
        except Exception:  # noqa: BLE001 - navconfig is optional outside the server
            value = None
    return default if value is None else str(value)


@dataclass(frozen=True)
class OdooHelpdeskSettings:
    """Connection settings for the helpdesk instance (never logged)."""

    url: str = DEFAULT_URL
    user: str = ""
    password: str = ""
    api_key: str = ""
    database: str = DEFAULT_DATABASE
    headless: bool = True

    @classmethod
    def from_env(cls) -> "OdooHelpdeskSettings":
        """Build the settings from ``ODOO_HELPDESK_*`` variables."""
        return cls(
            url=_env("ODOO_HELPDESK_URL", DEFAULT_URL).strip() or DEFAULT_URL,
            user=_env("ODOO_HELPDESK_USER"),
            password=_env("ODOO_HELPDESK_PASSWORD"),
            api_key=_env("ODOO_HELPDESK_APIKEY"),
            database=_env("ODOO_HELPDESK_DATABASE", DEFAULT_DATABASE).strip() or DEFAULT_DATABASE,
            headless=_env("ODOO_HELPDESK_HEADLESS", "1") != "0",
        )

    @property
    def base_url(self) -> str:
        """URL without the trailing slash."""
        return self.url.rstrip("/")

    def missing(self) -> list[str]:
        """Names of the required variables that are empty."""
        required = {
            "ODOO_HELPDESK_USER": self.user,
            "ODOO_HELPDESK_PASSWORD": self.password,
            "ODOO_HELPDESK_APIKEY": self.api_key,
        }
        return [name for name, value in required.items() if not value]


def build_odoo_toolkit(settings: OdooHelpdeskSettings) -> OdooToolkit:
    """Create the API toolkit pinned to the Odoo 19 JSON-2 transport.

    The API key travels as the JSON-2 bearer token (``password`` slot) and the
    database goes in the ``X-Odoo-Database`` header, so it is always explicit.
    """
    return OdooToolkit(
        url=settings.base_url,
        database=settings.database,
        username=settings.user,
        password=settings.api_key,
        protocol="json2",
    )


async def resolve_helpdesk_credentials(
    action: Authenticate,
) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """Resolve the web login for ``authenticate`` steps of the helpdesk site.

    Returns ``(user, password)`` for the ``odoo-helpdesk`` provider and
    ``None`` for anything else, which makes the step fail closed.
    """
    if action.credential_provider != CREDENTIAL_PROVIDER:
        return None
    settings = OdooHelpdeskSettings.from_env()
    return settings.user, settings.password


class HelpdeskBrowsingToolkit(WebBrowsingToolkit):
    """WebBrowsingToolkit whose run results also carry the browser's final URL.

    ``SequenceRunResult`` has no URL field, so without this the LLM cannot
    know where a navigation ended and tends to invent an Odoo URL. Every run
    tool below returns the parent's dict plus ``current_url``.
    """

    def _current_url(self) -> Optional[str]:
        driver = self._session_driver
        if driver is None:
            return None
        try:
            url = driver.current_url
            return url() if callable(url) else url
        except Exception:  # noqa: BLE001 - a closed page must not break the tool result
            return None

    def _with_url(self, result: Any) -> Any:
        """Attach ``current_url`` to a run result.

        ``execute_web_task`` answers with a ``{"status", "result"}`` envelope
        that the tool machinery unwraps before the LLM sees it, so the URL
        must live inside ``result`` as well as at the top level.
        """
        if isinstance(result, dict):
            url = self._current_url()
            result["current_url"] = url
            inner = result.get("result")
            if isinstance(inner, dict):
                inner["current_url"] = url
        return result

    # functools.wraps keeps the parent's docstring, annotations and signature
    # (via __wrapped__), which AbstractToolkit turns into the LLM tool schema.
    @functools.wraps(WebBrowsingToolkit.run_site_action)
    async def run_site_action(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._with_url(await super().run_site_action(*args, **kwargs))

    @functools.wraps(WebBrowsingToolkit.run_site_sequence)
    async def run_site_sequence(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._with_url(await super().run_site_sequence(*args, **kwargs))

    @functools.wraps(WebBrowsingToolkit.execute_web_task)
    async def execute_web_task(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._with_url(await super().execute_web_task(*args, **kwargs))


def build_browsing_toolkit(
    settings: OdooHelpdeskSettings,
    catalog_dir: Union[str, Path] = CATALOG_DIR,
    driver_type: str = "playwright",
) -> WebBrowsingToolkit:
    """Create the browsing toolkit with the env-backed credential resolver."""
    return HelpdeskBrowsingToolkit(
        catalog_dir=catalog_dir,
        driver_type=driver_type,
        browser="chrome",
        headless=settings.headless,
        credential_resolver=resolve_helpdesk_credentials,
        confirm_runs=False,  # test agent; keep True for shared deployments
    )


def build_working_memory_toolkit(session_id: Optional[str] = None) -> WorkingMemoryToolkit:
    """Create the scratch store for intermediate results (``wm_*`` tools)."""
    return WorkingMemoryToolkit(session_id=session_id)


def build_wiki_toolkit(storage_dir: Union[str, Path] = WIKI_DIR, wiki_name: str = WIKI_NAME) -> LLMWikiToolkit:
    """Create the agent's knowledge wiki over a local SQLite plane (``wiki_*`` tools).

    Built the same way the framework's dev-flow does it: no PageIndex /
    GraphIndex / OKF sub-toolkits, so ingest of external sources is off but
    pages, notes, edges and combined search all work.
    """
    config = WikiConfig(wiki_name=wiki_name, storage_dir=Path(storage_dir), sync_graph=False)
    return LLMWikiToolkit(None, None, None, config, agent_id="odoo_hd")


def build_bookstore_toolkit(
    library_dir: Union[str, Path] = LIBRARY_DIR,
    llm_spec: Optional[str] = None,
) -> BookstoreToolkit:
    """Create the read-only library toolkit (``bookstore_*`` tools).

    Args:
        library_dir: Library root (``library.db`` + ``trees/``) — the agent's
            private scope; the global ``~/.parrot/library`` is not included.
        llm_spec: ``provider:model`` for hybrid in-book search. Defaults to
            ``PARROT_BOOKSTORE_LLM`` or :data:`DEFAULT_BOOKSTORE_LLM`; when
            the provider cannot be built the toolkit degrades to BM25 only.
    """
    from parrot.knowledge.bookstore._llm import resolve_adapter  # noqa: PLC0415

    spec = llm_spec or _env("PARROT_BOOKSTORE_LLM", DEFAULT_BOOKSTORE_LLM)
    adapter, light = None, None
    try:
        adapter, light, _client = resolve_adapter(spec)
    except Exception:  # noqa: BLE001 - degrade to lexical search
        logger.warning("Bookstore LLM %r unavailable; using BM25-only search", spec, exc_info=True)
    locations = [LibraryLocation(scope="project", root=Path(library_dir))]
    return BookstoreToolkit(Bookstore(locations, adapter=adapter, lightweight_model=light))


async def seed_catalog(toolkit: WebBrowsingToolkit, base_url: str = DEFAULT_URL) -> str:
    """Write the helpdesk site and its deterministic actions to the catalog.

    Args:
        toolkit: Browsing toolkit whose catalog receives the actions.
        base_url: Root URL of the Odoo instance.

    Returns:
        The registered site slug.
    """
    base = base_url.rstrip("/")
    await toolkit.register_site(
        base,
        name=SITE_NAME,
        title="Odoo Helpdesk (staging)",
        description="TROC helpdesk on Odoo 19 — Softhealer All-in-One Helpdesk.",
        aliases=["odoo", "helpdesk", "odoo helpdesk", "pokemon.helpdesk.staging.trocdigital.io"],
    )
    await toolkit.save_site_action(
        SITE_NAME,
        "login",
        "Log in to the Odoo web client with the helpdesk web user.",
        steps=[
            {"action": "navigate", "url": f"{base}/web/login"},
            {
                "action": "authenticate",
                "method": "form",
                "credential_provider": CREDENTIAL_PROVIDER,
                "username_selector": "#login",
                "password_selector": "#password",
                "submit_selector": 'button[type="submit"]',
            },
            {"action": "wait", "condition": "/odoo", "condition_type": "url_contains", "timeout": 30},
        ],
        kind="operation",
        title="Iniciar sesión",
        overwrite=True,
    )
    navigation = {
        "home": ("Inicio", "Open the Odoo home (apps) screen.", f"{base}/odoo", ".o_action_manager"),
        "tickets": (
            "Tickets",
            "Open the Helpdesk Tickets view (kanban/list of sh.helpdesk.ticket).",
            f"{base}/odoo/action-{TICKETS_ACTION}",
            ".o_action_manager",
        ),
        "sla-analysis": (
            "Análisis SLA",
            "Open the Helpdesk SLA Analysis report.",
            f"{base}/odoo/action-{SLA_ACTION}",
            ".o_action_manager",
        ),
    }
    for name, (title, description, url, selector) in navigation.items():
        await toolkit.save_site_action(
            SITE_NAME,
            name,
            description,
            steps=[
                {"action": "navigate", "url": url},
                {"action": "wait", "condition": selector, "condition_type": "selector", "timeout": 30},
            ],
            kind="navigation",
            requires=["login"],
            title=title,
            overwrite=True,
        )
    await toolkit.save_site_action(
        SITE_NAME,
        "ticket",
        "Open one helpdesk ticket in its form view by database id.",
        steps=[
            {"action": "navigate", "url": f"{base}/odoo/action-{TICKETS_ACTION}/{{{{ticket_id}}}}"},
            {"action": "wait", "condition": ".o_form_view", "condition_type": "selector", "timeout": 30},
        ],
        kind="navigation",
        params={"ticket_id": {"description": "Database id of the sh.helpdesk.ticket", "required": True}},
        requires=["login"],
        title="Abrir ticket",
        overwrite=True,
    )
    return SITE_NAME


@register_agent(name="odoo_hd")
class OdooHelpdesk(Agent):
    """Test agent for the TROC helpdesk on Odoo 19 (API key + web session).

    Args:
        headless: Run the browser headless (``None`` reads
            ``ODOO_HELPDESK_HEADLESS``).
        catalog_dir: Action-catalog root; seeded on ``configure()`` when the
            site folder is missing.
        settings: Explicit settings (defaults to the ``ODOO_HELPDESK_*`` env).
        **kwargs: Forwarded to :class:`~parrot.bots.agent.Agent`
            (``llm``, ``use_llm``, ...).
    """

    agent_id: str = "odoo_hd"
    model = "gemini-3.1-flash-lite"

    def __init__(
        self,
        headless: Optional[bool] = None,
        catalog_dir: Union[str, Path] = CATALOG_DIR,
        settings: Optional[OdooHelpdeskSettings] = None,
        **kwargs: Any,
    ) -> None:
        base = settings or OdooHelpdeskSettings.from_env()
        if headless is not None:
            base = OdooHelpdeskSettings(
                url=base.url,
                user=base.user,
                password=base.password,
                api_key=base.api_key,
                database=base.database,
                headless=headless,
            )
        self.settings = base
        self.catalog_dir = Path(catalog_dir)
        self.odoo_toolkit = build_odoo_toolkit(self.settings)
        self.browsing_toolkit = build_browsing_toolkit(self.settings, catalog_dir=self.catalog_dir)
        self.working_memory = build_working_memory_toolkit()
        self.wiki_toolkit = build_wiki_toolkit()
        self.bookstore_toolkit = build_bookstore_toolkit()
        kwargs.setdefault("name", "OdooHelpdesk")
        super().__init__(
            tools=[
                self.odoo_toolkit,
                self.browsing_toolkit,
                self.working_memory,
                self.wiki_toolkit,
                self.bookstore_toolkit,
            ],
            system_prompt=SYSTEM_PROMPT,
            **kwargs,
        )

    async def configure(self, app=None) -> None:
        """Configure the agent, seed the browsing catalog and the wiki if missing."""
        await super().configure(app)
        if not (self.catalog_dir / SITE_NAME).exists():
            await seed_catalog(self.browsing_toolkit, self.settings.url)
        if not (WIKI_DIR / "index.md").exists():
            await self.seed_wiki()

    async def seed_wiki(self) -> dict[str, Any]:
        """Create the knowledge wiki and file the instance profile into it.

        Best-effort: the stage list is fetched live from Odoo and skipped when
        the API is unreachable, so configure() never fails because of it.

        Returns:
            Dict with the created wiki info and the ids of the seeded pages.
        """
        created = await self.wiki_toolkit.create_wiki(WIKI_NAME, description="TROC Helpdesk (Odoo 19) knowledge")
        pages: list[str] = []
        profile = (
            f"Instance {self.settings.base_url}, database {self.settings.database}, Odoo 19 (JSON-2 API). "
            f"Helpdesk app: Softhealer sh_all_in_one_helpdesk. Ticket model: {TICKET_MODEL} "
            "(fields: name, stage_id, team_id, user_id, partner_id, priority_new, category_id, create_date). "
            "Related models: helpdesk.stages, sh.helpdesk.team, helpdesk.category, helpdesk.tags, "
            "sh.helpdesk.ticket.type, sh.helpdesk.sla. Web tickets action: "
            f"/odoo/action-{TICKETS_ACTION}."
        )
        note = await self.wiki_toolkit.remember(WIKI_NAME, profile, title="Instance profile", category="concept")
        pages.append(note.get("page_id", ""))
        try:
            stages = await self.odoo_toolkit.search_records(
                "helpdesk.stages", domain=[], fields=["id", "name", "sequence"], limit=50, order="sequence"
            )
            listing = ", ".join(f"{r['name']} (id {r['id']})" for r in stages.records)
            note = await self.wiki_toolkit.remember(
                WIKI_NAME,
                f"Ticket stages (helpdesk.stages) in sequence order: {listing}.",
                title="Ticket stages",
                category="concept",
                related_pages=[p for p in pages if p],
            )
            pages.append(note.get("page_id", ""))
        except Exception:  # noqa: BLE001 - offline configure must still succeed
            self.logger.warning("Could not fetch helpdesk stages for the wiki seed", exc_info=True)
        return {"wiki": created, "pages": [p for p in pages if p]}

    async def close(self) -> None:
        """Release the browser session and the Odoo HTTP session."""
        await self.browsing_toolkit.close_browser()
        await self.odoo_toolkit.stop()

    async def verify_connection(self, web: bool = True) -> dict[str, Any]:
        """Check both credentials against the live instance without an LLM.

        Args:
            web: Also replay the catalogued ``tickets`` action (login +
                navigation) in the browser.

        Returns:
            A JSON-serialisable report with the server version, the API-key
            identity and its admin groups, a ticket sample, and the
            browser run outcome. Secrets are never included.
        """
        report: dict[str, Any] = {"url": self.settings.base_url, "missing_env": self.settings.missing()}
        odoo = self.odoo_toolkit
        info = await odoo.server_info()
        report["server"] = info.model_dump(mode="json")
        report["json2_ok"] = info.connected and info.transport == "json2" and info.server_serie.startswith("19")
        profile = await odoo.get_odoo_profile(include_modules=False)
        uid = profile.uid or profile.user_context.get("uid")
        report["api_user"] = {"uid": uid, "context": profile.user_context}
        if uid:
            rows = await odoo.search_records("res.users", domain=[["id", "=", uid]], fields=["name", "login", "share"])
            report["api_user"]["record"] = rows.records[0] if rows.records else None
            groups: dict[str, bool] = {}
            for group in ADMIN_GROUPS:
                groups[group] = bool(await odoo._execute("res.users", "has_group", [[uid]], {"group_ext_id": group}))
            report["api_user"]["admin_groups"] = groups
            report["api_admin"] = all(groups.values())
        tickets = await odoo.search_records(
            TICKET_MODEL,
            domain=[],
            fields=["id", "name", "stage_id", "team_id", "user_id"],
            limit=3,
            order="id desc",
        )
        report["tickets"] = {"total": tickets.total, "sample": tickets.records}
        report["toolkits"] = {
            type(tk).__name__: len(tk.get_tools())
            for tk in (
                self.odoo_toolkit,
                self.browsing_toolkit,
                self.working_memory,
                self.wiki_toolkit,
                self.bookstore_toolkit,
            )
        }
        books = await self.bookstore_toolkit.list_books()
        report["bookstore"] = {"books": len(books), "titles": [b.get("title") for b in books][:25]}
        if not (WIKI_DIR / "index.md").exists():
            await self.seed_wiki()
        wiki_pages = await self.wiki_toolkit.browse_pages(WIKI_NAME)
        report["wiki"] = {"name": WIKI_NAME, "pages": len(wiki_pages) if isinstance(wiki_pages, list) else wiki_pages}
        if web:
            if not (self.catalog_dir / SITE_NAME).exists():
                await seed_catalog(self.browsing_toolkit, self.settings.url)
            try:
                run = await self.browsing_toolkit.run_site_action(SITE_NAME, "tickets")
                report["web"] = {
                    "success": run.get("success"),
                    "executed": [
                        {k: item.get(k) for k in ("action", "success", "injected", "elapsed_ms", "error")}
                        for item in run.get("executed", [])
                    ],
                }
            finally:
                await self.browsing_toolkit.close_browser()
        return report


async def _run_check(web: bool) -> int:
    """Run :meth:`OdooHelpdesk.verify_connection` and print the report."""
    agent = OdooHelpdesk()
    try:
        report = await agent.verify_connection(web=web)
    finally:
        await agent.close()
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    ok = bool(report.get("json2_ok")) and bool(report.get("api_admin"))
    if web:
        ok = ok and bool(report.get("web", {}).get("success"))
    print("CHECK", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


async def main() -> int:
    """CLI entry point: ``--check [--no-web]`` or a natural-language question."""
    args = list(sys.argv[1:])
    if "--check" in args:
        return await _run_check(web="--no-web" not in args)
    question = " ".join(args) or "¿Cuántos tickets hay en el helpdesk y cuáles son los tres más recientes?"
    agent = OdooHelpdesk()
    await agent.configure()
    try:
        answer = await agent.ask(question)
        print(answer.response)
    finally:
        await agent.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
