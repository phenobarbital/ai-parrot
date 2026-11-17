---
id: F015
query_id: Q015
type: wiki_query
intent: "Orient on the subsystems the proposal touches via the knowledge graph before raw reads"
executed_at: 2026-10-25T10:02:00Z
duration_ms: 12000
parent_id: null
depth: 0
---

# F015 — Wiki orientation: governance primitives (RLS, PBAC, audit) and PyO3 packaging are documented; no `parrot.semantic` exists on dev

## Summary

Seven `wikitoolkit query` calls. "semantic layer satellite" returns only SDD artifacts (TASK-4463 score 1.00, spec, brainstorm, index) — no code page, confirming the satellite is absent from `dev`. RLS lives in `dataset_manager/sources/rls.py` and `authorizing.py` (`AuthorizingDataSource._apply_rls`, score 0.84); PBAC dataset filtering in `dataset_manager/tool.py::DatasetManager.get_tools_filtered` (0.76) with `pbac-datasetmanager-policy.spec.md`; the credential `AuditLedger` is `parrot.security.audit_ledger` (`parrot/auth/audit.py` is a deprecated alias, 0.80); the Ibis NO-GO is TASK-1437/1438 under `dataset_manager/spatial/`; Rust/PyO3 precedents are FEAT-528 finding F004 (1.00), `packages/navrules/rust/Cargo.toml` (0.92), TASK-1955 `parrot_codec` (0.84), `yaml-rs` (0.69).

## Citations

- path: `sdd/tasks/active/TASK-4463-semantic-distribution-skeleton.md`
  lines: 1
  symbol: wiki `file:sdd/tasks/active/TASK-4463-semantic-distribution-skeleton.md`
  wiki_page_id: file:sdd/tasks/active/TASK-4463-semantic-distribution-skeleton.md
  excerpt: |
    score=1.00 — only SDD docs match "semantic layer satellite parrot.semantic package"; no code page.

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`
  lines: 1
  symbol: `AuthorizingDataSource._apply_rls`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py#AuthorizingDataSource._apply_rls
  excerpt: |
    Return a request-scoped copy of the inner source with RLS applied. (score=0.84)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/rls.py`
  lines: 1
  symbol: RLS Predicate Injection (FEAT-228)
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/rls.py
  excerpt: |
    RLS Predicate Injection for FEAT-228 Data-Plane Authorization. (score=0.73)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 1
  symbol: `DatasetManager.get_tools_filtered`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager.get_tools_filtered
  excerpt: |
    Filter toolkit tools by resolver and then by dataset policy. (score=0.76)

- path: `packages/ai-parrot/src/parrot/auth/audit.py`
  lines: 1
  symbol: deprecated alias of `parrot.security.audit_ledger`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/audit.py
  excerpt: |
    DEPRECATED: Use ``parrot.security.audit_ledger`` instead. (score=0.80)

- path: `sdd/state/FEAT-528/findings/F004-local-mcp-and-rust-packaging.md`
  lines: 1
  symbol: PyO3 packaging precedent
  wiki_page_id: file:sdd/state/FEAT-528/findings/F004-local-mcp-and-rust-packaging.md
  excerpt: |
    Local MCP exposure and PyO3 packaging already exist (score=1.00)

- path: `sdd/tasks/completed/TASK-1955-rust-codec-extension.md`
  lines: 1
  symbol: `parrot_codec` maturin extension
  wiki_page_id: file:sdd/tasks/completed/TASK-1955-rust-codec-extension.md
  excerpt: |
    Optional Rust `parrot_codec` extension + maturin `python-source` fix (score=0.84)

## Notes

Wiki queries are free against the budget. Follow-up `wikitoolkit page` calls: TASK-1437 (F010) and FEAT-528 F004 (F012).
