---
id: F010
query_id: Q006
type: read
intent: Identify the closest in-repo precedent for a grounded, read-only, citation-audited advisory agent
executed_at: 2026-08-23T00:22:57Z
depth: 1
parent_id: F006
---

# F010 — SecurityAdvisor is a working end-to-end precedent for the entire LegalAnswerAgent pattern

## Summary

`agents/security_advisor.py` already implements, in production, nearly every element the
source proposes for §4–§5: a read-only agent with a hard "never writes" invariant; two
knowledge bases mounted as tools — a PgVector KB via `VectorStoreSearchTool` and a GraphIndex
graph via `GraphMemoryMixin` exposing `find_node`/`traverse`/`ground_claim`; structured
Pydantic outputs whose `references` list is **mandatory**; and `_audit_citations`, which
re-queries the KB and marks `validated=True` only when a cited source actually appears in the
retrieved corpus, routing failures to human review instead of automated action. That is
functionally the source's `verified` vs `pending_verification` gate, already built. A second
precedent, `parrot/flows/thales/`, does structured research citations over a flow.

## Citations

- path: `agents/security_advisor.py`
  lines: 1-27
  excerpt: |
    """SecurityAdvisor v2 — grounded, read-only security advisory agent.
    1. **Knowledge grounding** — two knowledge bases mounted as tools:
       - Remediation KB (PgVector) via ``VectorStoreSearchTool``
       - Compliance graph (GraphIndex, SQLite plane) via ``GraphMemoryMixin``
         Exposes ``find_node`` / ``traverse`` / ``ground_claim`` etc. as tools.
    2. **Structured, citation-audited outputs** — every LLM-produced
       recommendation is a Pydantic ``RemediationItem`` whose ``references``
       list is mandatory; citations are re-checked against the remediation
       KB (``_audit_citations``) and unvalidated items are routed to human
       review instead of Jira.

- path: `agents/security_advisor.py`
  lines: 424-433
  symbol: `_audit_citations`
  excerpt: |
    async def _audit_citations(self, report: RemediationReport) -> RemediationReport:
        """Re-query the remediation KB and validate every citation.

        For each item, runs a fresh similarity search on the item's title
        and marks ``validated=True`` only when at least one cited
        ``source`` actually appears in the retrieved corpus. Items that
        fail the audit keep ``validated=False`` and are excluded from
        automated Jira creation (human review instead).

- path: `agents/security_advisor.py`
  lines: 34-35
  excerpt: |
    NOTE: This file lives in ``agents/``, which is gitignored. Commit with
    ``git add -f``

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/mixin.py`
  lines: 30
  symbol: `GraphMemoryMixin`

- path: `examples/knowledge_wiki/wiki.py`
  lines: 1-24
  excerpt: |
    """LLM Wiki — composing PageIndex + GraphIndex + Ontology into a knowledge repo.
    the knowledge   GraphIndex graph (``rustworkx`` + FAISS) that the LLM grows
    graph           via the *write* tools of :class:`GraphIndexToolkit`
    entity layer    Ontology (:class:`OntologyRAGMixin`) — structured entities,
                    optional, degrades gracefully without ArangoDB

- path: `packages/ai-parrot/src/parrot/flows/thales/factories.py`
  excerpt: |
    Research agent & node factories for the "Thales" research flow (FEAT-425).

## Notes

`examples/knowledge_wiki/wiki.py` is the closest thing to the source's "LLM Wiki" framing and
notes the Ontology layer "degrades gracefully without ArangoDB" — i.e. GraphIndex runs on a
SQLite plane too, which matters for the spike environment.
