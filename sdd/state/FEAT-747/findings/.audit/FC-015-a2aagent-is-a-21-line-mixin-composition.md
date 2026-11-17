---
id: FC-015
query_id: Q039
type: read
intent: "Read bots/a2a_agent.py: how a parrot agent is exposed/consumed via A2A today (closest inter-agent surface)."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-015 — A2AAgent is a 21-line mixin composition over A2AEnabledMixin

## Summary

`bots/a2a_agent.py` composes `BasicAgent` with `parrot.a2a.server.A2AEnabledMixin`; `configure()` calls `setup_a2a(app, url)` to expose the agent over HTTP A2A. Consumption of remote A2A agents is via `ToolManager.register_a2a_agent` (FC-014). Q038 (tree of `parrot/a2a`, server `parrot/a2a`, integrations `a2a`) was **skipped** (budget).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/a2a_agent.py`
  lines: 1-21
  symbol: `A2AAgent`
  excerpt: |
    from ..a2a.server import A2AEnabledMixin
    class A2AAgent(BasicAgent, A2AEnabledMixin):
        def __init__(self, app: web.Application, url: str, *args, **kwargs):
        async def configure(self):
            await super().configure()
            self.setup_a2a(self.app, self.url)


## Notes

Q038 skipped: files_read budget reserved for Matrix crew reads. `[cross-lane: type=wiki_page, intent=parrot.a2a package layout (client, server, mesh router) — FW-009 covers]`. Tests observed under Q042: `tests/test_a2a_v1_mesh_router.py`, `test_a2a_tools.py`, `test_a2a_v1_client.py`, `ai-parrot-server/tests/unit/test_a2a_identity.py`, `test_a2a_credential_gate.py`, `tests/integration/events/test_a2a_trace_propagation.py`.
