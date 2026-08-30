# TASK-2603: Agent metadata as MCP resources

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2602
**Assigned-to**: unassigned

---

## Context

Implements the resources half of spec §3 **Module 2**, resolving spec **OQ8**.

Exactly **three** resources are served: an identity card, a policy-filtered tool catalog,
and KB descriptors. The system prompt, `backstory` and `rationale` are **excluded
outright** — never served, not policy-gated. Publishing guardrail wording hands an
attacker the bypass design.

> Note: the brainstorm's prose says "four resources" but enumerates three. OQ8's later
> revision is authoritative: **three**.

---

## Scope

- Register three MCP resources per agent on its `StreamableHttpMCPServer`:
  - **identity card** — `name`, `role`, `goal`, `capabilities`, description (the same
    fields A2A publishes in its `AgentCard`)
  - **tool catalog** — a browsable manifest of the tools **this principal** may call,
    filtered by the same policy as `tools/list`
  - **KB descriptors** — which knowledge bases the agent consults
- Enforce the hard exclusion: `resources/list` must not advertise, and `resources/read`
  must not serve, the system prompt / `backstory` / `rationale`.
- Unit tests, including the merge-blocking exclusion assertion.

**NOT in scope**: the policy engine itself (TASK-2605) — consume the filter hook it
exposes, or a stub if 2605 is not yet done.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/agent_resources.py` | CREATE | The three resource builders |
| `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py` | MODIFY | Register resources per agent |
| `packages/ai-parrot-server/tests/mcp/test_agent_resources.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31.

### Verified Imports
```python
from parrot.mcp.transports.base import RemoteMCPServerBase
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/transports/base.py
class RemoteMCPServerBase(_CoreMCPServerBase):                       # :18
    def register_resource(self, resource, read_handler)              # :49
    async def handle_resources_list(self, params) -> dict[str, Any]  # :86
    async def handle_resources_read(self, params) -> dict[str, Any]  # :93

# packages/ai-parrot/src/parrot/bots/abstract.py
self.tool_manager: ToolManager = ToolManager(...)                    # :386
self.knowledge_bases: List[AbstractKnowledgeBase] = []               # :554   <-- KB descriptors source

# packages/ai-parrot-server/src/parrot/a2a/server.py
def get_agent_card(self) -> AgentCard                                # :334   identity-card field precedent
def _tool_to_skill(self, tool) -> Optional[AgentSkill]               # :425   uses args_schema.model_json_schema()
```

### Does NOT Exist
- ~~A resource that serves the agent's system prompt~~ — and you must NOT create one.
- ~~`AbstractBot.system_prompt` as a safe public field~~ — `backstory` / `rationale` /
  the assembled prompt exist on the agent but are a **hard exclusion** here.
- ~~`MCPAgentManifest`~~ — a prior draft's model; does not exist.

---

## Implementation Notes

### Key Constraints
- The exclusion is enforced by an **allowlist**, not a denylist: build each resource from
  an explicit field list so a future agent attribute cannot leak in by default.
- The tool catalog is policy-filtered — same decision path as `tools/list`, so a principal
  never sees a tool in the catalog that `tools/list` hides.
- Async throughout; `self.logger` on resource reads.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/a2a/server.py:334` — which agent fields are already
  considered publishable

---

## Acceptance Criteria

- [ ] Exactly three resources are advertised per agent
- [ ] Identity card carries `name`, `role`, `goal`, `capabilities`, description
- [ ] Tool catalog is filtered by the caller's policy
- [ ] KB descriptors are built from `AbstractBot.knowledge_bases` (`:554`)
- [ ] **OQ8 invariant**: `backstory`, `rationale` and the assembled system prompt appear in
      neither `resources/list` nor `resources/read` (merge blocker)
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/mcp/test_agent_resources.py -v`
- [ ] No linting errors

---

## Test Specification

```python
class TestAgentResources:
    async def test_three_resources_advertised(self, server):
        listed = await server.handle_resources_list({})
        assert len(listed["resources"]) == 3

    async def test_identity_card_fields(self, server):
        card = await server.handle_resources_read({"uri": "agent://finance/identity"})
        assert {"name", "role", "goal", "capabilities"} <= set(card)

    async def test_resources_exclude_system_prompt(self, server, agent):
        """OQ8 INVARIANT — merge blocker."""
        listed = await server.handle_resources_list({})
        blob = json.dumps(listed)
        for banned in ("backstory", "rationale", "system_prompt"):
            assert banned not in blob
        for uri in [r["uri"] for r in listed["resources"]]:
            body = json.dumps(await server.handle_resources_read({"uri": uri}))
            assert agent.backstory not in body
            assert agent.rationale not in body

    async def test_tool_catalog_is_policy_filtered(self, server, denied_principal):
        cat = await server.handle_resources_read({"uri": "agent://finance/tools"})
        assert "restricted_tool" not in json.dumps(cat)

    async def test_kb_descriptors_from_knowledge_bases(self, server, agent):
        kbs = await server.handle_resources_read({"uri": "agent://finance/kbs"})
        assert len(kbs["knowledge_bases"]) == len(agent.knowledge_bases)
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 2 and OQ8 in §8.
2. **Check dependencies** — TASK-2602 completed.
3. **Verify the Codebase Contract**. 4. **Update status** → `"in-progress"`.
5. **Implement** — allowlist, never denylist. 6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
