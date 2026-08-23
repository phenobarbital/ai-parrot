---
id: F001
query_id: Q001
type: grep
intent: Confirm GraphIndexToolkit exists and enumerate its real tool names vs the claimed ground_claim/traverse/find_references
executed_at: 2026-08-23T00:20:22Z
depth: 0
parent_id: null
---

# F001 — GraphIndexToolkit exists; all three claimed tools confirmed, plus a gated write API

## Summary

`GraphIndexToolkit` is real and is a large `AbstractToolkit` (~1500 lines, ~30 agent-facing
tools). All three tools named in the source's reuse inventory — `ground_claim`, `traverse`,
`find_references` — exist with those exact names. The toolkit additionally splits read tools
from write tools (`create_node`, `link_nodes`, `merge_nodes`) behind a `_write_supported`
gate plus `graph_history`/`revert_write`, which directly supports the source's §1.6
"read-only agents / writers separate" principle without new machinery.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 72
  symbol: `GraphIndexToolkit`
  excerpt: |
    class GraphIndexToolkit(AbstractToolkit):

- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 1168
  symbol: `ground_claim`
  excerpt: |
    async def ground_claim(self, claim: str) -> dict:

- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 373
  symbol: `traverse`

- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 293
  symbol: `find_references`

- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 154-166
  symbol: `_write_supported`, `_no_write_error`
  excerpt: |
    def _write_supported(self) -> bool:
    def _no_write_error(self, op: str) -> dict:

- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 1116-1167
  symbol: `graph_history`, `revert_write`

## Notes

Read/write separation is enforced inside one toolkit, not by mounting two toolkits. The
source's §1.6 assumes separate writer/reader toolkits; the existing gate is an alternative
that may satisfy the same invariant.
