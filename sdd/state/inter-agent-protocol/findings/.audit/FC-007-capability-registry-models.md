---
id: FC-007
query_id: [Q024]
type: read
intent: "Follow-up: parrot/registry/capabilities — is it a contract/capability catalog reusable for the protocol's contract?"
executed_at: 2026-10-25T22:44:44Z
duration_ms: 0
parent_id: FC-006
depth: 1
---

# FC-007 — registry/capabilities is the FEAT-070 intent-router index (name, description, resource_type, embedding), not a typed remote contract

## Summary

`parrot/registry/capabilities/models.py` (238 lines) defines `ResourceType`, `RoutingType`, `CapabilityEntry(name, description, resource_type, embedding, metadata, not_for)`, `RouterCandidate`, `RoutingDecision`, `TraceEntry`, `RoutingTrace`, `IntentRouterConfig`. It routes a user intent to local resources (tools, stores) by lexical/embedding similarity. It has no typed input/output schema, versioning/hash, policy annotations or backing field — the brainstorm's `Capability` (cap_id, category, typed input/output, returns, backing, policy annotations) is a different, richer object. The name collision ("capability") is worth avoiding or reconciling in the spec.

## Citations

- path: `packages/ai-parrot/src/parrot/registry/capabilities/models.py`
  lines: 1-5
  symbol: module docstring
  excerpt: |
    """Pydantic v2 models for Intent Router and Capability Registry.
    Defines all enums and data models for the FEAT-070 intent routing feature:
- path: `packages/ai-parrot/src/parrot/registry/capabilities/models.py`
  lines: 48-69
  symbol: `CapabilityEntry`
  excerpt: |
    class CapabilityEntry(BaseModel):
        name: str = Field(..., description="Unique name of the capability")
        description: str = Field(
        resource_type: ResourceType
        embedding: Optional[list[float]] = Field(
        metadata: dict[str, Any] = Field(default_factory=dict)
        not_for: list[str] = Field(
- path: `packages/ai-parrot/src/parrot/registry/capabilities/models.py`
  lines: 25-35
  symbol: `ResourceType`, `RoutingType`
- path: `packages/ai-parrot/src/parrot/registry/capabilities/models.py`
  lines: 91-106
  symbol: `RoutingDecision`
- path: `packages/ai-parrot/src/parrot/registry/capabilities/registry.py`
  lines: 1
  symbol: (capability registry module — not read)

## Notes

Only models.py was read; registry.py in the same package was not opened (budget).
