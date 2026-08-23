---
id: F012
query_id: Q014
type: tree
intent: Check whether parrot.interfaces exists as a home for the proposed parrot.interfaces.legal contracts
executed_at: 2026-08-23T00:22:57Z
depth: 0
parent_id: null
---

# F012 — parrot.interfaces exists but is a mixins package, not a Pydantic-contracts home

## Summary

`parrot/interfaces/` is real, but its own docstring defines it as "Mixins for bot
functionality" — classes providing behaviour to bots through multiple inheritance, with heavy
ones lazy-loaded. Its contents are connection/capability interfaces (`aws.py`, `database.py`,
`http.py`, `google.py`, `vector.py`, `soap.py`, `o365.py`…), not domain data models. Placing
`CaseRef` / `CendojVerification` / `LegalAnswer` at `parrot.interfaces.legal`, as the source
tentatively proposes with an `[assumed]` marker, would break that convention.

## Citations

- path: `packages/ai-parrot/src/parrot/interfaces/__init__.py`
  lines: 1-9
  excerpt: |
    """
    Interfaces package - Mixins for bot functionality.

    This package contains interface classes that provide specific functionality
    to bot implementations through multiple inheritance.

    Heavy interfaces (ToolInterface, VectorInterface) are lazy-loaded to avoid
    pulling in all LLM client dependencies at import time.
    """

- path: `packages/ai-parrot/src/parrot/interfaces/`
  excerpt: |
    aws.py  credentials.py  database.py  dataframes.py  doc_converter.py
    documentdb.py  file  flowtask.py  google.py  hierarchy.py  http.py
    images  o365.py  obsidian  odoointerface.py  onedrive.py  rss.py
    sharepoint.py  soap.py  tools.py  vector.py  zammad.py

- path: `packages/ai-parrot-tools/src/parrot_tools/interfaces/`
  excerpt: |
    # parrot_tools has its own interfaces/ subtree (e.g. workday/parsers/)
    # — the per-toolkit convention for source-specific models

## Notes

The source's own layout proposal (`parrot_tools/legal/cendoj/models.py` +
`parrot_tools/legal/ids.py`) is the convention-consistent option and is corroborated by
`parrot_tools/interfaces/workday/parsers/` as a per-toolkit model home.
