"""Shared skills catalog tool (TASK-2515) and its database-mode path."""

from __future__ import annotations

from typing import Any

from parrot.bots.studio import tools as _pkg  # patched globals (``current_context``) are read at call time
from parrot.tools import tool

from ._context import _refusing, _require_app, _require_user_id, _studio_partition_and_services


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
    try:
        resolved_category = SkillCategory(category)
    except ValueError:
        resolved_category = SkillCategory.GENERAL
    if (ps := await _studio_partition_and_services(app)) is not None:
        if isinstance(ps, dict):
            return ps
        publish = _db_publish_skill(
            app, ps, _require_user_id(), name, description, resolved_category.value, triggers, body
        )
        return await _refusing(publish)
    if app.get("database") is None:
        raise RuntimeError("Database unavailable — cannot publish to the shared catalog.")

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


async def _db_publish_skill(app: Any, ps: tuple, user_id: str, name: str, description: str, category: str,
                            triggers: list[str], body: str) -> dict:
    """``StudioSkillCatalogService.publish``, then the derived search index (the handler's own best-effort upload).

    A failed upload leaves ``search_index_stale`` true (the resync endpoint repairs it); a success leaves it false.
    """
    from parrot.handlers.studio.skills_catalog import index_published_skill, org_id_from_session  # lazy: server

    part, services = ps
    rec = await services.skills.publish(part, owner=user_id, name=name, description=description, body=body,
                                        category=category, triggers=list(triggers))
    session = getattr(getattr(_pkg.current_context(), "request", None), "session", None)
    rec = await index_published_skill(app, services.skills, part, rec, org_id_from_session(session))
    return {"skill_id": str(rec.skill_id), "name": rec.name, "description": rec.description,
            "category": rec.category, "owner": rec.owner, "triggers": list(rec.triggers or []),
            "version": rec.version, "status": rec.status, "tenant": rec.tenant, "visibility": rec.visibility,
            "search_index_stale": rec.search_index_stale}
