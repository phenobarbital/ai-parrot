"""Legal domain toolkit package.

Houses the BOE (Boletín Oficial del Estado) integration for the Legal Norms
Graph feature (FEAT-449): identifier utilities, the consolidated-XML parser,
and the ``ExtractDataSource`` implementation used to feed
``OntologyRefreshPipeline``.

Also registers the ``"ontology_legal"`` wiki backend (FEAT-449 M7, R16) at
import time — the read-only FEAT-450 namespace adapter over the legal
ontology tenant. Guarded so this package still imports if the core wiki
plane is unavailable (satellites must degrade gracefully, never hard-fail
on an optional core surface).
"""

try:
    from parrot.knowledge.wiki.store import register_wiki_backend

    from .wiki_store import OntologyLegalWikiStore

    register_wiki_backend("ontology_legal", OntologyLegalWikiStore.factory)
except ImportError:  # pragma: no cover - core wiki plane unavailable
    pass
