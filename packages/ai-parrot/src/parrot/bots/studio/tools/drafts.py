"""Draft pipeline tools (TASK-2513) and the declarative bundle tool (database mode)."""

from __future__ import annotations

from pathlib import Path

from parrot.bots.studio import tools as _pkg  # patched globals (``AGENTS_DIR``) are read at call time
from parrot.tools import tool

from ._context import _refusing, _require_app, _require_user_id, _studio_partition_and_services


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

    app = _require_app()
    # Adversarial-review fix: stamp the REAL session user as the draft's
    # owner. The previous hardcoded "agent_studio" owner meant the
    # activation endpoint's own `_require_owner` check (403 on mismatch)
    # locked every non-superuser out of activating a draft the assistant
    # had just built for them — the feature's headline flow.
    user_id = _require_user_id()

    db = app.get("database")
    existing = None
    if db is not None:
        from asyncdb.exceptions import NoDataFound

        from parrot.handlers.models.studio_drafts import StudioDraft

        try:
            async with await db.acquire() as conn:
                StudioDraft.Meta.connection = conn
                try:
                    existing = await StudioDraft.get(name=name)
                except NoDataFound:
                    existing = None
        except Exception:  # pylint: disable=broad-except
            existing = None
        # Ownership on overwrite, checked BEFORE the file write: an
        # existing draft owned by someone else must not be clobbered.
        if existing is not None and str(existing.owner_user_id) != user_id:
            raise PermissionError(f"Draft '{name}' is owned by another user; refusing to overwrite.")

    drafts_dir = Path(_pkg.AGENTS_DIR) / "_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    file_path = resolve_safe_path(drafts_dir, f"{name}.py")
    file_path.write_text(source)

    report = validate_draft(source)
    base_class = detect_base_class(source) if report.passed else None
    status = "validated" if report.passed else "failed"

    if db is not None:
        import logging as _logging
        from datetime import datetime

        from parrot.handlers.models.studio_drafts import StudioDraft

        try:
            async with await db.acquire() as conn:
                StudioDraft.Meta.connection = conn
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
                    row = StudioDraft(**fields, owner_user_id=user_id)
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


async def _db_save_bundle(ps: tuple, user_id: str, name: str, bundle: dict) -> dict:
    """``StudioDraftService.save_bundle`` for a bundle named ``name``; replacing another user's draft is refused."""
    from parrot.handlers.studio.storage.models import StudioAgentBundle

    part, services = ps
    parsed = StudioAgentBundle.model_validate({**bundle, "name": bundle.get("name", name)})
    if parsed.name != name:
        raise ValueError(f"bundle.name '{parsed.name}' must equal the draft name '{name}'.")
    existing = await services.drafts.get(part, name)
    if existing is not None and str(existing.owner) != str(user_id):
        raise PermissionError(f"Draft '{name}' is not owned by the calling user; refusing to write.")
    rec = await services.drafts.save_bundle(part, owner=user_id, bundle=parsed)
    return {"name": name, "status": rec.status, "file_path": None, "validation_report": rec.validation,
            "kind": "declarative", "version": rec.version}


@tool(
    name="save_agent_bundle",
    requires_confirmation=True,
    confirm_template="Save the declarative agent bundle {name} as a draft? It will NOT be live until activated.",
    description=(
        "Save a declarative agent bundle (definition, toolkits, MCP servers, text assets) as a draft in the "
        "database. The only draft tool on tenant partitions; NEVER activates it — activation is the separate, "
        "explicit POST /astudio/drafts/{name}/activate endpoint."
    ),
)
async def save_agent_bundle(name: str, bundle: dict) -> dict:
    """Save a declarative agent draft through ``StudioDraftService`` (database mode only).

    Args:
        name: Draft slug (``^[a-z0-9_-]+$``); equals ``bundle["name"]`` when given.
        bundle: ``{definition, toolkits, mcp_servers, assets}`` (no secrets).

    Returns:
        ``{name, status, validation_report, kind, version}``, or ``{error, error_code}`` on a policy refusal.
    """
    from parrot.handlers.studio._base import is_valid_slug

    app = _require_app()
    user_id = _require_user_id()
    ps = await _studio_partition_and_services(app)
    if isinstance(ps, dict):
        return ps
    if ps is None:
        return {"error": "Declarative drafts need database storage.", "error_code": "studio_storage_unavailable"}
    if not is_valid_slug(name):
        raise ValueError(f"Invalid draft name '{name}'; must match ^[a-z0-9_-]+$.")
    return await _refusing(_db_save_bundle(ps, user_id, name, bundle))
