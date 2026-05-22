"""Knowledge sources for the helpdesk orchestrator example.

Two retrieval surfaces are exposed:

- :func:`pageindex_lookup` — hierarchical (tree) retrieval against the
  training manuals under :file:`knowledge/manuals/`.
- :func:`handbook_search` — flat semantic retrieval against the handbooks
  under :file:`knowledge/handbooks/`.

Both tools attempt the real backend (PageIndex / FAISS) when the
corresponding index has been built by :file:`knowledge/ingest.py`, and
fall back to a simple in-memory substring scan when not — keeping the
example runnable without any external dependencies.
"""
from examples.orchestrator.knowledge.retrieval import (
    handbook_search,
    pageindex_lookup,
)

__all__ = ["pageindex_lookup", "handbook_search"]
