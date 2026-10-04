---
id: F027
query_id: Q027
type: git_log
intent: Churn in knowledge/contracts, knowledge/ontology, knowledge/pageindex (60 days) — hot or quiet, in-flight refactors
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F027 — contracts is hot (a FEAT-539 burst on 2026-09-09/10), ontology is warm, pageindex is quiet

## Summary
There are 34 commits in 60 days. By directory: contracts 20, ontology 12, pageindex 2. Almost all of contracts landed in one day, 2026-09-09: the FEAT-539 contracts-card-ontology rollout (TASK-3025 through TASK-3040) plus fixes, ending with black formatting on 2026-09-10. Ontology churn came from FEAT-449 (legal-norms-graph-boe and legal-librarian-answer-layer, 2026-08-23/27) and graphindex Arango work (2026-08-10/16). Nothing has touched any of the three directories since 2026-09-10.

## Citations
- 95903557ac 2026-09-10 Jesus Lara — style: apply black formatting (post sdd-worker)
- 341d569195 2026-09-09 Jesus Lara — fix(contracts): make the demo agent answer end to end on real documents
- 6d4ba9cdd3 2026-09-09 Jesus — Merge feat-FEAT-539-contracts-card-ontology into feat-FEAT-539-contracts-o365-delta
- 7c61386ba9 2026-09-09 Jesus — fix(contracts): resolve deferred TASK-3054 review defects
- 77a6ddde21 2026-09-09 Jesus — fix(contracts): close the cross-source dedup hole, and finish the delta lane
- 0e99514bab .. 86b18068d3 2026-09-09 Jesus — feat(contracts-card-ontology): TASK-3025..TASK-3040 (15 commits: models, PG schema, catalog protocol, extraction, assembly, evidence storage, ingestion, verification, ontology vocabulary, ContractCard datasource, reconciliation, GraphIndex temporal publisher, relation judgements)
- b82deb77fe 2026-09-06 Jesus Lara — new epub and mobi reader for wikitoolkit and bookstore
- 4e6d8eb98d / a9378d2a42 / c8fa31da67 / e5f23ec002 2026-08-27 Jesus Lara — legal-librarian-answer-layer (FEAT-449): legal ontology v1.1 view, declarative ArangoSearch views in the ontology schema
- 9b398d907b / 58790db1c7 / fac5e3f0bb / 6478ec5fd3 2026-08-23 Jesus Lara — legal-norms-graph-boe: article_in_force TraversalPattern, legal.ontology.yaml
- 7fd6367ee9 2026-08-17 phenobarbital — Merge PR #1163 feat-425-agentcrew-tales-research
- b312160efa 2026-08-16 Claude — feat(graphindex): ArangoDB implementation of the graph commit protocol
- d04ee110c4 2026-08-10 Claude — fix(graphindex): make a document corpus ingestable
- per-directory counts (`git log --format=%h -- <dir> | wc -l`): contracts=20, ontology=12, pageindex=2

## Notes
- FEAT-539 is still open (see F029: TASK-3056 is in-progress and TASK-3054 is done-with-issues), so contracts is a live seam. The pattern being copied could still change.
- The pending FEAT-540 graphindex-core-seams (see F029) plans to rewrite `knowledge/ontology/__init__.py` as a PEP 562 lazy root — an in-flight refactor for ontology.
