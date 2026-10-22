"""Per-agent asset file tools (TASK-2514) and their database-mode path."""

from __future__ import annotations

from pathlib import Path

from parrot.bots.studio import tools as _pkg  # patched globals (``AGENTS_DIR``) are read at call time
from parrot.tools import tool

from ._context import (
    _can_manage_agent,
    _refusing,
    _require_agent_owner,
    _require_app,
    _require_author,
    _require_user_id,
    _studio_partition_and_services,
)


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

    # Adversarial-review fix: the HTTP file-CRUD endpoints call
    # `_require_owner` before every write; this tool path previously had
    # NO ownership check at all — any user driving the assistant could
    # write into any other user's agent directories.
    _require_author()
    app = _require_app()
    user_id = _require_user_id()
    ps = await _studio_partition_and_services(app)
    if isinstance(ps, dict):
        return ps
    if ps is None:
        await _require_agent_owner(app, agent_name, user_id)

    base_dir = Path(_pkg.AGENTS_DIR) / agent_name / kind
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

    if ps is not None:
        return await _refusing(_db_put_asset(ps, user_id, agent_name, kind, filename, content))

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


async def _db_put_asset(ps: tuple, user_id: str, agent_name: str, kind: str, filename: str, content: str) -> dict:
    """``StudioAssetService.put`` after the owner check on the agent row (fail closed, like the file path)."""
    from parrot.handlers.studio.storage.models import StudioAssetInput, StudioWriteGuard

    part, services = ps
    agent = await services.agents.get(part, agent_name)
    if agent is None:
        raise ValueError(f"Agent '{agent_name}' not found.")
    if not _can_manage_agent(agent, user_id):
        raise PermissionError(f"Agent '{agent_name}' is not owned by the calling user; refusing to write.")
    asset = StudioAssetInput(kind=kind, name=filename, content=content)
    record, version = await services.assets.put(part, agent_name, asset, actor=user_id, guard=StudioWriteGuard())
    return {"agent_name": agent_name, "kind": kind, "path": filename, "size": record.size, "version": version,
            "reload_required": False}
