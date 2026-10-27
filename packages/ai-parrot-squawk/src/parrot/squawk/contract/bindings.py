"""Serving-side bindings: which tool (or LLM-backed runner) serves each capability; contract assembly + version rules."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, model_validator

from parrot.interagent import CAP_ID_PATTERN, CapabilityCategory, SquawkCapability, SquawkContract


class LLMBackedSpec(BaseModel):
    """Typed in, structured out; tools restricted to contract capabilities (D9)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    system_prompt: str
    output_schema: dict[str, Any]
    tool_allowlist: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _allowlist_is_cap_ids(self) -> LLMBackedSpec:
        bad = [t for t in self.tool_allowlist if not re.match(CAP_ID_PATTERN, t)]
        if bad:
            raise ValueError(f"tool_allowlist must contain cap_ids, got {bad}")
        return self


class CapabilityBinding(BaseModel):
    """Binds a SquawkCapability to either a local tool name or an LLMBackedSpec."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: SquawkCapability
    tool_name: str | None = None
    llm_backed: LLMBackedSpec | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> CapabilityBinding:
        if self.capability.backing == "deterministic":
            if not self.tool_name or self.llm_backed is not None:
                raise ValueError("deterministic capability requires tool_name set and llm_backed None")
        elif self.capability.backing == "llm_backed":
            if self.tool_name is not None or self.llm_backed is None:
                raise ValueError("llm_backed capability requires llm_backed set and tool_name None")
        else:
            raise ValueError(f"unknown backing mode: {self.capability.backing}")
        return self


def build_contract(bindings: Sequence[CapabilityBinding], *, agent_id: str, major: int = 1) -> SquawkContract:
    """Group by category (hashes computed by CapabilityCategory); duplicate cap_id ⇒ ValueError."""
    seen: set[str] = set()
    groups: dict[str, list[SquawkCapability]] = defaultdict(list)
    for b in bindings:
        if b.capability.cap_id in seen:
            raise ValueError(f"duplicate cap_id {b.capability.cap_id}")
        seen.add(b.capability.cap_id)
        groups[b.capability.category].append(b.capability)
    cats = tuple(
        CapabilityCategory(name=n, capabilities=tuple(sorted(c, key=lambda x: x.cap_id)))
        for n, c in sorted(groups.items())
    )
    return SquawkContract(agent_id=agent_id, major=major, categories=cats)


def check_version_rules(previous: SquawkContract, candidate: SquawkContract) -> list[str]:
    """Violations of D8 versioning: removals / type changes need a major bump + deprecated_until; additions do not."""
    violations: list[str] = []

    prev_caps: dict[str, SquawkCapability] = {}
    for cat in previous.categories:
        for cap in cat.capabilities:
            prev_caps[cap.cap_id] = cap

    cand_caps: dict[str, SquawkCapability] = {}
    for cat in candidate.categories:
        for cap in cat.capabilities:
            cand_caps[cap.cap_id] = cap

    is_major_bump = candidate.major > previous.major

    # Check for removed capabilities
    removed_ids = set(prev_caps.keys()) - set(cand_caps.keys())
    if removed_ids:
        if not is_major_bump:
            violations.append(
                f"Capabilities removed without major version bump (prev={previous.major}, cand={candidate.major}): "
                + ", ".join(sorted(removed_ids))
            )
        else:
            # Major bump occurred: removed capabilities in previous contract must have deprecated_until set
            unannounced = [cap_id for cap_id in removed_ids if prev_caps[cap_id].deprecated_until is None]
            if unannounced:
                violations.append(
                    "Removed capabilities lacked deprecated_until in previous contract: "
                    + ", ".join(sorted(unannounced))
                )

    # Check for modified capabilities (input_schema or returns changed)
    shared_ids = set(prev_caps.keys()) & set(cand_caps.keys())
    for cap_id in sorted(shared_ids):
        p_cap = prev_caps[cap_id]
        c_cap = cand_caps[cap_id]
        if p_cap.input_schema != c_cap.input_schema or p_cap.returns != c_cap.returns:
            if not is_major_bump:
                violations.append(
                    f"Capability '{cap_id}' schema or return type changed without major version bump"
                )

    return violations
