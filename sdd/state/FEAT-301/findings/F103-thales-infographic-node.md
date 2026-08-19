---
id: F103
query: Q107
type: code_analysis
confidence: high
---
# F103: Thales InfographicNode (FEAT-425) Impact

**File**: `packages/ai-parrot/src/parrot/flows/thales/nodes/infographic.py`

`InfographicNode` delegates to `InfographicToolkit.render_template()` with
the `crew_report` template name. It is **block-type-agnostic** — it passes
structured data (executive_summary + decks) and the toolkit resolves the
template, which determines which block types appear in the response.

New block types are **transparent** to this node. The only requirement:
- Templates used by Thales produce valid `InfographicResponse` blocks
- The HTML renderer can render them

No changes to `InfographicNode` are required for FEAT-301.

**Graceful degradation**: The node wraps rendering in try/except and returns
`None` on failure (spec G7). This means even if a new block type has a
rendering bug, it won't crash the Thales flow.
