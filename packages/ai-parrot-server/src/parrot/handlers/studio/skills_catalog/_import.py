"""Skill import into an agent (database + legacy bodies of ``StudioSkillsImportHandler``), as mixins."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

# the package module: patch-aware reads of ``_get_shared_skill_registry`` / ``create_skill_registry`` /
# ``AGENTS_DIR`` (tests patch ``studio.skills_catalog.<name>``); only attributes are read, at call time
from parrot.handlers.studio import skills_catalog as _sc

from .._base import resolve_safe_path
from ..access import _store_record
from ._helpers import _compose_skill_markdown, _validate_skill_markdown


class _StudioSkillsImportDbMixin:
    """Database-mode import."""

    async def _db_post(self, storage, part):
        """Write ``skills/<name>.md`` of the agent through the catalogue service, under the agent lock."""
        agent_name = self.request.match_info.get("name")
        skill_id = self.request.match_info.get("id")
        if not agent_name or not skill_id:
            return self._error("Agent name and skill id are required.", status=400, code="missing_params")
        payload = await self._db_payload(lenient=True)
        if isinstance(payload, web.Response):
            return payload
        if (denied := await self._require_author()) is not None:
            return denied
        agents = storage.services.agents
        agent = await agents.get(part, agent_name)
        if agent is None and part.tenant is None:
            return await self._legacy_post()  # not a Studio agent: the registry/filesystem path
        denied = await self._check_record_access(
            await self._access(), _store_record("agent", agent.agent_id, agent) if agent else None, "agent",
            agent_name, manage=True)
        if denied is not None:
            return denied
        skill, denied = await self._db_skill(storage, part, skill_id, manage=False)
        if denied is not None:
            return denied
        existing = await storage.services.assets.get(part, agent_name, "skills", f"{skill.name}.md")
        if existing is not None and not bool(payload.get("overwrite", False)):
            return self._error(f"Skill file '{skill.name}.md' already exists for agent '{agent_name}'; "
                               "pass overwrite=true to replace.", status=409, code="collision")
        user = await self._get_user()
        refused = await self._studio_write(
            lambda guard: storage.services.skills.import_to_agent(
                part, skill.skill_id, agent_name, actor=user.user_id, guard=guard),
            record=agent, reread=lambda: agents.get(part, agent_name),
            reauthorize=self._reauthorize("agent", agent_name), expected_version=None)
        if isinstance(refused, web.Response):
            return refused
        return self.json_response({"agent": agent_name, "skill": skill.name, "file_path": None,
                                   "reload_required": False}, status=201)


class _StudioSkillsImportLegacyMixin:
    """Legacy (on-disk) import."""

    async def _legacy_post(self):
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("skills", "astudio:skills:import")) is not None:
            return denied

        agent_name = self.request.match_info.get("name")
        skill_id = self.request.match_info.get("id")
        if not agent_name or not skill_id:
            return self._error(
                "Agent name and skill id are required.",
                status=400,
                code="missing_params",
            )

        exists, owner = await self._resolve_agent(agent_name)
        if not exists:
            return self._error(f"Agent '{agent_name}' not found.", status=404, code="not_found")

        user = await self._get_user()
        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial

        entry = await self._get_entry_by_id(skill_id)
        if entry is None:
            return self._error(f"Skill '{skill_id}' not found.", status=404, code="not_found")

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            payload = {}
        overwrite = bool((payload or {}).get("overwrite", False))

        skills_dir = Path(_sc.AGENTS_DIR) / agent_name / "skills"
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
