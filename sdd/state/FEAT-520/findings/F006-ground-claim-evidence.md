# F006 — ground_claim signature + evidence model (OQ2)
**Query**: Q005/Q006 | **Confidence**: high

- `graphindex/grounding.py:204` — `async def ground_claim(self, claim: str) -> GroundingResult`. Resolves claim entities, BFS shortest paths over the in-memory retriever graph (max_hops), `contradicts` edges never count as support. Evidence = lists of `stable_edge_id(src, dst, kind)` strings; `decision: grounded|revise` with `required_evidence` hints. **No chunk FK anywhere** — grounding is graph-native.
- `graphindex/schema.py`: `Provenance` enum (:18), `NodeKind` (:36), `EdgeKind` (:64), `AssertionMeta` (:100, carries `asserted_by`), `UniversalNode` (:149, `provenance`, `content_ref`, `embedding_ref`, `source_uri`), `UniversalEdge` (:184, validator: `confidence` set iff `provenance==INFERRED`), `GraphUpdate`/`CommitReceipt`.
⇒ evidence_ref (brainstorm D4) is a NEW column with no existing consumer; UniversalEdge would need an optional field. Closing OQ2 needs a design decision, not code archaeology. Note: node already has `content_ref` (markdown-on-disk pointer) — consistent with body_ref in the draft schema.
