"""Module-level helpers of the shared skills catalog: shared-index registry, markdown validation, reconcile."""

from __future__ import annotations

import dataclasses
import logging
import tempfile
from pathlib import Path
from typing import Any

import yaml
from parrot.skills.parsers import parse_skill_file

# the package module: patch-aware reads of ``_get_shared_skill_registry`` / ``create_skill_registry`` /
# ``AGENTS_DIR`` (tests patch ``studio.skills_catalog.<name>``); only attributes are read, at call time
from parrot.handlers.studio import skills_catalog as _sc

from ...models.skills_catalog import SkillCatalogEntry

try:
    from navigator_auth.conf import AUTH_SESSION_OBJECT
except ImportError:  # pragma: no cover — navigator-auth always installed in prod
    AUTH_SESSION_OBJECT = "session"


DEFAULT_ORG_ID = "default"
SHARED_NAMESPACE_SUFFIX = "_shared"
_REGISTRIES_APP_KEY = "studio_shared_skill_registries"
logger = logging.getLogger("Parrot.AgentStudio")

def _shared_namespace(org_id: str) -> str:
    """Return the reserved shared-catalog namespace for ``org_id``."""
    return f"{org_id}/{SHARED_NAMESPACE_SUFFIX}"


def _get_shared_skill_registry(app: Any, org_id: str, part: Any = None):
    """Return (creating + caching on ``app`` if absent) the shared
    ``SkillRegistry`` for ``org_id``.

    A module-level function (not a method) so tests can monkeypatch it
    directly to avoid loading a real embedding model.

    Args:
        app: The aiohttp Application.
        org_id: Tenant/org id — ``"default"`` when the session carries none.
        part: The ``StudioPartition`` on the database backend: the registry is then the DERIVED per-pod
            index at ``shared_index_location(part, org_id)`` (under ``STUDIO_RUNTIME_DIR``, never
            ``AGENTS_DIR``). ``None`` (filesystem backend) keeps the ``AGENTS_DIR`` layout.

    Returns:
        A configured-on-first-use ``SkillRegistry`` for
        ``"<org_id>/_shared"``.
    """
    registries = app.get(_REGISTRIES_APP_KEY)
    if registries is None:
        registries = {}
        app[_REGISTRIES_APP_KEY] = registries
    namespace, persistence_path = _shared_index(org_id, part)
    cache_key = org_id if part is None else namespace
    registry = registries.get(cache_key)
    if registry is None:
        registry = _sc.create_skill_registry(namespace=namespace, persistence_path=persistence_path)
        registries[cache_key] = registry
    return registry


def _shared_index(org_id: str, part: Any) -> tuple[str, Path]:
    """``(namespace, persistence_path)`` of the shared index: derived location on the database backend."""
    if part is not None:
        from ..storage.services.catalog import shared_index_location

        return shared_index_location(part, org_id)
    return _shared_namespace(org_id), Path(_sc.AGENTS_DIR) / SHARED_NAMESPACE_SUFFIX / org_id / "skills"


