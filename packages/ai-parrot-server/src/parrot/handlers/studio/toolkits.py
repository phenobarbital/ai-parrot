"""Studio toolkit config surfaces — schema introspection + assignment
(FEAT-467 TASK-2518).

Implements spec §3 Module 10:

    GET  /api/v1/astudio/toolkits/{slug}/schema     — config schema
    POST /api/v1/astudio/agents/{name}/toolkits     — assign a configured
                                                        toolkit to the LIVE
                                                        agent instance

Three toolkits get first-class handling (``wiki``, ``dataset_manager``,
``infographic``); any other slug resolves generically via
``TOOL_REGISTRY`` + constructor-signature introspection.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from navigator_auth.decorators import is_authenticated, user_session
from parrot.conf import AGENTS_DIR
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.wiki import LLMWikiToolkit, WikiConfig
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.discovery import discover_from_registry, resolve_class
from parrot.tools.infographic_toolkit import InfographicToolkit
from pydantic import BaseModel, Field, ValidationError

from ._base import StudioBaseView, resolve_safe_path
from .agents import _StudioAgentsMixin
from .models import StudioError

# Configurable root for wiki storage directories submitted as *relative*
# paths (no dedicated wiki-storage config var exists elsewhere in the
# codebase — see TASK-2518 Completion Note). Absolute paths are honored
# as-is (server operator's responsibility) after a system-path denylist
# check; relative paths are sandboxed under this root via
# ``resolve_safe_path`` (traversal-safe — TASK-2511).
_WIKI_STORAGE_ROOT = AGENTS_DIR / "wiki_storage"

# System paths a submitted absolute ``storage_dir`` must never resolve to
# (or land directly under) — a coarse denylist, not a sandbox. NOTE:
# does NOT include "/" itself — every absolute path has "/" as an
# ancestor, so treating it as a forbidden *parent* would reject every
# absolute path; only an EXACT match on "/" is checked separately below.
_FORBIDDEN_ABSOLUTE_ROOTS = (
    Path("/etc"),
    Path("/root"),
    Path("/bin"),
    Path("/sbin"),
    Path("/usr"),
    Path("/sys"),
    Path("/proc"),
    Path("/boot"),
    Path("/dev"),
)


class ToolkitAssignRequest(BaseModel):
    """``POST /agents/{name}/toolkits`` payload."""

    slug: str
    params: dict[str, Any] = Field(default_factory=dict)


class _ToolkitAssignError(Exception):
    """Raised by the per-toolkit assignment helpers; mapped to a response
    by the handler."""

    def __init__(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


# ---------------------------------------------------------------------------
# Signature introspection (schema generation)
# ---------------------------------------------------------------------------


def _type_str(annotation: Any) -> str:
    """Best-effort human-readable type string for a constructor parameter."""
    if annotation is inspect.Parameter.empty:
        return "Any"
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", str(annotation))


def _json_safe(value: Any) -> Any:
    """Coerce a constructor default into a JSON-serialisable value."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return str(value)


def _introspect_params(cls: type, *, server_managed: frozenset[str] = frozenset()) -> dict[str, dict[str, Any]]:
    """Build a param-name -> {required, server_managed, type, default} map.

    Args:
        cls: The toolkit class whose ``__init__`` to introspect.
        server_managed: Parameter names the client can never supply — the
            server wires them from app context.

    Returns:
        A dict describing every non-``self``/``**kwargs`` constructor
        parameter.
    """
    sig = inspect.signature(cls.__init__)
    out: dict[str, dict[str, Any]] = {}
    for pname, param in sig.parameters.items():
        if pname == "self" or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        required = param.default is inspect.Parameter.empty
        entry: dict[str, Any] = {
            "required": required,
            "server_managed": pname in server_managed,
            "type": _type_str(param.annotation),
        }
        if not required:
            entry["default"] = _json_safe(param.default)
        out[pname] = entry
    return out


def _missing_required_params(cls: type, provided: dict) -> list[str]:
    """Required (no-default) constructor params not present in ``provided``."""
    sig = inspect.signature(cls.__init__)
    missing = []
    for pname, param in sig.parameters.items():
        if pname == "self" or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if param.default is inspect.Parameter.empty and pname not in provided:
            missing.append(pname)
    return missing


def _resolve_toolkit_class(slug: str) -> type | None:
    """Resolve a generic toolkit slug via ``TOOL_REGISTRY`` (case-insensitive).

    Deliberately uses ``discover_from_registry`` (declarative
    ``TOOL_REGISTRY`` dicts only) rather than the full ``discover_all``
    walk — matches the Codebase Contract's explicit "resolve via
    TOOL_REGISTRY" guidance for generic slugs.

    Args:
        slug: Candidate toolkit slug.

    Returns:
        The resolved class, or ``None`` if unknown/unresolvable.
    """
    registry = discover_from_registry()
    dotted_path = registry.get(slug)
    if dotted_path is None:
        lowered = {key.lower(): value for key, value in registry.items()}
        dotted_path = lowered.get(slug.lower())
    if dotted_path is None:
        return None
    try:
        return resolve_class(dotted_path)
    except (ImportError, AttributeError):
        return None


