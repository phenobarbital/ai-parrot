"""OdooAgent ("Oddie") — self-documenting Odoo operations agent (FEAT-240).

Oddie is a registered :class:`~parrot.bots.Agent` that grounds every answer in
the official Odoo 16 / 18 / 19 documentation PageIndex, records learnings and
new operation patterns as skills, and gates all write / shell operations behind
HITL confirmation.

Capabilities:
    - **OdooToolkit** (RPC + ``odoo-bin``/``odoo-cli`` shell functions) — action
      layer against the live test instance (``ODOO_TEST_*`` env vars).
    - **PageIndexToolkit** — grounded retrieval over the bundled Odoo docs, plus
      a write-back path so out-of-doc learnings are preserved.
    - **Skill Registry** (``SkillRegistryMixin``) — file-based skills under
      ``agents/odoo_agent/skills/``; the agent documents new operations as skills.
    - **WorkingMemoryToolkit** — intermediate result store for staged / presentable
      data.
    - **HITL ConfirmationGuard** — gates write/delete RPC tools and all shell
      tools behind human confirmation.
    - **UserInfo KB** (always-active) — auto-injects user context into the system
      prompt.

Configuration:
    Reads ``ODOO_TEST_URL``, ``ODOO_TEST_DATABASE``, ``ODOO_TEST_USERNAME``,
    ``ODOO_TEST_PASSWORD`` from the environment (never uses the staging
    ``ODOO_*`` variables).

Registration:
    Registered as ``odoo_agent`` via ``@register_agent(name="odoo_agent",
    at_startup=True)``.  Only load this file when the backup
    ``agents/backup/odoo.py`` is NOT on the agent load path — both register the
    same slug and would collide.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from parrot.auth.confirmation import (
    ConfirmationConfig,
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
)
from parrot.bots import Agent
from parrot.clients.google import GoogleGenAIClient
from parrot.knowledge.pageindex import PageIndexLLMAdapter, PageIndexToolkit
from parrot.models.google import GoogleModel
from parrot.registry import register_agent
from parrot.skills import SkillRegistryMixin
from parrot.stores.kb.user import UserInfo
from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot_tools.odoo import OdooToolkit

logger = logging.getLogger(__name__)

# ── PageIndex configuration ───────────────────────────────────────────────────

# Absolute path to the persisted per-version PageIndex trees.
# Overridable via ODOO_PAGEINDEX_DIR env var; defaults to
# agents/odoo_agent/documentation/ relative to this file.
# Must match the ``storage_dir`` used by ``scripts/odoo_agent/build_odoo_pageindex.py``.
_SCRIPT_DIR = Path(__file__).resolve().parent
PAGEINDEX_STORAGE_DIR: str = os.environ.get(
    "ODOO_PAGEINDEX_DIR",
    str(_SCRIPT_DIR / "odoo_agent" / "documentation"),
)

# Lightweight LLM model used for PageIndex summary generation.
_PAGEINDEX_LIGHT_MODEL = "gemini-2.0-flash-lite"

# ── Skills configuration ──────────────────────────────────────────────────────

_SKILLS_DIR = _SCRIPT_DIR / "odoo_agent" / "skills"

# ── Backstory ─────────────────────────────────────────────────────────────────

BACKSTORY = """\
You are Oddie, an AI assistant specialising in Odoo ERP operations.

## Your knowledge base

You have access to the official documentation for **Odoo 16**, **18**, and **19**
through the PageIndex (trees: ``odoo_16``, ``odoo_18``, ``odoo_19``).  Every
answer you give about Odoo operations MUST be grounded in a PageIndex retrieval
first.  Do not rely on parametric memory for version-specific details — always
search the documentation.

**Key version differences to call out:**
- **Odoo 16** uses XML-RPC (``/xmlrpc/2/``).
- **Odoo 18** uses JSON-RPC and REST.
- **Odoo 19** adds the JSON-2 envelope protocol on top of 18.

## Write-back learnings

Whenever you discover information that is NOT in the documentation — a gap,
a workaround, a version-specific gotcha — splice it into the relevant
PageIndex tree using:
- ``pageindex_insert_content`` — for plain text/JSON notes.
- ``pageindex_insert_markdown`` — for structured markdown notes.

