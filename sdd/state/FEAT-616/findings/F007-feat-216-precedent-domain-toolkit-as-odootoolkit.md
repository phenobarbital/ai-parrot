---
id: F007
query_id: Q007
type: read
intent: FEAT-216 fieldservice precedent
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F007 — FEAT-216 precedent: domain toolkit as OdooToolkit subclass (never implemented)

## Summary

FEAT-216 (`OdooFieldServiceToolkit`, approved 2026-06-02) resolved the same fork this request leaves open: *subclass `OdooToolkit`*, expose all inherited tools, reuse `_execute`, add entities/inputs/envelopes to the three model modules, gate writes with `@requires_permission`, extend `_DEFAULT_KNOWN_MODELS`, and rely on `AbstractToolkit.get_tools()` reflection so new `async def` methods auto-register as `odoo_<name>` tools. Mixin/composition and `get_tools_filtered` narrowing were considered and rejected. The spec was never decomposed (no per-spec index, no `fieldservice.py`).

## Citations

- path: `sdd/specs/odoo-fieldservice-toolkit.spec.md`
  lines: 60-120
  symbol: §2 Architectural Design
  excerpt: |
    `OdooFieldServiceToolkit(OdooToolkit)` is a subclass that adds 8 `async`
    methods, each decorated with `@tool_schema(<Input>)` (and `@requires_permission`
    where it writes). Because `AbstractToolkit.get_tools()` discovers tools by
    runtime reflection over `async def` instance methods, the subclass
    **automatically registers its new methods as tools and inherits all parent tools**
- path: `sdd/specs/odoo-fieldservice-toolkit.spec.md`
  lines: 120-200
  symbol: §2 Data Models (entities / inputs / envelopes split)
- path: `sdd/proposals/odoo-fieldservice-toolkit.proposal.md`
  lines: 211-222
  symbol: §5 Resolved — "Subclass vs. compose, and tool surface?"
- path: `sdd/proposals/odoo-fieldservice-toolkit.proposal.md`
  lines: 85-96
  symbol: `SqlToolkit(DatabaseToolkit)` precedent

## Notes

Decision precedent is directly reusable; the FEAT-216 design was validated by review but has no runtime evidence.
