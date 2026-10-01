"""Shared foundation of the Studio services (spec §2.5/§2.5b): limits, allowlists, validators, gate, container."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal, Sequence
from uuid import UUID

from aiohttp import web
from navconfig import config

from parrot.tools.spec import NormalizedTooling, normalize_tooling

from .. import models as _models
from ..models import (
    StudioAgentDefinition,
    StudioAssetInput,
    StudioAssetTooLarge,
    StudioPartition,
    StudioToolingRecord,
    StudioToolingRefused,
)
from ..repositories import StudioRepositories

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .agents import StudioAgentService
    from .assets import StudioAssetService
    from .drafts import StudioDraftService
    from .catalog import StudioSkillCatalogService
    from .tooling import StudioToolingService

logger = logging.getLogger("Parrot.AgentStudio.Storage")

VISIBILITY_DOMAIN = frozenset({"private", "tenant", "groups"})
ALLOWLIST_APP_KEY = "studio_class_allowlist"
MAX_ASSET_NAME_LENGTH = 255
_KIB = 1024


class StudioValidationError(Exception):
    """A request-shape refusal; ``code`` is the X14 error code the handlers map (422 unless ``status`` says so)."""

    code: str = "validation_error"
    status: int = 422

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status


class StudioBinaryAssetRefused(StudioValidationError):
    """Assets are text only (415 ``binary_assets_unsupported``)."""

    code = "binary_assets_unsupported"
    status = 415


class StudioAssetFileTooLarge(StudioAssetTooLarge):
    """One asset over its per-kind cap (413 ``asset_too_large``)."""

    code = "asset_too_large"


class StudioAgentAssetsQuota(StudioAssetTooLarge):
    """The agent's total asset bytes would exceed the quota (413 ``agent_assets_quota``)."""

    code = "agent_assets_quota"


@dataclass(frozen=True)
class StudioLimits:
    """Asset size limits (spec §2.5 table)."""

    identity_max: int = 64 * _KIB
    kb_max: int = 256 * _KIB
    skills_max: int = 128 * _KIB
    agent_total_max: int = 4 * _KIB * _KIB

    @classmethod
    def from_config(cls) -> "StudioLimits":
        """Read the ``STUDIO_ASSET_MAX_BYTES_*`` / ``STUDIO_AGENT_MAX_ASSET_BYTES`` settings."""
        d = cls()
        return cls(
            identity_max=config.getint("STUDIO_ASSET_MAX_BYTES_IDENTITY", fallback=d.identity_max),
            kb_max=config.getint("STUDIO_ASSET_MAX_BYTES_KB", fallback=d.kb_max),
            skills_max=config.getint("STUDIO_ASSET_MAX_BYTES_SKILLS", fallback=d.skills_max),
            agent_total_max=config.getint("STUDIO_AGENT_MAX_ASSET_BYTES", fallback=d.agent_total_max),
        )

    def max_for(self, kind: str) -> int:
        """Per-file cap of an asset kind."""
        return {"identity": self.identity_max, "kb": self.kb_max, "skills": self.skills_max}[kind]


class StudioClassAllowlist:
    """Bot classes a tenant partition may use: ``parrot.bots.__all__`` plus host additions."""

    def __init__(self, extra: Iterable[str] = ()) -> None:
        self._extra = frozenset(extra)

    @classmethod
    def from_app(cls, app: Any) -> "StudioClassAllowlist":
        """Host additions come from ``app["studio_class_allowlist"]``."""
        return cls(app.get(ALLOWLIST_APP_KEY) or ())

    def names(self) -> frozenset[str]:
        """Every class name a tenant partition may use."""
        import parrot.bots as bots_module

        return frozenset(bots_module.__all__) | self._extra

    def allows(self, part: StudioPartition, bot_class: str) -> bool:
        """Tenant partitions: allowlist only. The non-tenant partition keeps ``get_bot_class`` resolution."""
        return part.tenant is None or bot_class in self.names()


class StudioToolingGate:
    """Storage-side call into the host-owned tenant tooling policy (spec §2.5b)."""

    def __init__(self, app: web.Application) -> None:
        self._app = app

    def enforce(
        self,
        part: StudioPartition,
        tooling: NormalizedTooling,
        *,
        agent_id: UUID | None,
        actor: str | None,
        phase: Literal["write", "activate", "build"],
    ) -> None:
        """enforce_tenant_tooling on the FINAL normalised tooling; TenantToolingRefused → StudioToolingRefused."""
        from parrot.tools.tooling_policy import TenantToolingRefused, ToolingSubject, enforce_tenant_tooling

        try:
            enforce_tenant_tooling(
                self._app,
                tooling,
                subject=ToolingSubject(tenant=part.tenant, agent_id=agent_id, actor=actor, phase=phase),
            )
        except TenantToolingRefused as exc:
            refused = StudioToolingRefused(str(exc))
            refused.code = exc.code  # type: ignore[attr-defined]
            refused.reason = exc.reason  # type: ignore[attr-defined]
            refused.item = exc.item  # type: ignore[attr-defined]
            raise refused from exc


def validate_visibility(part: StudioPartition, visibility: str, allowed_groups: Sequence[str] = ()) -> None:
    """Visibility domain; the non-tenant partition is always ``private`` (mirrors the DB CHECKs)."""
    if visibility not in VISIBILITY_DOMAIN:
        raise StudioValidationError(f"invalid visibility {visibility!r}", code="invalid_visibility")
    if part.tenant is None and visibility != "private":
        raise StudioValidationError("a non-tenant agent is always private", code="invalid_visibility")
    if visibility != "groups" and allowed_groups:
        raise StudioValidationError("allowed_groups requires visibility 'groups'", code="invalid_visibility")