Use the tree that matches the Odoo version the learning applies to
(``odoo_16``, ``odoo_18``, or ``odoo_19``).

## Skill documentation

Whenever you learn how to perform an Odoo operation that could be reused, call
``document_skill`` (or ``save_learned_skill``) to record it as a skill.  Good
candidates are: workflows that required multiple steps, error patterns with
known fixes, and version-specific procedures.

## Working memory

Use the ``wm_store`` and ``wm_store_result`` tools to stage intermediate
results and data tables for presentation to the user.  When you have gathered
data and want to present it cleanly, store it in working memory first, then
retrieve and format it for the user.

## Live Odoo interaction

You can interact with the live Odoo test instance (Odoo 18 at ``ODOO_TEST_*``)
via the Odoo RPC tools (``odoo_search_records``, ``odoo_get_record``,
``odoo_create_record``, etc.).

Shell tools (``odoo_shell_install_module``, ``odoo_shell_upgrade_module``,
``odoo_cli_command``) are also available when the ``ODOO_BIN`` binary is
reachable.

**HITL gate:** All write and delete RPC tools AND all shell tools require
explicit human confirmation before they execute.  Before proposing a write
or shell operation, state clearly:
1. What you intend to do.
2. Which tool / command will be called.
3. What the effect will be.

Wait for the user's approval.  Never execute a write or shell tool without
presenting the details first.

## Response format for how-to questions

When answering "how do I do X in Odoo" questions, follow the
``/structured-operation-response`` skill: respond with a **numbered list of
concrete steps**, grounding each step in the PageIndex, and calling out
version differences where relevant.

## Grounding citation

