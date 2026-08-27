"""AgentStudio meta-agent tools (FEAT-467 TASK-2521).

Every MUTATING tool is HITL-gated (``requires_confirmation=True`` — FEAT-235
``ConfirmationGuard``) and constrained by construction to write ONLY:

- ``AGENTS_DIR/_drafts/`` (via ``save_agent_draft``) — the TASK-2513 draft
  pipeline; a draft only ever becomes live code through its own explicit
  ``POST .../activate`` endpoint, never from this agent directly.
- ``AGENTS_DIR/<agent>/{identity,kb,skills}/`` (via ``write_identity_file``/
  ``write_kb_file``/``write_skill_file``) — the TASK-2514 sandboxed asset
  directories.
- The registry's own YAML factory path (via ``create_yaml_agent``, reusing
  ``parrot.bots.factory.tools.finalize.finalize_agent_registration`` —
  the SAME function ``AgentFactoryOrchestrator`` calls).
- The shared skills catalog (via ``publish_skill_to_catalog`` — TASK-2515).

No tool accepts a raw filesystem path; every write target is built
internally from a caller-supplied ``agent_name``/``filename`` and validated
through the same sandboxing (``resolve_safe_path``) and per-kind filename
rules the Studio HTTP handlers use. There is NO tool capable of writing a
``.py`` module directly into ``AGENTS_DIR`` itself.

Package-layering note: this module lives in the CORE ``ai-parrot``
distribution, but several validation/persistence helpers it reuses (to
avoid duplicating logic — see each tool's docstring) live in the
``ai-parrot-server`` satellite (``parrot.handlers.studio.*``). Those are
imported LAZILY, function-body-local, mirroring the existing
``parrot.knowledge.graphindex.factory`` precedent of a core module
lazily importing from a satellite distribution only when the specific
feature is actually invoked (AgentStudio is a server-side-only surface;
core never imports ``ai-parrot-server`` at module-import time).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parrot.conf import AGENTS_DIR
from parrot.tools import tool
from parrot.utils.helpers import current_context


def _require_app() -> Any:
    """Return the aiohttp Application bound to the current tool call.

    Raises:
        RuntimeError: No ``RequestContext`` is bound (tool called outside
            an ``agent.session(request=..., app=...)`` block — AgentStudio
            tools require app context to reach the database/registry).
    """
    ctx = current_context()
    if ctx is None or ctx.app is None:
        raise RuntimeError(
            "AgentStudio tools require an active request context "
            "(agent.session(request=..., app=...)); none is bound."
        )
    return ctx.app


# ---------------------------------------------------------------------------
# Draft pipeline (TASK-2513)
# ---------------------------------------------------------------------------


@tool(
    name="save_agent_draft",
    requires_confirmation=True,
    confirm_template="Save agent draft {name}.py under AGENTS_DIR/_drafts/? "
    "It will NOT be live until explicitly activated.",
    description=(
        "Save generated Python agent source as a draft under "
        "AGENTS_DIR/_drafts/<name>.py and statically validate it (AST "
        "allowlist — no import/exec). NEVER writes live code; the draft "
        "only becomes a real agent via the separate, explicit "
        "POST /astudio/drafts/{name}/activate endpoint."
    ),
)
async def save_agent_draft(name: str, source: str) -> dict:
    """Save+validate a generated agent draft (TASK-2513 draft pipeline).

    Args:
        name: Draft slug (``^[a-z0-9_-]+$``) — becomes ``<name>.py``.
        source: Full Python source of the candidate agent module.

    Returns:
        ``{name, status, file_path, validation_report}``.
    """
    from parrot.handlers.studio._base import is_valid_slug, resolve_safe_path
    from parrot.handlers.studio.validation import detect_base_class, validate_draft

    if not is_valid_slug(name):
        raise ValueError(f"Invalid draft name '{name}'; must match ^[a-z0-9_-]+$.")

    drafts_dir = Path(AGENTS_DIR) / "_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    file_path = resolve_safe_path(drafts_dir, f"{name}.py")
    file_path.write_text(source)

    report = validate_draft(source)
    base_class = detect_base_class(source) if report.passed else None
    status = "validated" if report.passed else "failed"

    app = _require_app()
    db = app.get("database")
    if db is not None:
        import logging as _logging
        from datetime import datetime

        from asyncdb.exceptions import NoDataFound

        from parrot.handlers.models.studio_drafts import StudioDraft

        try:
            async with await db.acquire() as conn:
                StudioDraft.Meta.connection = conn
                try:
                    existing = await StudioDraft.get(name=name)
                except NoDataFound:
                    existing = None
                fields = {
                    "name": name,
                    "file_path": str(file_path),
                    "status": status,
                    "validation_report": report.model_dump(),
                    "base_class": base_class,
                }
                if existing is not None:
                    for key, value in fields.items():
                        existing.set(key, value)
                    existing.set("updated_at", datetime.now())
                    await existing.update()
                else:
                    row = StudioDraft(**fields, owner_user_id="agent_studio")
                    await row.insert()
        except Exception as exc:  # pylint: disable=broad-except
            # Best-effort — the draft FILE (already written above) is the
            # source of truth; a DB row failure never blocks the save.
            _logging.getLogger("Parrot.AgentStudio.Tools").warning(
                "save_agent_draft: failed to persist draft row for '%s': %s",
                name,
                exc,
            )

    return {
        "name": name,
        "status": status,
        "file_path": str(file_path),
        "validation_report": report.model_dump(),
    }


# ---------------------------------------------------------------------------
# YAML-agent factory flow (absorbs AgentFactory — spec §3 Module 13)
# ---------------------------------------------------------------------------


@tool(
    name="create_yaml_agent",
    requires_confirmation=True,
    confirm_template="Register agent {name!s} (class {bot_class!s}) via a " "persisted YAML definition?",
    description=(
        "Create a simple (non-code-generated) agent by writing a lossless "
        "YAML definition under AGENTS_DIR/agents/<category>/ and "
        "registering it into the live AgentRegistry. Reuses the SAME "
        "finalize_agent_registration() the AgentFactory flow uses — never "
        "writes a live .py module."
    ),
)
async def create_yaml_agent(
    name: str,
    bot_class: str = "BasicBot",
    llm: str | None = None,
    description: str | None = None,
    category: str = "general",
) -> dict:
    """Create + register a YAML-defined agent (absorbs AgentFactory's
    finalize step — TASK-2521).

    Args:
        name: Agent slug.
        bot_class: Base class name (e.g. ``"BasicBot"``, ``"Agent"``).
        llm: Optional ``"provider:model"`` string.
        description: Optional human-readable description.
        category: YAML category sub-directory.

    Returns:
        The ``finalize_agent_registration`` result dict
        (``yaml_path``, ``registered``, ``agent_name``, ...).
    """
    # AgentDefinition IS BotConfig (a deliberate alias — see
    # bots/factory/contracts.py); resolving bot_class through the live
    # BotManager mirrors the EXACT construction TASK-2512's
    # `POST /astudio/agents` create flow uses, so YAML-agent creation
    # behaves identically whether it comes from the REST endpoint or
    # this tool.
    from parrot.bots.factory.tools.finalize import finalize_agent_registration
    from parrot.clients.factory import LLMFactory
    from parrot.models.basic import ModelConfig
    from parrot.registry.registry import BotConfig

    app = _require_app()
    manager = app.get("bot_manager")
    if manager is None:
        raise RuntimeError("BotManager unavailable — cannot resolve bot_class.")
    resolved_class = manager.get_bot_class(bot_class)
    if resolved_class is None:
        raise ValueError(f"Unknown bot_class '{bot_class}'.")

    config_dict = {"description": description} if description else {}
    model_config = None
    if llm:
        provider, model = LLMFactory.parse_llm_string(llm)
        model_config = ModelConfig(provider=provider, model=model or "")

    definition = BotConfig(
        name=name,
        class_name=resolved_class.__name__,
        module=resolved_class.__module__,
        origin="factory",
        config=config_dict,
        model=model_config,
    )
    return await finalize_agent_registration(definition, category=category)


# ---------------------------------------------------------------------------
# Per-agent asset files (TASK-2514)
# ---------------------------------------------------------------------------


async def _write_asset_file(agent_name: str, kind: str, filename: str, content: str) -> dict:
    """Shared implementation for the three ``write_*_file`` tools.

    Reuses the SAME per-kind filename validators and sandboxed path
    resolution the Studio ``PUT .../files/{kind}/{filename}`` endpoint
    uses (``handlers/studio/files.py`` — imported lazily, see module
    docstring). Never writes outside ``AGENTS_DIR/<agent_name>/<kind>/``.
    """
    from parrot.handlers.studio._base import is_valid_slug, resolve_safe_path
    from parrot.handlers.studio.files import (
        VALID_KINDS,
        _is_skill_definition_file,
        _StudioFilesMixin,
    )

    if not is_valid_slug(agent_name):
        raise ValueError(f"Invalid agent name '{agent_name}'.")
    if kind not in VALID_KINDS:
        raise ValueError(f"Unknown kind '{kind}'; must be one of {VALID_KINDS}.")

    base_dir = Path(AGENTS_DIR) / agent_name / kind
    target = resolve_safe_path(base_dir, filename)

    # _validate_kind_filename / _validate_skill_content are @staticmethod
    # on _StudioFilesMixin — callable directly on the class, no instance
    # needed (same functions the PUT .../files/{kind}/{filename} handler
    # calls on itself).
    kind_error = _StudioFilesMixin._validate_kind_filename(kind, filename)
    if kind_error:
        raise ValueError(kind_error)

    if kind == "skills" and _is_skill_definition_file(filename):
        content_error = _StudioFilesMixin._validate_skill_content(content)
        if content_error:
            raise ValueError(content_error)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)

    return {
        "agent_name": agent_name,
        "kind": kind,
        "path": filename,
        "size": target.stat().st_size,
        "reload_required": True,
    }


@tool(
    name="write_identity_file",
    requires_confirmation=True,
    confirm_template="Write identity file {filename} for agent {agent_name}?",
    description=(
        "Write one of the five canonical identity files "
        "(AGENTS_DIR/<agent_name>/identity/<filename>) for an existing "
        "agent. Requires a reload to take effect."
    ),
)
async def write_identity_file(agent_name: str, filename: str, content: str) -> dict:
    """Write a canonical identity file for ``agent_name`` (TASK-2514)."""
    return await _write_asset_file(agent_name, "identity", filename, content)


@tool(
    name="write_kb_file",
    requires_confirmation=True,
    confirm_template="Write knowledge-base file {filename} for agent {agent_name}?",
    description=(
        "Write a flat .md/.txt knowledge-base file under "
        "AGENTS_DIR/<agent_name>/kb/<filename> for an existing agent. "
        "Requires a reload to take effect."
    ),
)
async def write_kb_file(agent_name: str, filename: str, content: str) -> dict:
    """Write a KB file for ``agent_name`` (TASK-2514)."""
    return await _write_asset_file(agent_name, "kb", filename, content)


@tool(
    name="write_skill_file",
    requires_confirmation=True,
    confirm_template="Write skill file {filename} for agent {agent_name}?",
    description=(
        "Write a per-agent skill file (single-file <name>.md, or composite "
        "<name>/SKILL.md + assets) under AGENTS_DIR/<agent_name>/skills/. "
        "Skill-definition files are validated (frontmatter contract) before "
        "writing. Requires a reload to take effect."
    ),
)
async def write_skill_file(agent_name: str, filename: str, content: str) -> dict:
    """Write a per-agent skill file for ``agent_name`` (TASK-2514)."""
    return await _write_asset_file(agent_name, "skills", filename, content)


# ---------------------------------------------------------------------------
# Shared skills catalog (TASK-2515)
# ---------------------------------------------------------------------------


@tool(
    name="publish_skill_to_catalog",
    requires_confirmation=True,
    confirm_template="Publish skill '{name}' to the shared org-wide catalog?",
    description=(
        "Publish a new skill to the shared, org-wide skills catalog "
        "(Postgres-first, best-effort registry dual-write). Fails with a "
        "clear error if a skill with this name already exists."
    ),
)
async def publish_skill_to_catalog(
    name: str,
    description: str,
    category: str,
    triggers: list[str],
    body: str,
) -> dict:
    """Publish a new shared skill (TASK-2515 catalog).

    Args:
        name: Unique skill name within the shared catalog.
        description: Human-readable description.
        category: One of ``parrot.skills.models.SkillCategory``'s values
            (out-of-vocabulary values map to ``"general"``).
        triggers: Trigger phrases/commands.
        body: Skill markdown body (including frontmatter).

    Returns:
        The published catalog entry, serialized.
    """
    import logging as _logging

    from parrot.handlers.models.skills_catalog import SkillCatalogEntry
    from parrot.handlers.studio.skills_catalog import StudioSkillsCatalogHandler
    from parrot.skills.models import SkillCategory

    app = _require_app()
    if app.get("database") is None:
        raise RuntimeError("Database unavailable — cannot publish to the shared catalog.")

    try:
        resolved_category = SkillCategory(category)
    except ValueError:
        resolved_category = SkillCategory.GENERAL

    # A bare, request-less instance of the handler's DB glue — its
    # methods only need `.request.app` / `.logger`, never the full
    # aiohttp request/response cycle (mirrors the `tool.execute()`
    # `_pre_execute` seam, not a real HTTP dispatch — no duplicate
    # persistence logic; this calls the SAME `_insert_entry`/
    # `_dual_write_to_registry`/`_flag_stale` the POST /astudio/skills
    # handler uses).
    helper = object.__new__(StudioSkillsCatalogHandler)
    helper.request = type("_FakeRequest", (), {"app": app})()
    helper.logger = _logging.getLogger("Parrot.AgentStudio.PublishSkill")

    existing = await helper._get_entry_by_name(name)  # pylint: disable=protected-access
    if existing is not None:
        raise ValueError(f"Skill '{name}' already exists in the shared catalog.")

    entry = SkillCatalogEntry(
        name=name,
        description=description,
        category=resolved_category.value,
        owner="agent_studio",
        triggers=list(triggers),
        body=body,
        version=1,
        status="active",
        search_index_stale=False,
    )
    await helper._insert_entry(entry)  # pylint: disable=protected-access

    stale = await helper._dual_write_to_registry(entry, "agent_studio")  # pylint: disable=protected-access
    if stale:
        await helper._flag_stale(entry)  # pylint: disable=protected-access

    return helper._entry_to_dict(entry)  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# Read-only introspection (no confirmation)
# ---------------------------------------------------------------------------


@tool(
    name="list_agent_base_classes",
    description="List available agent base classes (name, module, " "docstring, configurable constructor params).",
)
async def list_agent_base_classes() -> list:
    """List agent base classes via the Studio catalog (TASK-2519)."""
    from parrot.handlers.studio.catalog import _build_base_classes_catalog

    return _build_base_classes_catalog()


@tool(
    name="list_available_tools",
    description="List available tools/toolkits from the framework's tool registry.",
)
async def list_available_tools() -> list:
    """List the tool catalog via the existing tools_catalog registry."""
    from parrot.handlers.tools_catalog import _build_catalog

    return _build_catalog()


@tool(
    name="list_existing_agents",
    description="List agents already registered in the live AgentRegistry.",
)
async def list_existing_agents() -> list:
    """List registered agent names (registry-origin only)."""
    app = _require_app()
    manager = app.get("bot_manager")
    if manager is None or manager.registry is None:
        return []
    return [meta.name for meta in manager.registry.list_agents()]


def build_studio_tools() -> list:
    """Return every AgentStudio meta-agent tool (FEAT-467 TASK-2521)."""
    return [
        save_agent_draft,
        create_yaml_agent,
        write_identity_file,
        write_kb_file,
        write_skill_file,
        publish_skill_to_catalog,
        list_agent_base_classes,
        list_available_tools,
        list_existing_agents,
    ]
