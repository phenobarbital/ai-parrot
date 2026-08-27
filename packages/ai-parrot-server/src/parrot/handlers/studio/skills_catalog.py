"""Shared skills catalog — org-wide, category-ordered, owner-filterable
(FEAT-467 TASK-2515).

Hybrid storage (spec §3 Module 7, resolved decision): Postgres
(``navigator.ai_skills_catalog`` / :class:`SkillCatalogEntry`) is the
system-of-record and SQL query plane (``ORDER BY category``,
``WHERE owner``); the shared-namespace ``SkillRegistry`` (``"<org_id>/
_shared"``) is a best-effort secondary index for embedding search and
git-like versioning. PG write always happens FIRST; the registry write
is wrapped so a Redis/embedding outage never fails a publish — it only
flags ``search_index_stale=True`` for later repair (startup
reconciliation pass, or the admin ``/skills/resync`` endpoint).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import yaml
from asyncdb.exceptions import NoDataFound
from navigator_auth.decorators import is_authenticated, user_session
from pydantic import ValidationError

try:
    from navigator_auth.conf import AUTH_SESSION_OBJECT
except ImportError:  # pragma: no cover — navigator-auth always installed in prod
    AUTH_SESSION_OBJECT = "session"

from parrot.conf import AGENTS_DIR
from parrot.skills.models import SkillCategory
from parrot.skills.parsers import parse_skill_file
from parrot.skills.store import create_skill_registry

from ..models.skills_catalog import SkillCatalogEntry
from ._base import StudioBaseView, resolve_safe_path
from .models import SkillPublishRequest, StudioError

DEFAULT_ORG_ID = "default"
SHARED_NAMESPACE_SUFFIX = "_shared"
_REGISTRIES_APP_KEY = "studio_shared_skill_registries"


def _shared_namespace(org_id: str) -> str:
    """Return the reserved shared-catalog namespace for ``org_id``."""
    return f"{org_id}/{SHARED_NAMESPACE_SUFFIX}"


def _get_shared_skill_registry(app: Any, org_id: str):
    """Return (creating + caching on ``app`` if absent) the shared
    ``SkillRegistry`` for ``org_id``.

    A module-level function (not a method) so tests can monkeypatch it
    directly to avoid loading a real embedding model.

    Args:
        app: The aiohttp Application.
        org_id: Tenant/org id — ``"default"`` when the session carries none.

    Returns:
        A configured-on-first-use ``SkillRegistry`` for
        ``"<org_id>/_shared"``.
    """
    registries = app.get(_REGISTRIES_APP_KEY)
    if registries is None:
        registries = {}
        app[_REGISTRIES_APP_KEY] = registries
    registry = registries.get(org_id)
    if registry is None:
        persistence_path = Path(AGENTS_DIR) / SHARED_NAMESPACE_SUFFIX / org_id / "skills"
        registry = create_skill_registry(
            namespace=_shared_namespace(org_id),
            persistence_path=persistence_path,
        )
        registries[org_id] = registry
    return registry


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
            registry = _get_shared_skill_registry(app, DEFAULT_ORG_ID)
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


class _StudioSkillsMixin:
    """Shared helpers for the skills-catalog views in this module."""

    async def _get_org_id(self) -> str:
        """Best-effort org_id from the session; ``"default"`` when absent
        (Implementation Notes: "org_id for the shared namespace: derive
        from session; when absent use 'default'")."""
        try:
            session = await self._resolve_session()
        except Exception:  # pylint: disable=broad-except
            return DEFAULT_ORG_ID
        if not session or not hasattr(session, "get"):
            return DEFAULT_ORG_ID
        userinfo = session.get(AUTH_SESSION_OBJECT, {})
        if not isinstance(userinfo, dict):
            return DEFAULT_ORG_ID
        org_id = userinfo.get("org_id") or userinfo.get("organization_id")
        return str(org_id) if org_id else DEFAULT_ORG_ID

    async def _get_entry_by_id(self, skill_id: str) -> SkillCatalogEntry | None:
        db = self.request.app.get("database")
        if db is None:
            return None
        try:
            async with await db.acquire() as conn:
                SkillCatalogEntry.Meta.connection = conn
                try:
                    return await SkillCatalogEntry.get(skill_id=skill_id)
                except NoDataFound:
                    return None
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to query skill '%s': %s", skill_id, exc)
            return None

    async def _get_entry_by_name(self, name: str) -> SkillCatalogEntry | None:
        db = self.request.app.get("database")
        if db is None:
            return None
        try:
            async with await db.acquire() as conn:
                SkillCatalogEntry.Meta.connection = conn
                try:
                    return await SkillCatalogEntry.get(name=name)
                except NoDataFound:
                    return None
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to query skill by name '%s': %s", name, exc)
            return None

    async def _list_entries(self, **filters: Any) -> list[SkillCatalogEntry]:
        """Return catalog entries, optionally filtered by exact column match."""
        db = self.request.app.get("database")
        if db is None:
            raise RuntimeError("Database unavailable.")
        async with await db.acquire() as conn:
            SkillCatalogEntry.Meta.connection = conn
            entries = await SkillCatalogEntry.filter(**filters)
            return entries or []

    async def _insert_entry(self, entry: SkillCatalogEntry) -> None:
        db = self.request.app.get("database")
        if db is None:
            raise RuntimeError("Database unavailable.")
        async with await db.acquire() as conn:
            SkillCatalogEntry.Meta.connection = conn
            await entry.insert()

    async def _update_entry(self, entry: SkillCatalogEntry) -> None:
        db = self.request.app.get("database")
        if db is None:
            raise RuntimeError("Database unavailable.")
        async with await db.acquire() as conn:
            SkillCatalogEntry.Meta.connection = conn
            await entry.update()

    async def _delete_entry(self, entry: SkillCatalogEntry) -> None:
        db = self.request.app.get("database")
        if db is None:
            raise RuntimeError("Database unavailable.")
        async with await db.acquire() as conn:
            SkillCatalogEntry.Meta.connection = conn
            await entry.delete()

    @staticmethod
    def _entry_to_dict(entry: SkillCatalogEntry) -> dict:
        return {
            "skill_id": str(entry.skill_id),
            "name": entry.name,
            "description": entry.description,
            "category": entry.category,
            "owner": entry.owner,
            "triggers": list(entry.triggers or []),
            "body": entry.body,
            "version": entry.version,
            "status": entry.status,
            "search_index_stale": entry.search_index_stale,
        }

    def _error(self, message: str, *, status: int, code: str | None = None):
        return self.json_response(
            StudioError(message=message, code=code).model_dump(),
            status=status,
        )


@is_authenticated()
@user_session()
class StudioSkillsCatalogHandler(_StudioSkillsMixin, StudioBaseView):
    """``/api/v1/astudio/skills`` and ``/api/v1/astudio/skills/{id}``.

    GET (list ordered/grouped by category, or one entry + registry
    versions), POST (publish — PG first, registry best-effort), PUT/
    DELETE (owner-or-admin).
    """

    async def get(self):
        skill_id = self.request.match_info.get("id")
        if skill_id:
            return await self._get_one(skill_id)
        return await self._get_all()

    async def _get_all(self):
        qs = self.request.rel_url.query
        category_param = qs.get("category")
        owner_param = qs.get("owner")

        if category_param:
            valid_values = [c.value for c in SkillCategory]
            if category_param not in valid_values:
                return self._error(
                    f"Invalid category '{category_param}'; must be one of " f"{valid_values}.",
                    status=400,
                    code="invalid_category",
                )

        filters: dict[str, Any] = {}
        if category_param:
            filters["category"] = category_param
        if owner_param:
            filters["owner"] = owner_param

        try:
            entries = await self._list_entries(**filters)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to list skills: %s", exc)
            return self._error("Failed to list skills.", status=500, code="list_failed")

        entries = sorted(entries or [], key=lambda e: (e.category, e.name))

        grouped: dict[str, list[dict]] = {}
        for entry in entries:
            grouped.setdefault(entry.category, []).append(self._entry_to_dict(entry))

        return self.json_response({"skills": grouped, "count": len(entries)})

    async def _get_one(self, skill_id: str):
        entry = await self._get_entry_by_id(skill_id)
        if entry is None:
            return self._error(f"Skill '{skill_id}' not found.", status=404, code="not_found")
        data = self._entry_to_dict(entry)
        try:
            registry = _get_shared_skill_registry(self.request.app, await self._get_org_id())
            data["versions"] = await registry.get_skill_versions(str(entry.skill_id))
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "Studio: failed to fetch registry versions for '%s': %s",
                skill_id,
                exc,
            )
            data["versions"] = []
        return self.json_response(data)

    async def post(self):
        """Publish a new shared skill — PG insert first, registry
        best-effort (spec §7: "Never fail a publish because Redis is down")."""
        if self.request.match_info.get("id"):
            return self._error(
                "Use POST /astudio/skills (no id in the URL) to publish.",
                status=400,
                code="invalid_route",
            )

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            publish_request = SkillPublishRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        existing = await self._get_entry_by_name(publish_request.name)
        if existing is not None:
            return self._error(
                f"Skill '{publish_request.name}' already exists.",
                status=409,
                code="duplicate",
            )

        if self.request.app.get("database") is None:
            return self._error("Database unavailable.", status=503, code="unavailable")

        user = await self._get_user()

        entry = SkillCatalogEntry(
            name=publish_request.name,
            description=publish_request.description,
            category=publish_request.category.value,
            owner=user.user_id,
            triggers=list(publish_request.triggers),
            body=publish_request.body,
            version=1,
            status="active",
            search_index_stale=False,
        )
        try:
            await self._insert_entry(entry)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error(
                "Studio: failed to insert skill catalog entry '%s': %s",
                publish_request.name,
                exc,
            )
            return self._error(f"Failed to publish skill: {exc}", status=500, code="publish_failed")

        stale = await self._dual_write_to_registry(entry, user.user_id)
        if stale:
            await self._flag_stale(entry)

        return self.json_response(self._entry_to_dict(entry), status=201)

    async def put(self):
        skill_id = self.request.match_info.get("id")
        if not skill_id:
            return self._error("Skill id is required.", status=400, code="missing_id")

        entry = await self._get_entry_by_id(skill_id)
        if entry is None:
            return self._error(f"Skill '{skill_id}' not found.", status=404, code="not_found")

        user = await self._get_user()
        self._require_owner(entry.owner, user)  # raises 403 on denial

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        try:
            publish_request = SkillPublishRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        if self.request.app.get("database") is None:
            return self._error("Database unavailable.", status=503, code="unavailable")

        entry.set("description", publish_request.description)
        entry.set("category", publish_request.category.value)
        entry.set("triggers", list(publish_request.triggers))
        entry.set("body", publish_request.body)
        entry.set("version", entry.version + 1)
        try:
            await self._update_entry(entry)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to update skill '%s': %s", skill_id, exc)
            return self._error("Failed to update skill.", status=500, code="update_failed")

        stale = await self._dual_write_to_registry(entry, entry.owner)
        if stale and not entry.search_index_stale:
            await self._flag_stale(entry)

        return self.json_response(self._entry_to_dict(entry))

    async def delete(self):
        skill_id = self.request.match_info.get("id")
        if not skill_id:
            return self._error("Skill id is required.", status=400, code="missing_id")

        entry = await self._get_entry_by_id(skill_id)
        if entry is None:
            return self._error(f"Skill '{skill_id}' not found.", status=404, code="not_found")

        user = await self._get_user()
        self._require_owner(entry.owner, user)  # raises 403 on denial

        if self.request.app.get("database") is None:
            return self._error("Database unavailable.", status=503, code="unavailable")

        try:
            await self._delete_entry(entry)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to delete skill '%s': %s", skill_id, exc)
            return self._error("Failed to delete skill.", status=500, code="delete_failed")

        try:
            registry = _get_shared_skill_registry(self.request.app, await self._get_org_id())
            await registry.revoke_skill(str(entry.skill_id), reason="deleted via Studio catalog")
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning("Studio: registry revoke failed for '%s': %s", skill_id, exc)

        return self.json_response({"skill_id": str(entry.skill_id), "deleted": True})

    # -- shared dual-write helpers ---------------------------------------

    async def _dual_write_to_registry(self, entry: SkillCatalogEntry, owner_user_id: str) -> bool:
        """Best-effort registry upload. Returns True on failure (caller
        flags ``search_index_stale``) — NEVER raises."""
        try:
            registry = _get_shared_skill_registry(self.request.app, await self._get_org_id())
            await registry.upload_skill(
                name=entry.name,
                content=entry.body,
                agent_id=owner_user_id,
                description=entry.description,
                category=entry.category,
                triggers=list(entry.triggers or []),
                owner_user_id=owner_user_id,
                skill_id=str(entry.skill_id),
            )
            return False
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "Studio: registry dual-write failed for skill '%s': %s",
                entry.name,
                exc,
            )
            return True

    async def _flag_stale(self, entry: SkillCatalogEntry) -> None:
        entry.set("search_index_stale", True)
        try:
            await self._update_entry(entry)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error(
                "Studio: failed to flag search_index_stale for '%s': %s",
                entry.name,
                exc,
            )