When you retrieve documentation to answer a question, briefly cite the source
(e.g. "According to the Odoo 18 documentation (PageIndex)…") so the user knows
your answer is grounded, not generated from parametric memory.
"""


# ── Agent ─────────────────────────────────────────────────────────────────────


@register_agent(name="odoo_agent", at_startup=True)
class OdooAgent(SkillRegistryMixin, Agent):
    """Self-documenting Odoo ERP operations agent (FEAT-240).

    Grounds answers in the official Odoo documentation PageIndex,
    records learnings as skills, and gates all writes behind HITL.

    Attributes:
        agent_id: Registry slug — ``"odoo_agent"``.
        model: Gemini 3.5 Flash (via :class:`~parrot.models.google.GoogleModel`).
        enable_skill_registry: Enables the SkillRegistryMixin capability.
        skill_registry_expose_tools: Exposes skill tools to the LLM.
        skill_registry_inject_context: Injects available-skills context.
    """

    agent_id: str = "odoo_agent"
    model = GoogleModel.GEMINI_3_5_FLASH

    # SkillRegistryMixin configuration
    enable_skill_registry: bool = True
    skill_registry_expose_tools: bool = True
    skill_registry_inject_context: bool = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialise OdooAgent.

        Args:
            *args: Forwarded to :class:`~parrot.bots.Agent`.
            **kwargs: Forwarded to :class:`~parrot.bots.Agent`; ``backstory``
                is injected here.
        """
        super().__init__(*args, backstory=BACKSTORY, **kwargs)
        self._odoo_toolkit: OdooToolkit | None = None
        self._pageindex_toolkit: PageIndexToolkit | None = None
        self.logger = logging.getLogger(__name__)

    def agent_tools(self) -> list[Any]:
        """Return the tools exposed to the LLM.

        Builds :class:`~parrot_tools.odoo.OdooToolkit` from ``ODOO_TEST_*``
        env vars (read fresh on every call — never cached at module scope)
        and :class:`~parrot.knowledge.pageindex.PageIndexToolkit` backed by
        the persisted version trees.

        Returns:
            Combined list of OdooToolkit and PageIndexToolkit tools.
        """
        # Read credentials fresh from the environment every time — avoids
        # stale values when the process is long-lived or env vars change.
        self._odoo_toolkit = OdooToolkit(
            url=os.environ.get("ODOO_TEST_URL", ""),
            database=os.environ.get("ODOO_TEST_DATABASE", ""),
            username=os.environ.get("ODOO_TEST_USERNAME", ""),
            password=os.environ.get("ODOO_TEST_PASSWORD", ""),
            verify_ssl=False,
        )

        # PageIndexToolkit (grounded retrieval over Odoo 16/18/19 docs)
        try:
            google_client = GoogleGenAIClient(model=_PAGEINDEX_LIGHT_MODEL)
            adapter = PageIndexLLMAdapter(
                client=google_client,
                model=_PAGEINDEX_LIGHT_MODEL,
            )
            self._pageindex_toolkit = PageIndexToolkit(
                adapter=adapter,
                storage_dir=PAGEINDEX_STORAGE_DIR,
            )
            pageindex_tools = self._pageindex_toolkit.get_tools()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "PageIndexToolkit could not be initialised (%s). "
                "PageIndex tools will not be available.  "
                "Run scripts/odoo_agent/build_odoo_pageindex.py to build the index.",
                exc,
            )
            pageindex_tools = []

        return self._odoo_toolkit.get_tools() + pageindex_tools

    async def configure(self, app: Any = None, queries: Any = None) -> None:
        """Configure capabilities: WorkingMemory, HITL guard, UserInfo KB, skills.

        Wires all non-tool capabilities in the correct order:
        1. ``WorkingMemoryToolkit`` — registered before super() so it is
           available during the rest of configure().
        2. ``ConfirmationGuard`` — attached to the ToolManager so write/delete
           RPC tools and shell tools are HITL-gated.
        3. ``UserInfo`` KB — always-active; auto-injected into the system prompt.
        4. ``super().configure()`` — standard Agent setup.
        5. ``_configure_skill_registry()`` — loads file-based skills from
           ``agents/odoo_agent/skills/`` (SkillRegistryMixin).

        Args:
            app: Optional aiohttp application instance.
            queries: Optional query context forwarded to super().
        """
        # 1. Working memory toolkit
        wm_toolkit = WorkingMemoryToolkit()
        self.tool_manager.register_toolkit(wm_toolkit)

        # 2. HITL ConfirmationGuard (OQ2 resolved: built here in configure())
        #
        # DEPLOYMENT NOTE: ``human_manager=None`` means the guard is
        # fail-closed — any HITL-gated shell tool call (odoo_shell_install_module,
        # odoo_shell_upgrade_module, odoo_cli_command) will be denied with
        # status="cancelled" until a HumanInteractionManager is injected by
        # the serving layer (e.g. Telegram / Slack integration).
        # This is safe by design: better to block than to execute without approval.
        store = InMemoryConfirmationWindowStore()
        config = ConfirmationConfig(
            approval_timeout=120.0,
            default_channel="telegram",
            max_edit_retries=1,
        )
        guard = ConfirmationGuard(
            store=store,
            human_manager=None,  # Injected by the serving layer at runtime
            config=config,
        )
        self.tool_manager.set_confirmation_guard(guard)
        self.logger.warning(
            "ConfirmationGuard attached with human_manager=None (fail-closed). "
            "Shell and write tools will be DENIED until a HumanInteractionManager "
            "is provided by the serving layer (Telegram/Slack)."
        )

        # 3. UserInfo KB (always-active — auto-injected into system prompt)
        self.register_kb(UserInfo())
        self.logger.debug("UserInfo KB registered (always_active=True)")

        # 4. Standard Agent configure (registers tools, memory, etc.)
        await super().configure(app=app)

        # 5. Skill Registry (loads agents/odoo_agent/skills/)
        if _SKILLS_DIR.is_dir():
            self.skill_paths = [_SKILLS_DIR]
        await self._configure_skill_registry()
        self.logger.info("OdooAgent configured — PageIndex + skills + HITL ready")

    async def cleanup(self) -> None:
        """Release resources: OdooToolkit transport + PageIndex + super().

        Args:
            (none)
        """
        if self._odoo_toolkit is not None:
            await self._odoo_toolkit.cleanup()
            self._odoo_toolkit = None
        # PageIndexToolkit has no async cleanup; its storage is file-based
        await super().cleanup()