def _validate_skill_markdown(content: str) -> str | None:
    """Validate composed skill markdown via a scratch tmp-file parse.

    Mirrors ``handlers/studio/files.py``'s identical technique (TASK-2514)
    — never writes the real target, returns an error message on failure.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        parse_skill_file(tmp_path)
        return None
    except Exception as exc:  # pylint: disable=broad-except
        return str(exc)
    finally:
        tmp_path.unlink(missing_ok=True)


def _compose_skill_markdown(entry: SkillCatalogEntry) -> str:
    """Compose frontmatter + body for importing a catalog entry as a
    per-agent skill file (spec §3 Module 7 — "frontmatter composed from
    the entry")."""
    frontmatter = {
        "name": entry.name,
        "description": entry.description,
        "triggers": list(entry.triggers or []),
        "category": entry.category,
        "version": str(entry.version),
        # parse_skill_file() validates `source` against SkillSource,
        # which only has AUTHORED/LEARNED members (no "catalog"/"shared"
        # value exists) — a catalog import is developer-authored content,
        # not LLM-learned.
        "source": "authored",
    }
    fm_text = yaml.safe_dump(frontmatter, sort_keys=False)
    return f"---\n{fm_text}---\n\n{entry.body}\n"


async def reconcile_skills_catalog(app: Any) -> None:
    """``app.on_startup`` hook: re-upload every ``search_index_stale``
    catalog row into the shared registry (best-effort, never blocks
    startup — spec §7 "Dual-write drift ... startup reconciliation").

    Args:
        app: The aiohttp Application (``app.on_startup.append(...)``
            passes it automatically).
    """
    db = app.get("database")
    if db is None:
        return
    if await _reconcile_database(app):
        return
    try:
        async with await db.acquire() as conn:
            SkillCatalogEntry.Meta.connection = conn
            stale_entries = await SkillCatalogEntry.filter(search_index_stale=True)
    except Exception:  # pylint: disable=broad-except
        return
    if not stale_entries:
        return

    for entry in stale_entries:
        try:
            registry = _sc._get_shared_skill_registry(app, DEFAULT_ORG_ID)
            await registry.upload_skill(
                name=entry.name,
                content=entry.body,
                agent_id=entry.owner,
                description=entry.description,
                category=entry.category,
                triggers=list(entry.triggers or []),
                owner_user_id=entry.owner,
                skill_id=str(entry.skill_id),
            )
            entry.search_index_stale = False
            async with await db.acquire() as conn:
                SkillCatalogEntry.Meta.connection = conn
                await entry.update()
        except Exception:  # pylint: disable=broad-except
            continue


def _skill_dict(rec: Any) -> dict:
    """Response item of a ``StudioSkillRecord``: the FEAT-467 keys plus ``tenant``/``visibility``/``allowed_groups``."""
    return {
        "skill_id": str(rec.skill_id), "name": rec.name, "description": rec.description, "category": rec.category,
        "owner": rec.owner, "triggers": list(rec.triggers or []), "body": rec.body, "version": rec.version,
        "status": rec.status, "search_index_stale": rec.search_index_stale, "tenant": rec.tenant,
        "visibility": rec.visibility, "allowed_groups": list(rec.allowed_groups),
    }


async def _upload_to_index(registry: Any, rec: Any) -> None:
    """Upload one catalogue record into the derived shared index."""
    await registry.upload_skill(
        name=rec.name, content=rec.body, agent_id=rec.owner, description=rec.description, category=rec.category,
        triggers=list(rec.triggers or []), owner_user_id=rec.owner, skill_id=str(rec.skill_id),
    )


def org_id_from_session(session: Any) -> str:
    """The shared-namespace org id carried by ``session`` (``userinfo.org_id``); ``"default"`` when absent."""
    if not session or not hasattr(session, "get"):
        return DEFAULT_ORG_ID
    userinfo = session.get(AUTH_SESSION_OBJECT, {})
    if not isinstance(userinfo, dict):
        return DEFAULT_ORG_ID
    org_id = userinfo.get("org_id") or userinfo.get("organization_id")
    return str(org_id) if org_id else DEFAULT_ORG_ID


async def index_published_skill(app: Any, svc: Any, part: Any, rec: Any, org_id: str = DEFAULT_ORG_ID) -> Any:
    """Best-effort upload of a published/updated catalogue record to the partition's derived search index.

    Shared by the HTTP handler and the assistant's ``publish_skill_to_catalog`` tool. A failure never raises: the
    row is flagged ``search_index_stale`` (the resync endpoint / startup reconcile repairs it) and the returned
    record carries the flag; on success the record is returned unchanged (flag cleared).
    """
    try:
        await _upload_to_index(_sc._get_shared_skill_registry(app, org_id, part), rec)
        return rec
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Studio: registry dual-write failed for skill '%s': %s", rec.name, exc)
    await svc.mark_stale(part, rec.skill_id)
    return dataclasses.replace(rec, search_index_stale=True)


async def _rebuild_index(svc: Any, part: Any, registry: Any, rows: list) -> tuple[int, int]:
    """Re-upload ``rows`` into the derived index, clearing ``search_index_stale``; returns ``(resynced, failed)``."""
    resynced = failed = 0
    for rec in rows:
        try:
            await _upload_to_index(registry, rec)
            if rec.search_index_stale:
                await svc.mark_stale(part, rec.skill_id, False)
            resynced += 1
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Studio: index rebuild failed for skill '%s': %s", rec.name, exc)
            failed += 1
    return resynced, failed


async def _reconcile_database(app: Any) -> bool:
    """Database backend: rebuild the GLOBAL partition's derived index from Postgres. ``False`` = not applicable."""
    from ..storage.backend import ensure_studio_storage
    from ..storage.models import StudioPartition

    try:
        storage = app.get("studio_storage") or await ensure_studio_storage(app)
        if storage.backend != "database":
            return False
        svc = storage.services.skills
        registry = _sc._get_shared_skill_registry(app, DEFAULT_ORG_ID, StudioPartition.GLOBAL)
        await _rebuild_index(svc, StudioPartition.GLOBAL, registry, await svc.list(StudioPartition.GLOBAL))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Studio: startup skills reconcile failed: %s", exc)
    return True
