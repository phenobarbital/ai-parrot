"""Studio per-agent asset file management — identity/kb/skills CRUD
(FEAT-467 TASK-2514).

Exposes sandboxed CRUD for ``AGENTS_DIR/<agent>/{identity,kb,skills}/``.
Changes take effect only after an explicit reload (FEAT-467 TASK-2510/
TASK-2512) — every mutating response flags ``reload_required: true``;
this handler never triggers a reload itself (resolved decision, spec §3
Module 6).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from asyncdb.exceptions import NoDataFound
from navigator_auth.decorators import is_authenticated, user_session
from parrot.bots.prompts.identity import IDENTITY_FILES
from parrot.conf import AGENTS_DIR
from parrot.skills.parsers import parse_skill_file

from ..models import BotModel
from ._base import StudioBaseView, is_valid_slug, resolve_safe_path
from .models import StudioError

VALID_KINDS = ("identity", "kb", "skills")
KB_EXTENSIONS = (".md", ".txt")
IDENTITY_FILENAMES = tuple(f"{name}.md" for name in IDENTITY_FILES)


def _validate_identity_filename(filename: str) -> str | None:
    """Return an error message, or ``None`` if ``filename`` is one of the
    five canonical identity files."""
    if filename not in IDENTITY_FILENAMES:
        names = ", ".join(IDENTITY_FILENAMES)
        return f"Identity filename must be one of: {names}."
    return None


def _validate_kb_filename(filename: str) -> str | None:
    """Return an error message, or ``None`` if ``filename`` is a flat
    ``.md``/``.txt`` file (matches ``_get_kb_local_files``'s scan)."""
    path = Path(filename)
    if len(path.parts) != 1:
        return "KB filenames must not contain subdirectories."
    if path.suffix not in KB_EXTENSIONS:
        return "KB files must have a .md or .txt extension."
    return None


def _validate_skills_filename(filename: str) -> str | None:
    """Return an error message, or ``None`` for a valid skills path.

    Valid shapes: single-file ``<name>.md``, or composite
    ``<name>/SKILL.md`` + ``<name>/<asset>`` (assets unrestricted).
    """
    path = Path(filename)
    if len(path.parts) == 1:
        if path.suffix != ".md":
            return "Single-file skills must have a .md extension."
        return None
    if len(path.parts) == 2:
        return None  # SKILL.md or a composite asset file
    return "Skill paths must be either '<name>.md' or '<name>/<asset>'."


def _is_skill_definition_file(filename: str) -> bool:
    """True when ``filename`` is a skill's frontmatter-bearing entry point
    (single-file ``<name>.md``, or composite ``<name>/SKILL.md``) — the
    ONLY skills paths that get ``parse_skill_file`` validation; adjacent
    composite assets are written as-is."""
    path = Path(filename)
    return path.suffix == ".md" and (len(path.parts) == 1 or path.name == "SKILL.md")


class _StudioFilesMixin:
    """Shared helpers for the asset-file view in this module."""

    def _registry(self):
        manager = self.request.app.get("bot_manager")
        return manager.registry if manager else None

    async def _get_db_agent(self, name: str) -> BotModel | None:
        db = self.request.app.get("database")
        if db is None:
            return None
        try:
            async with await db.acquire() as conn:
                BotModel.Meta.connection = conn
                try:
                    return await BotModel.get(name=name)
                except NoDataFound:
                    return None
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to query DB agent '%s': %s", name, exc)
            return None

    async def _resolve_agent(self, name: str) -> tuple[bool, str | None]:
        """Return ``(exists, owner)`` for an agent by name.

        Checks the registry first (own bot_config.config['created_by']
        stamp — TASK-2512 convention), then falls back to a DB-origin
        agent's ``created_by`` column — assets live under
        ``AGENTS_DIR/<agent>/`` regardless of the agent's origin.
        """
        registry = self._registry()
        meta = registry.get_metadata(name) if registry is not None else None
        if meta is not None:
            owner = None
            if meta.bot_config is not None:
                owner = (meta.bot_config.config or {}).get("created_by")
            return True, (str(owner) if owner is not None else None)
        db_agent = await self._get_db_agent(name)
        if db_agent is not None:
            owner = db_agent.created_by
            return True, (str(owner) if owner is not None else None)
        return False, None

    @staticmethod
    def _validate_kind_filename(kind: str, filename: str) -> str | None:
        if kind == "identity":
            return _validate_identity_filename(filename)
        if kind == "kb":
            return _validate_kb_filename(filename)
        if kind == "skills":
            return _validate_skills_filename(filename)
        return None

    @staticmethod
    def _validate_skill_content(content: str) -> str | None:
        """Validate skill frontmatter via a scratch tmp-file parse.

        Returns an error message on failure, ``None`` on success. Never
        writes the real target file — callers only proceed to the real
        write when this returns ``None`` (spec: "on PUT of a skill file,
        validate with parse_skill_file (tmp-file parse) -> 422 ... only
        then move into place" — TASK-2514 Implementation Notes).
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            parse_skill_file(tmp_path)
            return None
        except Exception as exc:  # pylint: disable=broad-except
            # ValueError (missing frontmatter fields) or pydantic
            # ValidationError (e.g. MAX_TOKENS body cap) — both surfaced
            # verbatim as the 422 message.
            return str(exc)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _error(self, message: str, *, status: int, code: str | None = None):
        return self.json_response(
            StudioError(message=message, code=code).model_dump(),
            status=status,
        )


@is_authenticated()
@user_session()
class StudioFilesHandler(_StudioFilesMixin, StudioBaseView):
    """``/api/v1/astudio/agents/{name}/files/{kind}[/{filename:.*}]``.

    GET (list a kind, or read one file), PUT (write — owner-enforced),
    DELETE (remove — owner-enforced, always allowed even for an in-use
    file).
    """

    async def get(self):
        agent_name = self.request.match_info.get("name")
        kind = self.request.match_info.get("kind")
        filename = self.request.match_info.get("filename")

        if not agent_name or not is_valid_slug(agent_name):
            return self._error(
                "Invalid agent name.", status=400, code="invalid_agent"
            )
        if kind not in VALID_KINDS:
            return self._error(
                f"Unknown kind '{kind}'; must be one of {VALID_KINDS}.",
                status=400,
                code="invalid_kind",
            )

        exists, _owner = await self._resolve_agent(agent_name)
        if not exists:
            return self._error(
                f"Agent '{agent_name}' not found.", status=404, code="not_found"
            )

        base_dir = Path(AGENTS_DIR) / agent_name / kind

        if not filename:
            return self._list_files(base_dir, kind)

        try:
            target = resolve_safe_path(base_dir, filename)
        except ValueError as exc:
            return self._error(str(exc), status=400, code="invalid_path")

        if not target.exists() or not target.is_file():
            return self._error(
                f"File '{filename}' not found.", status=404, code="not_found"
            )

        return self.json_response({
            "path": filename,
            "kind": kind,
            "size": target.stat().st_size,
            "content": target.read_text(),
        })

    def _list_files(self, base_dir: Path, kind: str):
        if not base_dir.exists():
            return self.json_response({"kind": kind, "files": []})
        files = sorted(
            str(p.relative_to(base_dir)) for p in base_dir.rglob("*") if p.is_file()
        )
        return self.json_response({"kind": kind, "files": files})

    async def put(self):
        agent_name = self.request.match_info.get("name")
        kind = self.request.match_info.get("kind")
        filename = self.request.match_info.get("filename")

        if not agent_name or not is_valid_slug(agent_name):
            return self._error(
                "Invalid agent name.", status=400, code="invalid_agent"
            )
        if kind not in VALID_KINDS:
            return self._error(
                f"Unknown kind '{kind}'; must be one of {VALID_KINDS}.",
                status=400,
                code="invalid_kind",
            )
        if not filename:
            return self._error(
                "Filename is required.", status=400, code="missing_filename"
            )

        exists, owner = await self._resolve_agent(agent_name)
        if not exists:
            return self._error(
                f"Agent '{agent_name}' not found.", status=404, code="not_found"
            )

        user = await self._get_user()
        self._require_owner(owner, user)  # raises 403 on denial

        base_dir = Path(AGENTS_DIR) / agent_name / kind
        try:
            target = resolve_safe_path(base_dir, filename)
        except ValueError as exc:
            return self._error(str(exc), status=400, code="invalid_path")

        kind_error = self._validate_kind_filename(kind, filename)
        if kind_error:
            return self._error(kind_error, status=400, code="invalid_filename")

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        content = (payload or {}).get("content")
        if content is None:
            return self._error(
                "'content' is required.", status=400, code="missing_content"
            )

        if kind == "skills" and _is_skill_definition_file(filename):
            error = self._validate_skill_content(content)
            if error:
                return self._error(error, status=422, code="invalid_frontmatter")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

        return self.json_response(
            {
                "path": filename,
                "kind": kind,
                "size": target.stat().st_size,
                "reload_required": True,
            },
            status=200,
        )

    async def delete(self):
        agent_name = self.request.match_info.get("name")
        kind = self.request.match_info.get("kind")
        filename = self.request.match_info.get("filename")

        if not agent_name or not is_valid_slug(agent_name):
            return self._error(
                "Invalid agent name.", status=400, code="invalid_agent"
            )
        if kind not in VALID_KINDS:
            return self._error(
                f"Unknown kind '{kind}'; must be one of {VALID_KINDS}.",
                status=400,
                code="invalid_kind",
            )
        if not filename:
            return self._error(
                "Filename is required.", status=400, code="missing_filename"
            )

        exists, owner = await self._resolve_agent(agent_name)
        if not exists:
            return self._error(
                f"Agent '{agent_name}' not found.", status=404, code="not_found"
            )

        user = await self._get_user()
        self._require_owner(owner, user)  # raises 403 on denial

        base_dir = Path(AGENTS_DIR) / agent_name / kind
        try:
            target = resolve_safe_path(base_dir, filename)
        except ValueError as exc:
            return self._error(str(exc), status=400, code="invalid_path")

        if not target.exists():
            return self._error(
                f"File '{filename}' not found.", status=404, code="not_found"
            )

        # Deleting a file the live agent uses is allowed — never blocked
        # (resolved decision, spec §3 Module 6).
        target.unlink()

        return self.json_response(
            {"path": filename, "kind": kind, "deleted": True, "reload_required": True}
        )
