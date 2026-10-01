---
id: F001
query_id: Q001
type: wiki_query
intent: locate OdooToolkit and prior Odoo SDD artifacts
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F001 — OdooToolkit location and prior Odoo SDD artifacts

## Summary

Wiki ranks `parrot_tools/odoo/__init__.py` (score 1.00) and the `parrot_tools/odoo` directory as the toolkit home. Prior Odoo SDD artifacts exist: the FEAT-216 `odoo-fieldservice-toolkit` proposal + spec (subclass precedent), `evaluate-odoo-mcp-toolkit`, `odoo-interface`, `odoo-pageindex-documentation-agent` specs, and the brand-new FEAT-614 `odoo-json2-domain-first-methods` spec (2026-09-30). No helpdesk-related Odoo artifact exists yet.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py`
  wiki_page_id: file:packages/ai-parrot-tools/src/parrot_tools/odoo/__init__.py
  symbol: `OdooToolkit` (re-export)
- path: `sdd/proposals/odoo-fieldservice-toolkit.proposal.md`
  wiki_page_id: file:sdd/proposals/odoo-fieldservice-toolkit.proposal.md
- path: `sdd/specs/odoo-fieldservice-toolkit.spec.md`
- path: `sdd/specs/odoo-json2-domain-first-methods.spec.md`
- path: `sdd/state/FEAT-216/findings/F001-odoo-toolkit-structure.md`
  wiki_page_id: file:sdd/state/FEAT-216/findings/F001-odoo-toolkit-structure.md

## Notes

`sdd/tasks/index/` has no `odoo-fieldservice-toolkit.json` and `parrot_tools/odoo/` has no `fieldservice.py`: FEAT-216 was approved but never decomposed/implemented (see F007).
