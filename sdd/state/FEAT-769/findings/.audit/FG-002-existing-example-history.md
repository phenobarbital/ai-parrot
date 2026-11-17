# FG-002 — The existing example is 3 days old and was already rewritten once by a ledger fix

**Query**: Q013 · **Type**: git_log · **Depth**: 1

## Summary
`examples/semantic/agent_semantic_example.py` was introduced on **2026-10-26** by
`9b2f099c3` — *TASK-4702, "engine-committed coder deliverable"* — as a 261-line file
shipped together with `examples/semantic/README.md` (+15) and its pin
`packages/ai-parrot-semantic/tests/test_example_agent.py` (+84). One day later
`ef85c5035` ("wire real PBAC guard in agent example, scope env and owner checks",
ledger issue `f0da823294fb`) rewrote 173 lines of that 261-line example and grew the
pinning test by 186 lines — i.e. the first cut of the example used a *fake/placeholder*
PBAC guard and unscoped env/owner checks, and a post-merge review caught it. The
companion doc `docs/tools/semantic-layer.md` was corrected the same day by `9a953146d`
("test the doc's own YAML/JSON blocks and align its model format", issue `d01c24f18770`)
because its YAML/JSON model format did not match the shipped loader.
Implication for FEAT-769: the single existing example is both *very recent* and *already
proven to attract correctness bugs*; new examples should be modelled on the post-`ef85c5035`
file (never the original TASK-4702 version), and each new example should ship with its own
pin test in the same `packages/ai-parrot-semantic/tests/` location, since that is the
established and enforced pattern.

## Citations
- `examples/semantic/agent_semantic_example.py` (added, +261) — commit `9b2f099c` (2026-10-26) `feat(semantic-layer): TASK-4702 — engine-committed coder deliverable`
- `examples/semantic/agent_semantic_example.py` (173 lines changed), `examples/semantic/README.md`, `packages/ai-parrot-semantic/tests/test_example_agent.py` (+186) — commit `ef85c503` (2026-10-27) `fix(semantic-layer): wire real PBAC guard in agent example, scope env and owner checks (issue:f0da823294fb)`
- `docs/tools/semantic-layer.md`, `packages/ai-parrot-semantic/tests/test_mcp_local.py` — commit `9a953146` (2026-10-27) `fix(semantic-layer): test the doc's own YAML/JSON blocks and align its model format (issue:d01c24f18770)`
- `packages/ai-parrot-semantic/.mcp.json` — commit `b3b658e6` (2026-10-26) `fix(semantic-layer): TASK-4481 review fixes — .mcp.json mcpServers wrapper`
- `git ls-files examples/semantic` → only `README.md` and `agent_semantic_example.py`; `examples/agents/semantic/` does **not** exist yet.

## Notes
Post-merge corrections to FEAT-704 artefacts arrive through the `/sdd-fix` ledger lane
(`(issue:<id>)` commit suffix), not through new TASK ids.
[cross-lane: type=read, intent=diff the post-`ef85c503` example against the toolkit's real PBAC guard API so new examples copy the *corrected* wiring]
