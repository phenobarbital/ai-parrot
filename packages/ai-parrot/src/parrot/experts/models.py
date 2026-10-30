"""Domain-expert data models, manifest invariants and errors (FEAT-778, spec §2/M1)."""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPAWN_TOOL_NAME: Final[str] = "spawn_sub_agent"
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

LayerName = Literal[
    "rules",
    "tier1_shared",
    "tier1_expert",
    "tier2_shared",
    "tier2_expert",
    "adr",
    "stage_input",
    "retrieval",
]


class ExpertError(Exception):
    """Base class for every domain-expert error."""


class ExpertBundleError(ExpertError):
    """A bundle directory is malformed (manifest, identity, `$` placeholder…)."""


class DuplicateExpertError(ExpertError):
    """Two bundles in the same root declare the same name."""


class ExpertKnowledgeError(ExpertError):
    """A knowledge source cannot be resolved (e.g. empty or unwritable wiki namespace)."""


class ExpertPolicyError(ExpertError):
    """A policy invariant would be violated (e.g. spawn tool in the allowlist)."""


class ExpertCapabilityError(ExpertError):
    """A tool needs a capability the manifest does not declare."""


class RuleSyntaxError(ExpertError):
    """A governance rules file contains a line outside the ALWAYS/NEVER grammar."""


class KnowledgeMode(str, Enum):
    """How an expert knowledge source is made available."""

    INLINE = "inline"
    RETRIEVAL = "retrieval"


class KnowledgeSourceKind(str, Enum):
    """Supported expert knowledge source types."""

    BUNDLED = "bundled"
    WORKSPACE = "workspace"
    WIKI = "wiki"
    BOOKSTORE = "bookstore"
    GRAPHINDEX = "graphindex"
    ADR = "adr"
    KB = "kb"


class ExpertTier(str, Enum):
    """Policy tier used to select an expert model configuration."""

    JUDGMENT = "judgment"
    BALANCED = "balanced"
    TEMPLATED = "templated"


class KnowledgeSourceSpec(BaseModel):
    """One `knowledge:` entry of expert.yaml."""

    model_config = ConfigDict(extra="forbid")

    source: KnowledgeSourceKind
    mode: KnowledgeMode
    scope: dict[str, list[str]] = Field(default_factory=dict)
    filter: dict[str, list[str]] = Field(default_factory=dict)


class ExpertManifest(BaseModel):
    """Machine-read expert.yaml."""

    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    description: str
    tier: ExpertTier = ExpertTier.BALANCED
    toolkits: list[str] = Field(default_factory=list)
    tools_allow: list[str] = Field(default_factory=list)
    knowledge: list[KnowledgeSourceSpec]
    capabilities: list[Literal["validate", "write", "review"]] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    global_only: bool = False

    @field_validator("name")
    @classmethod
    def _kebab(cls, value: str) -> str:
        """Validate a 2-64 character kebab-case expert name."""
        if not 2 <= len(value) <= 64 or _KEBAB.match(value) is None:
            raise ValueError("name must be 2-64 characters of kebab-case")
        return value

    @model_validator(mode="after")
    def _invariants(self) -> ExpertManifest:
        """Validate mandatory wiki access and the no-delegation rule."""
        if not any(source.source is KnowledgeSourceKind.WIKI for source in self.knowledge):
            raise ValueError("knowledge must include a wiki source")
        if SPAWN_TOOL_NAME in self.toolkits or SPAWN_TOOL_NAME in self.tools_allow:
            raise ValueError(f"{SPAWN_TOOL_NAME} is not permitted for domain experts")
        return self


class RuleSet(BaseModel):
    """Parsed governance rules for one scope layer."""

    layer: Literal["org", "team", "project", "expert", "stage"]
    source: Path
    revision: str
    mandated: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class KnowledgeLayer(BaseModel):
    """One resolved inline or retrieval knowledge layer."""

    layer: LayerName
    source: str
    mode: KnowledgeMode
    revision: str
    tokens: int = 0
    content: str | None = None
    handle: dict[str, Any] | None = None


class KnowledgeContext(BaseModel):
    """Resolved knowledge made available to a domain expert."""

    expert: str
    stage: str | None = None
    budget_tokens: int
    layers: list[KnowledgeLayer] = Field(default_factory=list)
    trimmed: list[KnowledgeLayer] = Field(default_factory=list)

    def inline_text(self, layer: str) -> str:
        """Concatenate inline contents for one layer name in their original order."""
        return "\n\n".join(
            item.content
            for item in self.layers
            if item.layer == layer and item.mode is KnowledgeMode.INLINE and item.content is not None
        )

    def retrieval_handles(self) -> list[KnowledgeLayer]:
        """Return retrieval layers in their original order."""
        return [item for item in self.layers if item.mode is KnowledgeMode.RETRIEVAL]


class ExpertBundle(BaseModel):
    """The validated files and metadata that make up one expert bundle."""

    manifest: ExpertManifest
    root: Path
    identity_dir: Path
    persona_doc: Path | None = None
    knowledge_files: list[Path] = Field(default_factory=list)
    rules: RuleSet | None = None
    adr_dir: Path | None = None
    tenant: str | None = None
    origin: Literal["bundled", "workspace"] = "workspace"
