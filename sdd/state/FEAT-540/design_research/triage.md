# Design research triage — FEAT-540 graphindex-core-seams (v0.4, 2026-10-14)

Model: gpt-5.6-luna (codex-cli 0.160.0, reasoning high). 12 suggestions; every
`affected_paths` entry passed containment + existence checks. Factual spot checks:
S7 `intent.py:176` uses `llm.completion` (true); S8 `embed.py:193` `_persist_to_pgvector`
is a stub (true); S10 `wiki/toolkit.py:139-161` selects the source backend and
`sources.py` has 25 `backend ==` branches (true); S3 `loader.py:44` `_NullPersistence` (true);
S1's "analytics eagerly imported by `graphindex/__init__`" is imprecise (analytics is imported
by `builder.py:28`; `__init__` eagerly imports communities/export_html/signals/persist_sqlite/
projection/sqlite_reader/odoo_code) — substance holds.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Split pure core from framework adapters before enforcing ceilings (architecture) | CONFIRM | PEP 562 alone cannot meet G2; graphindex/__init__ eager exports added to M1 | §3 M1, M2, M6 |
| S2 | Behavioural persistence contract (architecture) | CONFIRM | semantics written into GraphPersistence + conformance suite | §2, §3 M7, §4 |
| S3 | One registry as the only composition root incl. null/Arango (architecture) | CONFIRM | null backend registered; 7 dispatch sites consolidated | §2 backends.py, §3 M7 |
| S4 | Replace Arango-named TenantContext fields (api) | ESCALATE | cross-cutting hard cut; better with FEAT-670's mapping | §8 Q1 |
| S5 | Typed ops + dialect-bound dynamic escape hatch (api) | CONFIRM | OntologyTraversalStore + DynamicQuery + fail-closed validate_query | §2, §3 M8 |
| S6 | GraphIndex persistence over a document/edge adapter (architecture) | CONFIRM | GraphDocumentStore vs OntologyTraversalStore split | §2, §3 M7/M8 |
| S7 | Reconcile LLM Protocol with `completion` callers (api) | CONFIRM (scoped) | ontology resolver stays on AbstractClient; ProviderNotAvailable distinction adopted | §3 M2, §6 |
| S8 | Durable embedding writes behind persistence capabilities (architecture) | CONFIRM | EmbeddingPersistence; pgvector stub removed from embedder | §2, §3 M2/M7 |
| S9 | pin.py explicit SQLite boundary (risk) | CONFIRM | guard now, capability deferred | §3 M7, §8 Q4 |
| S10 | Source-collection manager as injected backend (architecture) | CONFIRM | SourceManifestBackend + registry | §2, §3 M7 |
| S11 | Transport descriptors from one operation registry (api) | CONFIRM | fingerprints + duplicate checks + golden manifests | §2, §3 M5 |
| S12 | Behavioural contract/import tests (testing) | CONFIRM | conformance matrix, reopen tests, blocked-package probes | §4 |

Summary: 11 confirmed (one scoped) · 0 rejected · 1 escalated.