def _validate_wiki_storage_dir(raw: Path) -> Path:
    """Validate/resolve a client-submitted ``WikiConfig.storage_dir``.

    Absolute paths are accepted as-is after a system-path denylist check
    (server operator's responsibility). Relative paths are sandboxed
    under :data:`_WIKI_STORAGE_ROOT` via ``resolve_safe_path``
    (rejects ``..`` traversal and symlink escapes).

    Args:
        raw: The client-submitted ``storage_dir``.

    Returns:
        The validated, resolved absolute path.

    Raises:
        ValueError: ``raw`` is empty, resolves to (or under) a forbidden
            system path, or escapes the sandboxed root.
    """
    if raw is None:
        raise ValueError("storage_dir is required.")
    if raw.is_absolute():
        resolved = raw.resolve()
        if resolved == Path("/"):
            raise ValueError("storage_dir must not be the filesystem root.")
        for forbidden in _FORBIDDEN_ABSOLUTE_ROOTS:
            if resolved == forbidden or forbidden in resolved.parents:
                raise ValueError(f"storage_dir must not resolve under a system path: {raw!r}")
        return resolved
    return resolve_safe_path(_WIKI_STORAGE_ROOT, str(raw))


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


@is_authenticated()
@user_session()
class StudioToolkitsHandler(_StudioAgentsMixin, StudioBaseView):
    """``/api/v1/astudio/toolkits/{slug}/schema`` and
    ``/api/v1/astudio/agents/{name}/toolkits``.

    GET serves a toolkit's configuration schema; POST assigns a
    configured toolkit instance onto a live agent's ``tool_manager``.
    """

    def _error(self, message: str, *, status: int, code: str | None = None, details: dict | None = None):
        return self.json_response(
            StudioError(message=message, code=code, details=details).model_dump(),
            status=status,
        )

    # -- GET: schema -------------------------------------------------

    async def get(self):
        slug = self.request.match_info.get("slug")
        if not slug:
            return self._error("Toolkit slug is required.", status=400, code="missing_slug")

        if slug == "wiki":
            schema = self._wiki_schema()
        elif slug == "dataset_manager":
            schema = self._dataset_manager_schema()
        elif slug == "infographic":
            schema = self._infographic_schema()
        else:
            cls = _resolve_toolkit_class(slug)
            if cls is None:
                return self._error(f"Unknown toolkit '{slug}'.", status=404, code="not_found")
            schema = {
                "slug": slug,
                "class_name": cls.__name__,
                "params": _introspect_params(cls),
            }

        return self.json_response(schema)

    @staticmethod
    def _wiki_schema() -> dict:
        params = _introspect_params(
            LLMWikiToolkit,
            server_managed=frozenset({"pageindex_toolkit", "graphindex_toolkit", "okf_toolkit"}),
        )
        if "config" in params:
            params["config"]["schema"] = WikiConfig.model_json_schema()
        return {"slug": "wiki", "class_name": "LLMWikiToolkit", "params": params}

    @staticmethod
    def _dataset_manager_schema() -> dict:
        return {
            "slug": "dataset_manager",
            "class_name": "DatasetManager",
            "params": _introspect_params(DatasetManager),
        }

    @staticmethod
    def _infographic_schema() -> dict:
        return {
            "slug": "infographic",
            "class_name": "InfographicToolkit",
            "params": _introspect_params(InfographicToolkit, server_managed=frozenset({"artifact_store"})),
        }

    # -- POST: assignment ----------------------------------------------

    async def post(self):
        name = self.request.match_info.get("name")
        if not name:
            return self._error("Agent name is required.", status=400, code="missing_name")

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            assign_request = ToolkitAssignRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        db_agent = await self._get_db_agent(name)
        if db_agent is not None:
            owner = str(db_agent.created_by) if db_agent.created_by is not None else None
        else:
            registry = self._registry()
            meta = registry.get_metadata(name) if registry is not None else None
            if meta is None:
                return self._error(f"Agent '{name}' not found.", status=404, code="not_found")
            owner = self._registry_agent_owner(meta)

        user = await self._get_user()
        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial

        manager = self._manager()
        if manager is None:
            return self._error("BotManager unavailable.", status=503, code="unavailable")

        bot = await manager.get_bot(name)
        if bot is None:
            return self._error(f"Agent '{name}' has no live instance.", status=404, code="not_found")

        slug = assign_request.slug
        params = assign_request.params
        try:
            if slug == "wiki":
                registered_names, extra = await self._assign_wiki(bot, params)
            elif slug == "dataset_manager":
                registered_names, extra = self._assign_dataset_manager(bot, params)
            elif slug == "infographic":
                registered_names, extra = self._assign_infographic(bot, params)
            else:
                registered_names, extra = self._assign_generic(bot, slug, params)
        except _ToolkitAssignError as exc:
            return self._error(exc.message, status=exc.status, code=exc.code, details=exc.details)

        response = {
            "agent": name,
            "slug": slug,
            "registered_tools": sorted(registered_names),
            "reload_required": False,
            "persisted": False,
        }
        response.update(extra)
        return self.json_response(response, status=200)

    # -- Per-toolkit assignment helpers ---------------------------------

    async def _assign_wiki(self, bot, params: dict) -> tuple[list[str], dict]:
        """Assign ``LLMWikiToolkit`` — reuse-else-build for pageindex/graphindex.

        Per TASK-2518 Codebase Contract: no bot-level capture attribute
        exists for the OKF toolkit (only ``_pageindex_toolkit`` /
        ``_graphindex_toolkit`` / ``_llmwiki_toolkit`` are declared on
        ``AbstractBot``), and ``OKFToolkit`` cannot be constructed from a
        bare ``WikiConfig`` (it requires an already-ingested,
        OKF-enriched PageIndex tree). ``LLMWikiToolkit.__init__`` only
        stores ``okf_toolkit`` — it is never touched during construction
        — so ``None`` is passed; OKF-specific wiki tools are unavailable
        until a real OKF toolkit is wired in separately.
        """
        try:
            config = WikiConfig(**params)
        except ValidationError as exc:
            raise _ToolkitAssignError(422, "invalid_config", f"Invalid WikiConfig: {exc}") from exc

        try:
            storage_dir = _validate_wiki_storage_dir(config.storage_dir)
        except ValueError as exc:
            raise _ToolkitAssignError(422, "invalid_storage_dir", str(exc)) from exc
        config = config.model_copy(update={"storage_dir": storage_dir})

        pageindex_toolkit = getattr(bot, "_pageindex_toolkit", None)
        pageindex_source = "reused"
        if pageindex_toolkit is None:
            pageindex_source = "built"
            adapter = PageIndexLLMAdapter(client=bot.get_client())
            pageindex_toolkit = PageIndexToolkit(adapter=adapter, storage_dir=storage_dir / "pageindex")

        graphindex_toolkit = getattr(bot, "_graphindex_toolkit", None)
        graphindex_source = "reused"
        if graphindex_toolkit is None:
            graphindex_source = "built"
            graphindex_toolkit = await build_graph_memory_toolkit(
                db_dir=storage_dir / "graphindex",
                agent_id=bot.name,
            )

        self.logger.info(
            "Studio wiki assignment for '%s': pageindex=%s graphindex=%s",
            bot.name,
            pageindex_source,
            graphindex_source,
        )

        toolkit = LLMWikiToolkit(
            pageindex_toolkit,
            graphindex_toolkit,
            None,
            config,
            agent_id=bot.name,
        )
        registered = bot.tool_manager.register_toolkit(toolkit)
        return (
            [t.name for t in registered],
            {"pageindex_source": pageindex_source, "graphindex_source": graphindex_source},
        )

    def _assign_dataset_manager(self, bot, params: dict) -> tuple[list[str], dict]:
        try:
            toolkit = DatasetManager(**params)
        except TypeError as exc:
            missing = _missing_required_params(DatasetManager, params)
            raise _ToolkitAssignError(
                422,
                "invalid_params",
                str(exc),
                details={"missing": missing} if missing else None,
            ) from exc
        registered = bot.tool_manager.register_toolkit(toolkit)
        return [t.name for t in registered], {}

    def _assign_infographic(self, bot, params: dict) -> tuple[list[str], dict]:
        artifact_store = self.request.app.get("artifact_store")
        if artifact_store is None:
            raise _ToolkitAssignError(
                422,
                "server_managed",
                "InfographicToolkit requires app['artifact_store'], which is not configured.",
                details={"missing": ["artifact_store"]},
            )
        try:
            toolkit = InfographicToolkit(artifact_store=artifact_store, **params)
        except TypeError as exc:
            missing = _missing_required_params(InfographicToolkit, {**params, "artifact_store": artifact_store})
            raise _ToolkitAssignError(
                422,
                "invalid_params",
                str(exc),
                details={"missing": missing} if missing else None,
            ) from exc
        registered = bot.tool_manager.register_toolkit(toolkit)
        return [t.name for t in registered], {}

    def _assign_generic(self, bot, slug: str, params: dict) -> tuple[list[str], dict]:
        cls = _resolve_toolkit_class(slug)
        if cls is None:
            raise _ToolkitAssignError(404, "not_found", f"Unknown toolkit '{slug}'.")
        missing = _missing_required_params(cls, params)
        if missing:
            raise _ToolkitAssignError(
                422,
                "server_managed",
                f"Toolkit '{slug}' requires params this endpoint can't supply.",
                details={"missing": missing},
            )
        try:
            toolkit = cls(**params)
        except TypeError as exc:
            raise _ToolkitAssignError(422, "invalid_params", str(exc)) from exc
        registered = bot.tool_manager.register_toolkit(toolkit)
        return [t.name for t in registered], {}
