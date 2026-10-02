"""Shared context/partition/refusal helpers for the AgentStudio meta-agent tools."""

from __future__ import annotations

from typing import Any

from parrot.bots.studio import tools as _pkg  # patched globals (``current_context``) are read at call time


def _require_app() -> Any:
    """Return the aiohttp Application bound to the current tool call.

    Raises:
        RuntimeError: No ``RequestContext`` is bound (tool called outside
            an ``agent.session(request=..., app=...)`` block — AgentStudio
            tools require app context to reach the database/registry).
    """
    ctx = _pkg.current_context()
    if ctx is None or ctx.app is None:
        raise RuntimeError(
            "AgentStudio tools require an active request context "
            "(agent.session(request=..., app=...)); none is bound."
        )
    return ctx.app


def _require_user_id() -> str:
    """Return the session user's id bound to the current tool call.

    ``StudioAssistantHandler`` passes ``user_id=`` into
    ``agent.session(...)`` (adversarial-review fix) so mutating tools can
    stamp real ownership and enforce it. Fail-closed: a mutating tool
    with no caller identity must refuse rather than write unowned (or
    worse, mis-owned) state.

    Raises:
        RuntimeError: No ``RequestContext`` is bound, or it carries no
            ``user_id``.
    """
    ctx = _pkg.current_context()
    if ctx is None or not getattr(ctx, "user_id", None):
        raise RuntimeError(
            "AgentStudio mutating tools require the caller's user identity "
            "(agent.session(..., user_id=...)); none is bound — refusing "
            "to write."
        )
    return str(ctx.user_id)


def _unscoped_refusal() -> dict:
    """The ``tool_scope_unavailable`` refusal (FEAT-605 X14) for a call on an opted-in host with no bound scope."""
    return {
        "error": "tool_scope_unavailable: no studio_scope is bound to this tool call (reason: no_scope)",
        "error_code": "tool_scope_unavailable",
    }


async def _studio_partition_and_services(app: Any) -> tuple[Any, Any] | dict | None:
    """``(partition, services)`` in database mode, else ``None`` (filesystem path).

    The partition is the bound ``studio_scope.caller``'s (FEAT-605) when present. With no bound scope it is GLOBAL
    (X11) only on a plain host; when the host installed a scope resolver (opted in) the call FAILS CLOSED and the
    ``tool_scope_unavailable`` refusal dict is returned (callers return it as-is; nothing is written).
    """
    storage = app.get("studio_storage")
    if storage is None or storage.backend != "database":
        return None
    from parrot.handlers.scope import has_installed_resolver  # lazy: server satellite
    from parrot.handlers.studio.storage.models import StudioPartition  # lazy: server satellite

    scope = (getattr(_pkg.current_context(), "kwargs", None) or {}).get("studio_scope")
    if scope is None and has_installed_resolver(app):
        return _unscoped_refusal()
    part = StudioPartition.from_scope(scope.caller) if scope is not None else StudioPartition.GLOBAL
    storage.require_for(part)
    return part, storage.services


def _refusal_code(exc: Exception) -> str | None:
    """X14 code of a storage/service refusal, or ``None`` for anything that is not one."""
    from pydantic import ValidationError

    from parrot.handlers.studio.storage import models as m
    from parrot.handlers.studio.storage.services._common import StudioValidationError

    if isinstance(exc, ValidationError):
        return "validation_error"
    if isinstance(exc, (StudioValidationError, m.StudioAssetTooLarge)):
        return getattr(exc, "code", "validation_error")
    table = (
        (m.StudioNameConflict, "duplicate"),
        (m.StudioNotFound, "not_found"),
        (m.StudioToolingRefused, "tooling_not_permitted"),
        ((m.StudioVersionConflict, m.StudioStaleAuthorization), "version_conflict"),
        (m.StudioStorageUnavailable, "studio_storage_unavailable"),
    )
    return next((code for kinds, code in table if isinstance(exc, kinds)), None)


async def _refusing(awaitable: Any) -> dict:
    """Await a service call; a policy/validation refusal becomes ``{error, error_code}`` (X14), the rest raises."""
    try:
        return await awaitable
    except Exception as exc:  # pylint: disable=broad-except
        code = _refusal_code(exc)
        if code is None:
            raise
        return {"error": str(exc) or code, "error_code": code}


async def _require_agent_owner(app: Any, agent_name: str, user_id: str) -> None:
    """Refuse unless ``user_id`` owns ``agent_name`` (adversarial-review fix).

    Mirrors the SAME dual-source owner lookup the Studio file-CRUD
    endpoints use (``_StudioFilesMixin._resolve_agent``): registry
    metadata's ``bot_config.config['created_by']`` first, then a
    DB-origin agent's ``created_by`` column. The HTTP path enforces this
    via ``StudioBaseView._require_owner``; this is the equivalent gate
    for the meta-agent tool path, which previously had none.

    Args:
        app: The aiohttp Application (source of ``bot_manager``/``database``).
        agent_name: Target agent.
        user_id: The calling session user's id.

    Raises:
        ValueError: The agent does not exist.
        PermissionError: The agent exists but is not owned by ``user_id``
            (including unowned agents — fail closed, same posture as
            ``_require_owner``).
    """
    owner = None
    exists = False

    manager = app.get("bot_manager")
    registry = getattr(manager, "registry", None) if manager is not None else None
    if registry is not None:
        meta = registry.get_metadata(agent_name)
        if meta is not None:
            exists = True
            bot_config = getattr(meta, "bot_config", None)
            if bot_config is not None:
                owner = (getattr(bot_config, "config", None) or {}).get("created_by")

    if not exists:
        db = app.get("database")
        if db is not None:
            from asyncdb.exceptions import NoDataFound

            from parrot.handlers.models import BotModel

            try:
                async with await db.acquire() as conn:
                    BotModel.Meta.connection = conn
                    try:
                        db_agent = await BotModel.get(name=agent_name)
                    except NoDataFound:
                        db_agent = None
            except Exception:  # pylint: disable=broad-except
                db_agent = None
            if db_agent is not None:
                exists = True
                owner = db_agent.created_by

    if not exists:
        raise ValueError(f"Agent '{agent_name}' not found.")
    if owner is None or str(owner) != str(user_id):
        raise PermissionError(f"Agent '{agent_name}' is not owned by the calling user; refusing to write.")