@is_authenticated()
@user_session()
class StudioSkillsImportHandler(_StudioSkillsMixin, StudioBaseView):
    """``POST /api/v1/astudio/agents/{name}/skills/import/{id}``.

    Materializes a catalog entry as
    ``AGENTS_DIR/<agent>/skills/<name>.md`` — collision refused (409)
    unless ``overwrite=true``.
    """

    async def post(self):
        agent_name = self.request.match_info.get("name")
        skill_id = self.request.match_info.get("id")
        if not agent_name or not skill_id:
            return self._error(
                "Agent name and skill id are required.",
                status=400,
                code="missing_params",
            )

        entry = await self._get_entry_by_id(skill_id)
        if entry is None:
            return self._error(f"Skill '{skill_id}' not found.", status=404, code="not_found")

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            payload = {}
        overwrite = bool((payload or {}).get("overwrite", False))

        skills_dir = Path(AGENTS_DIR) / agent_name / "skills"
        try:
            target = resolve_safe_path(skills_dir, f"{entry.name}.md")
        except ValueError as exc:
            return self._error(str(exc), status=400, code="invalid_path")

        if target.exists() and not overwrite:
            return self._error(
                f"Skill file '{entry.name}.md' already exists for agent "
                f"'{agent_name}'; pass overwrite=true to replace.",
                status=409,
                code="collision",
            )

        markdown = _compose_skill_markdown(entry)
        error = _validate_skill_markdown(markdown)
        if error:
            return self._error(error, status=422, code="invalid_frontmatter")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown)

        return self.json_response(
            {
                "agent": agent_name,
                "skill": entry.name,
                "file_path": str(target),
                "reload_required": True,
            },
            status=201,
        )


