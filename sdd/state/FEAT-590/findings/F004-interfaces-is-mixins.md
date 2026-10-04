---
id: F004
query_id: Q004
type: read
intent: Verify parrot.interfaces convention for placing ToolCallDelegate protocol
executed_at: 2026-09-21T22:08:00Z
depth: 0
parent_id: null
---

# F004 — parrot.interfaces is a mixins package, NOT a contracts home

## Summary

`parrot/interfaces/` is documented as "Mixins for bot functionality" — connection/capability interfaces (aws.py, database.py, http.py, google.py, vector.py, etc.). The proposal places ToolCallDelegate at `parrot/interfaces/delegate.py`, which breaks this convention. A prior finding (F012, FEAT-449) established the same conclusion. Better location: `parrot/bots/flows/plan/delegate.py` (co-locate with the module it extends) or a new subpackage `plan/delegate/`.

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
    documentdb.py  file/  flowtask.py  google.py  hierarchy.py  http.py
    images/  jira/  o365.py  obsidian/  odoointerface.py  onedrive.py
    rss.py  sharepoint.py  soap.py  tools.py  vector.py  zammad.py

- path: `sdd/state/FEAT-449/findings/F012-contracts-home.md`
  excerpt: |
    parrot.interfaces exists but is a mixins package, not a Pydantic-contracts home.

## Notes

The proposal's `parrot/interfaces/delegate.py` path should be relocated. Options: (a) `parrot/bots/flows/plan/delegate.py` — natural home since it extends the plan execution model; (b) `parrot/bots/flows/plan/delegate/` subpackage if backends warrant separate files; (c) a `parrot/delegate/` top-level package (mirrors the `parrot/skills/` pattern). Option (a) is simplest and follows how PlanToolNode lives in `plan/node.py`.
