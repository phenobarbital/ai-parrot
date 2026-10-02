"""Agent Studio storage types (spec §2.4). Records are frozen; payloads are Pydantic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from parrot.handlers.studio.models import CreateAgentRequest
from parrot.tools.config_schema import build_schema_envelope, is_secret_name, secret_paths
from parrot.tools.spec import MCP_SECRET_FIELDS, AgentMCPServerSpec, ToolkitSpec

STUDIO_KEY_PREFIX: Final = "studio:"
STUDIO_TOOLING_REF_PREFIX: Final = "studio-agent:"
STUDIO_MODEL_PARAM_KEYS: Final = frozenset({"temperature", "max_tokens", "top_k", "top_p"})
STUDIO_TENANT_CONFIG_KEYS: Final[frozenset[str]] = frozenset()
STUDIO_FORBIDDEN_CONFIG_KEYS: Final = frozenset(
    {
        "llm",
        "model",
        "model_config",
        "chatbot_id",
        "name",
        "mcp_servers",
        "toolkits",
        "vector_store_config",
    }
)
STUDIO_RESERVED_CONFIG_KEYS: Final = frozenset({"tenant", "created_by", "visibility", "allowed_groups"})
RESERVED_CONFIG_KEY_MESSAGE: Final = "reserved_config_key"


@dataclass(frozen=True, slots=True)
class StudioPartition:
    """The ONLY way to address rows. tenant=None is the non-tenant partition."""

    tenant: str | None
    GLOBAL: ClassVar["StudioPartition"]

    @classmethod
    def from_scope(cls, scope: Any) -> "StudioPartition":
        """Build a partition from any object exposing ``.tenant`` (duck-typed)."""
        return cls(getattr(scope, "tenant", None))


StudioPartition.GLOBAL = StudioPartition(None)


@dataclass(frozen=True, slots=True)
class StudioAgentKey:
    """Qualified runtime key of a Studio agent."""

    tenant: str | None
    name: str

    @property
    def qualified(self) -> str:
        """``studio:<tenant>:<name>``, or ``studio:-:<name>`` for tenant None."""
        return f"{STUDIO_KEY_PREFIX}{self.tenant or '-'}:{self.name}"

    @classmethod
    def parse(cls, qualified: str) -> "StudioAgentKey":
        """Parse a qualified key; raise ``ValueError`` on a malformed one."""
        if not qualified.startswith(STUDIO_KEY_PREFIX):
            raise ValueError(f"not a studio key: {qualified!r}")
        tenant, sep, name = qualified[len(STUDIO_KEY_PREFIX) :].partition(":")
        if not sep or not tenant or not name or ":" in name:
            raise ValueError(f"malformed studio key: {qualified!r}")
        return cls(None if tenant == "-" else tenant, name)

    def __post_init__(self) -> None:
        if self.tenant == "-":
            raise ValueError("'-' is not a valid tenant")
        if ":" in self.name or not self.name:
            raise ValueError("agent name must be non-empty and contain no ':'")


class StudioModelParams(BaseModel):
    """LLM sampling settings. The ONLY source of these values for a Studio agent."""

    model_config = ConfigDict(extra="forbid")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    top_k: int | None = Field(default=None, gt=0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)


class StudioAgentDefinition(BaseModel):
    """What POST /agents accepts, minus transport flags and the name."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    bot_class: str = "BasicBot"
    llm: str | None = None
    model_params: StudioModelParams = Field(default_factory=StudioModelParams)
    system_prompt: str | None = None
    description: str | None = None
    category: str = "general"
    tools: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def _check_config_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Refuse keys that are moved elsewhere, overwritten by the factory or reserved."""
        reserved = STUDIO_RESERVED_CONFIG_KEYS & value.keys()
        if reserved:
            raise ValueError(f"{RESERVED_CONFIG_KEY_MESSAGE}: {sorted(reserved)}")
        moved = (STUDIO_MODEL_PARAM_KEYS | STUDIO_FORBIDDEN_CONFIG_KEYS | {"system_prompt", "tools"}) & value.keys()
        if moved:
            raise ValueError(f"config keys not allowed (own field or factory-overwritten): {sorted(moved)}")
        return value

    @classmethod
    def from_create_request(cls, req: CreateAgentRequest) -> "StudioAgentDefinition":
        """Normalise the FEAT-467 payload; drops ``persist`` and ``name``."""
        config = dict(req.config)
        params = {k: config.pop(k) for k in list(config) if k in STUDIO_MODEL_PARAM_KEYS}
        system_prompt = config.pop("system_prompt", None)
        tools = config.pop("tools", None)
        return cls(
            bot_class=req.bot_class,
            llm=req.llm,
            model_params=StudioModelParams(**params),
            system_prompt=system_prompt,
            description=req.description,
            category=req.category,
            tools=list(tools or []),
            config=config,
        )


class StudioAgentPatch(BaseModel):
    """PATCH /agents/{name} body. Merge-patch of the General fields; omitted = unchanged."""

    model_config = ConfigDict(extra="forbid")
    description: str | None = None
    llm: str | None = None
    model_params: StudioModelParams | None = None
    system_prompt: str | None = None
    category: str | None = None
    expected_version: int | None = None


class StudioAssetInput(BaseModel):
    """One asset (identity / kb / skills) of an agent bundle."""

    kind: Literal["identity", "kb", "skills"]
    name: str
    content: str
    content_type: str = "text/markdown"


def _named_secret_paths(value: Any, prefix: str = "") -> list[str]:
    """Find secret-like names inside mappings and arrays, including unknown toolkit parameters."""
    found: list[str] = []
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, child in items:
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and is_secret_name(str(key)):
            found.append(path)
        else:
            found.extend(_named_secret_paths(child, path))
    return found


def _toolkit_secret_paths(spec: ToolkitSpec) -> list[str]:
    """Inspect the same toolkit classes and x-secret schemas used by the Tools tab, without constructing them."""
    from ..tooling_store import _EXPLICIT, _resolve_toolkit_class

    cls = _EXPLICIT.get(spec.slug) or _resolve_toolkit_class(spec.slug)
    if cls is None:
        return []  # Optional/unavailable toolkits still get recursive name checks.
    schema = build_schema_envelope(spec.slug, cls).schema_
    return secret_paths(schema, spec.params)


def _secret_fields_of(label: str, spec: ToolkitSpec | AgentMCPServerSpec) -> list[str]:
    """Names of the secret-bearing fields set on ``spec``."""
    found: list[str] = []
    if spec.secret_refs:
        found.append(f"{label}.secret_refs")
    if spec.vault_owner:
        found.append(f"{label}.vault_owner")
    paths = set(_named_secret_paths(spec.params))
    if isinstance(spec, AgentMCPServerSpec):
        paths.update(field for field in MCP_SECRET_FIELDS if field in spec.params)
    elif spec.params:
        paths.update(_toolkit_secret_paths(spec))
    found.extend(f"{label}.params.{path}" for path in sorted(paths))
    return found


class StudioAgentBundle(BaseModel):
    """Name + definition + tooling + assets. Secret-bearing fields are refused."""

    name: str
    definition: StudioAgentDefinition
    toolkits: list[ToolkitSpec] = Field(default_factory=list)
    mcp_servers: list[AgentMCPServerSpec] = Field(default_factory=list)
    assets: list[StudioAssetInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refuse_secrets(self) -> "StudioAgentBundle":
        """Secrets are entered in the Tools tab, never carried by a bundle."""
        found: list[str] = []
        for spec in self.toolkits:
            found.extend(_secret_fields_of(f"toolkits[{spec.slug}]", spec))
        for srv in self.mcp_servers:
            found.extend(_secret_fields_of(f"mcp_servers[{srv.name}]", srv))
        if found:
            raise ValueError(f"secret-bearing fields are not allowed in a bundle: {found}")
        return self


@dataclass(frozen=True, slots=True)
class StudioAgentHead:
    """Result of the per-lookup revalidation query and of the row lock."""

    agent_id: UUID
    version: int
    status: str


@dataclass(frozen=True, slots=True)
class StudioWriteGuard:
    """Preconditions checked under the agent (or draft) row lock, in the write transaction."""

    authorized_version: int | None = None
    expected_version: int | None = None
    # Identity of the authorized row (agent_id / draft_id): a delete + re-create lands on a fresh id even when
    # its version equals the authorized one (a re-created row starts at version 1), which versions alone miss.
    authorized_id: Any = None

    @classmethod
    def for_record(cls, record: Any, *, expected_version: int | None = None) -> "StudioWriteGuard":
        """The guard authorizing exactly ``record`` (an agent or draft record); no guard fields when ``None``."""
        if record is None:
            return cls(expected_version=expected_version)
        ident = getattr(record, "agent_id", None) or getattr(record, "draft_id", None)
        return cls(authorized_version=record.version, expected_version=expected_version, authorized_id=ident)

    def check(self, head: "StudioAgentHead", name: str) -> "StudioAgentHead":
        """Under the row lock: VersionConflict, then StaleAuthorization (version, then identity). Returns ``head``."""
        if self.expected_version is not None and self.expected_version != head.version:
            raise StudioVersionConflict(f"{name}: expected {self.expected_version}, found {head.version}")
        if self.authorized_version is not None and self.authorized_version != head.version:
            raise StudioStaleAuthorization(f"{name}: authorized {self.authorized_version}, found {head.version}")
        if self.authorized_id is not None and self.authorized_id != head.agent_id:
            raise StudioStaleAuthorization(f"{name}: the authorized record was replaced")
        return head


@dataclass(frozen=True, slots=True)
class StudioAgentRecord:
    """An ``ai_agents`` row."""

    agent_id: UUID
    tenant: str | None
    name: str
    owner: str
    visibility: str
    allowed_groups: tuple[str, ...]
    definition: StudioAgentDefinition
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    @property
    def key(self) -> StudioAgentKey:
        """Qualified key of this agent."""
        return StudioAgentKey(self.tenant, self.name)

    @property
    def tooling_ref(self) -> str:
        """``studio-agent:<agent_id>`` (canonical lowercase hyphenated UUID)."""
        return f"{STUDIO_TOOLING_REF_PREFIX}{self.agent_id}"


@dataclass(frozen=True, slots=True)
class StudioAssetRecord:
    """An ``ai_agent_assets`` row."""

    agent_id: UUID
    kind: str
    name: str
    content: str | None
    content_type: str
    size: int
    sha256: str
    storage_uri: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StudioToolingRecord:
    """An ``ai_agent_tooling`` row."""

    agent_id: UUID
    kind: str
    slug: str
    position: int
    config: dict
    secret_refs: dict
    vault_owner: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StudioAgentSnapshot:
    """One consistent read of an agent and all its children."""

    record: StudioAgentRecord
    assets: tuple[StudioAssetRecord, ...]
    tooling: tuple[StudioToolingRecord, ...]


@dataclass(frozen=True, slots=True)
class StudioDraftRecord:
    """An ``ai_agent_drafts`` row."""

    draft_id: UUID
    tenant: str | None
    owner: str
    name: str
    visibility: str
    allowed_groups: tuple[str, ...]
    bundle: StudioAgentBundle
    validation: dict
    status: str
    version: int
    activated_agent_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StudioSkillRecord:
    """An ``ai_skills`` row."""

    skill_id: UUID
    tenant: str | None
    owner: str
    visibility: str
    allowed_groups: tuple[str, ...]
    name: str
    description: str
    category: str
    triggers: list
    body: str
    version: int
    status: str
    search_index_stale: bool
    created_at: datetime
    updated_at: datetime


class StudioNameConflict(Exception):
    """Duplicate name in the partition (409)."""


class StudioVersionConflict(Exception):
    """Client ``expected_version`` is stale (409 version_conflict)."""


class StudioStaleAuthorization(Exception):
    """``authorized_version`` moved; the handler re-authorises once."""


class StudioNotFound(Exception):
    """Row vanished under the lock (404)."""


class StudioAssetTooLarge(Exception):
    """Asset or per-agent quota exceeded (413)."""


class StudioToolingRefused(Exception):
    """Tenant tooling policy refused the tooling (422 tooling_not_permitted)."""


class StudioStorageUnavailable(Exception):
    """Storage not reachable (503 studio_storage_unavailable)."""


class StudioStorageError(Exception):
    """A statement failed (asyncdb error tuple) → 500."""
