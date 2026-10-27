"""Inter-agent capability contract models and deterministic category hashing."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.interagent.descriptors import MediaType

CAP_ID_PATTERN = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"


class ReturnsSpec(BaseModel):
    """Specify whether a capability returns inline data or an artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    kind: Literal["inline", "artifact"]
    media_type: MediaType | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")


class PolicyAnnotations(BaseModel):
    """Describe policy constraints applied to a capability invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_class: str = "internal"
    redaction: str | None = None
    aggregation_min: int | None = None
    row_cap: int | None = None
    cacheable: bool = False
    cache_ttl_s: int | None = None
    rate_limit_per_caller: str | None = Field(default=None, pattern=r"^\d+/(s|m|h)$")
    token_budget: int | None = None


class SquawkCapability(BaseModel):
    """Define one immutable capability exposed through the inter-agent contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cap_id: str = Field(pattern=CAP_ID_PATTERN)
    category: str
    description: str = Field(max_length=400)
    input_schema: dict[str, Any]
    returns: ReturnsSpec
    backing: Literal["deterministic", "llm_backed"]
    policy: PolicyAnnotations = PolicyAnnotations()
    version: int = 1
    deprecated_until: date | None = None

    @model_validator(mode="after")
    def _category_matches(self) -> "SquawkCapability":
        """Validate the category and return-kind-specific requirements.

        Returns:
            The validated capability.

        Raises:
            ValueError: If the category or return specification is inconsistent.
        """
        if self.category != self.cap_id.rsplit(".", 1)[0]:
            raise ValueError("category must match the cap_id prefix")
        if self.returns.kind == "artifact" and self.returns.media_type is None:
            raise ValueError("artifact returns require media_type")
        if self.returns.kind == "inline" and self.returns.schema_ is None:
            raise ValueError("inline returns require schema")
        return self


class CapabilityCategory(BaseModel):
    """Group capability definitions under one independently hashed category."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str = ""
    capabilities: tuple[SquawkCapability, ...]
    hash: str = ""

    @model_validator(mode="after")
    def _fill_hash(self) -> "CapabilityCategory":
        """Recompute the category hash even when a caller supplies one.

        Returns:
            The category with its canonical hash.
        """
        object.__setattr__(self, "hash", category_hash(self))
        return self


class SquawkContract(BaseModel):
    """Represent the versioned set of categories exposed by an agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    major: int = Field(ge=1)
    categories: tuple[CapabilityCategory, ...]

    @property
    def hashes(self) -> dict[str, str]:
        """Return category names mapped to their canonical hashes."""
        return {category.name: category.hash for category in self.categories}


class ContractDelta(BaseModel):
    """Describe contract categories that changed, stayed equal, or disappeared."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    changed: tuple[CapabilityCategory, ...] = ()
    unchanged: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()


def category_hash(category: CapabilityCategory) -> str:
    """Return the canonical SHA-256 hash for a category excluding ``hash``.

    Args:
        category: The category to serialize from its canonical Pydantic model.

    Returns:
        A ``sha256:``-prefixed hexadecimal digest.
    """
    data = category.model_dump(mode="json", exclude={"hash"}, by_alias=True)
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def contract_delta(known: Mapping[str, str], contract: SquawkContract) -> ContractDelta:
    """Partition categories according to their hashes known by a peer.

    Args:
        known: The peer's category names and hashes.
        contract: The current complete contract.

    Returns:
        Changed category definitions, unchanged names, and removed names.
    """
    changed = tuple(category for category in contract.categories if category.hash != known.get(category.name))
    unchanged = tuple(category.name for category in contract.categories if category.hash == known.get(category.name))
    current_names = {category.name for category in contract.categories}
    removed = tuple(name for name in known if name not in current_names)
    return ContractDelta(changed=changed, unchanged=unchanged, removed=removed)
