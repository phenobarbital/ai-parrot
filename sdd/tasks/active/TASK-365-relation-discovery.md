# TASK-365: Relation Discovery Engine

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (4-8h)
**Depends-on**: TASK-360, TASK-363
**Assigned-to**: —

---

## Context

> Automatic edge creation from data sources using multiple strategies: exact field match,
> fuzzy match, AI-assisted, and composite. Implements spec Module 10.

---

## Scope

### Create `parrot/knowledge/ontology/discovery.py`

`RelationDiscovery`:
- `__init__(self, llm_client=None)` — LLM client for AI-assisted strategy.
- `async discover(self, ctx: TenantContext, relation_def: RelationDef, source_data: list[dict], target_data: list[dict]) -> DiscoveryResult`:
  - Iterate over `relation_def.discovery.rules`.
  - Apply matching strategy per rule.
  - Merge results, deduplicate (same source→target pair).
  - Partition: confirmed (>= threshold) vs review_queue (< threshold).

**Strategies:**

1. `_exact_match(source_data, target_data, rule) -> list[dict]`:
   - Build lookup dict on `target_field` for O(n) matching.
   - Deterministic, no ambiguity.

2. `_fuzzy_match(source_data, target_data, rule, threshold) -> tuple[list, list]`:
   - Use `rapidfuzz.fuzz.ratio()` for normalized string matching.
   - Returns (confirmed, ambiguous) — ambiguous = below threshold but above minimum (0.5).

3. `async _llm_resolve_batch(candidates, relation_def, batch_size=50) -> list`:
   - Batch ambiguous pairs, send to LLM with structured output.
   - LLM returns confidence scores per pair.
   - Partition by `rule.threshold`.

4. `_composite_match(source_data, target_data, rule) -> tuple[list, list]`:
   - Multi-field weighted scoring.
   - (Can be implemented as extension of fuzzy with multiple fields.)

**Review queue output:**
- Write ambiguous pairs to `{ONTOLOGY_REVIEW_DIR}/{tenant}_review_queue.json`.
- Each entry: `{source_value, target_value, confidence, rule_name, timestamp}`.

`DiscoveryResult(BaseModel)`:
- `confirmed: list[dict]` — edges to create (`{_from, _to, confidence, rule}`).
- `review_queue: list[dict]` — ambiguous pairs.
- `stats: DiscoveryStats` — total_source, total_target, edges_created, needs_review.

---

## Acceptance Criteria

- [ ] Exact match produces correct edges with O(n) lookup.
- [ ] Fuzzy match partitions confirmed vs review queue by threshold.
- [ ] AI-assisted batches to LLM and respects `batch_size`.
- [ ] Results deduplicated (same source→target from multiple rules keeps highest confidence).
- [ ] Review queue written to JSON file at configured path.
- [ ] `DiscoveryStats` accurately reports counts.
- [ ] `rapidfuzz` used for fuzzy matching.
- [ ] Unit tests for each strategy.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/discovery.py` | **Create** |
| `tests/knowledge/test_ontology_discovery.py` | **Create** |