@is_authenticated()
@user_session()
class StudioSkillsResyncHandler(_StudioSkillsMixin, StudioBaseView):
    """``POST /api/v1/astudio/skills/resync`` — admin-only.

    Re-uploads every ``search_index_stale`` catalog row into the shared
    registry; returns counts. Same routine the startup hook runs
    automatically (:func:`reconcile_skills_catalog`), exposed here for an
    on-demand admin retry.
    """

    async def post(self):
        user = await self._get_user()
        if not user.is_superuser:
            return self._error("Admin privileges required.", status=403, code="admin_required")

        if self.request.app.get("database") is None:
            return self._error("Database unavailable.", status=503, code="unavailable")

        try:
            stale_entries = await self._list_entries(search_index_stale=True)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: resync failed to query stale entries: %s", exc)
            return self._error("Failed to query stale entries.", status=500, code="resync_failed")

        resynced = 0
        failed = 0
        org_id = await self._get_org_id()
        for entry in stale_entries:
            try:
                registry = _get_shared_skill_registry(self.request.app, org_id)
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
                entry.set("search_index_stale", False)
                await self._update_entry(entry)
                resynced += 1
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning("Studio: resync failed for skill '%s': %s", entry.name, exc)
                failed += 1

        return self.json_response({"resynced": resynced, "failed": failed, "total": len(stale_entries)})
