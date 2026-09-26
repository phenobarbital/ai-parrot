---
id: F001
query_id: Q001
type: wiki_query
intent: Locate the existing Google services client and any Drive-specific code
executed_at: 2026-09-25T22:52:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# F001 — No Drive-specific module exists; the only Google plumbing is `GoogleClient`

## Summary

`wikitoolkit query "google drive client interface"` returns the generic Google
services client and the Workspace tool base, but **no** page for a Drive
manager, Drive tool, or Drive loader. The FEAT-603 spec page also ranks (score
0.11) as the only file-manager precedent. Absence is the finding: Drive support
must be built, and the existing client is the auth/transport seam to reuse.

## Citations

- path: `packages/ai-parrot/src/parrot/interfaces/google.py`
  wiki_page_id: file:packages/ai-parrot/src/parrot/interfaces/google.py
  score: 0.46
  symbol: `GoogleClient`
  excerpt: |
    Google Services Client for AI-Parrot. (async-only, aiogoogle)

- path: `packages/ai-parrot-tools/src/parrot_tools/google/base.py`
  wiki_page_id: file:packages/ai-parrot-tools/src/parrot_tools/google/base.py
  symbol: `GoogleBaseTool`
  excerpt: |
    Base classes for Google Workspace tools.

- path: `examples/clients/google_client_example.py`
  wiki_page_id: file:examples/clients/google_client_example.py
  score: 1.00
  lines: 32-41
  excerpt: |
    scopes=["drive"],   # example only exercises scope resolution, no Drive calls

- path: `sdd/specs/sharepoint-filemanager.spec.md`
  wiki_page_id: file:sdd/specs/sharepoint-filemanager.spec.md
  score: 0.11
  excerpt: |
    Feature Specification: SharePoint & OneDrive FileManager (FEAT-603)

## Notes

Ledger issue `3daf42eb6bec` (FEAT-603 AC2 does not account for the
`client_class` override) surfaced in the same query — relevant when mirroring
AC2 for the Drive manager (see F008).