def validate_definition_for(
    part: StudioPartition,
    definition: StudioAgentDefinition,
    *,
    allowlist: StudioClassAllowlist | None = None,
    visibility: str = "private",
    allowed_groups: Sequence[str] = (),
) -> None:
    """Bot class (tenant allowlist), tenant config keys (422 ``unsupported_config_key``) and visibility domain."""
    validate_visibility(part, visibility, allowed_groups)
    if not (allowlist or StudioClassAllowlist()).allows(part, definition.bot_class):
        raise StudioValidationError(
            f"bot_class {definition.bot_class!r} is not allowed for this tenant", code="bot_class_not_allowed"
        )
    if part.tenant is not None:
        extra = sorted(set(definition.config) - _models.STUDIO_TENANT_CONFIG_KEYS)
        if extra:
            raise StudioValidationError(f"unsupported config keys: {extra}", code="unsupported_config_key")


def _name_problem(name: str) -> str | None:
    """Why ``name`` is not a safe relative asset path (traversal, absolute, backslash, NUL, empty parts), or None."""
    if not name or len(name) > MAX_ASSET_NAME_LENGTH:
        return "asset name must be 1-255 characters"
    if "\x00" in name or "\\" in name:
        return "asset name must not contain NUL or backslash"
    if name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/")):
        return "asset name must be a relative path without '.', '..' or empty segments"
    return None


def validate_asset_input(limits: StudioLimits, asset: StudioAssetInput) -> int:
    """Validate one asset (text only, safe name, per-kind filename rules, size cap, skill frontmatter).

    Returns:
        The UTF-8 byte size of the content.

    Raises:
        StudioBinaryAssetRefused: ``content_type`` is not ``text/*`` (415).
        StudioValidationError: unsafe or kind-invalid name, invalid skill frontmatter (422).
        StudioAssetFileTooLarge: over the per-kind cap (413).
    """
    from parrot.handlers.studio.files import _StudioFilesMixin, _is_skill_definition_file

    if not asset.content_type.lower().startswith("text/"):
        raise StudioBinaryAssetRefused("only text assets are supported")
    problem = _name_problem(asset.name) or _StudioFilesMixin._validate_kind_filename(asset.kind, asset.name)
    if problem:
        raise StudioValidationError(problem, code="invalid_asset_name")
    size = len(asset.content.encode("utf-8"))
    if size > limits.max_for(asset.kind):
        raise StudioAssetFileTooLarge(f"{asset.kind}/{asset.name}: {size} > {limits.max_for(asset.kind)} bytes")
    if asset.kind == "skills" and _is_skill_definition_file(asset.name):
        problem = _StudioFilesMixin._validate_skill_content(asset.content)
        if problem:
            raise StudioValidationError(problem, code="invalid_skill")
    return size


def normalized_tooling_for(
    definition: StudioAgentDefinition, tooling_rows: Sequence[StudioToolingRecord]
) -> NormalizedTooling:
    """The tooling the builder will see: ``definition.tools`` plus the stored rows, via ``normalize_tooling``."""
    toolkits: list[dict[str, Any]] = []
    servers: list[dict[str, Any]] = []
    for row in sorted(tooling_rows, key=lambda r: (r.kind, r.position, r.slug)):
        spec = {**row.config, "secret_refs": dict(row.secret_refs), "vault_owner": row.vault_owner}
        if row.kind == "toolkit":
            toolkits.append({**spec, "slug": row.slug})
        else:
            servers.append({**spec, "name": row.slug})
    return normalize_tooling(definition.tools, toolkits, servers)


def studio_runtime_dir() -> Path:
    """``STUDIO_RUNTIME_DIR`` (default ``<tempdir>/parrot-studio-<pid>``); never under ``AGENTS_DIR``."""
    import os

    configured = config.get("STUDIO_RUNTIME_DIR")
    root = Path(configured) if configured else Path(tempfile.gettempdir()) / f"parrot-studio-{os.getpid()}"
    from parrot.conf import AGENTS_DIR

    agents = Path(AGENTS_DIR).resolve()
    resolved = root.resolve()
    if resolved == agents or agents in resolved.parents:
        raise StudioValidationError("STUDIO_RUNTIME_DIR must not be under AGENTS_DIR", code="invalid_runtime_dir")
    return root


@dataclass(frozen=True)
class StudioServices:
    """The services of one app, built over one :class:`StudioRepositories`."""

    repos: StudioRepositories
    agents: "StudioAgentService"
    assets: "StudioAssetService"
    tooling: "StudioToolingService"
    drafts: "StudioDraftService"
    skills: "StudioSkillCatalogService"


def build_studio_services(app: web.Application, repos: StudioRepositories) -> StudioServices:
    """Wire every service (modules are imported here: they land in later tasks)."""
    from .agents import StudioAgentService
    from .assets import StudioAssetService
    from .catalog import StudioSkillCatalogService
    from .drafts import StudioDraftService
    from .tooling import StudioToolingService

    limits = StudioLimits.from_config()
    allowlist = StudioClassAllowlist.from_app(app)
    gate = StudioToolingGate(app)
    tooling = StudioToolingService(repos, tooling_gate=gate)
    agents = StudioAgentService(repos, limits=limits, class_allowlist=allowlist, tooling=tooling, tooling_gate=gate)
    assets = StudioAssetService(repos, limits=limits, tooling_gate=gate)
    drafts = StudioDraftService(repos, agents=agents, class_allowlist=allowlist, tooling_gate=gate)
    skills = StudioSkillCatalogService(repos, limits=limits, runtime_dir=studio_runtime_dir())
    return StudioServices(repos, agents, assets, tooling, drafts, skills)
