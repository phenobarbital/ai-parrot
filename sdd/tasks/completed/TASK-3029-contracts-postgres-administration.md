# TASK-3029: Catalog aliases, audit, sources and publication state

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3028
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M2 in spec §3 and the corresponding normative §2 behavior. Covers AC3, AC10, AC11; full feature acceptance remains governed by spec §§4–5.

## Scope

- Complete party merge/alias, answer audit/retirement, source-item/cursor, relation judgement and durable outbox operations declared by the protocol.
- Merge cards/signatories/aliases/queued projections atomically while preserving snapshots; reject alias conflicts, self-merges and unknown identities.
- Persist all answer outcomes and retirement actor/time/reason. Suppress every tenant contract/node pair, carry evidence remappings across renumbering and expose cache invalidation state.
- Persist immutable publication payloads, target state/receipts/retries and judgement outcomes including none; preserve force history and source identity/tombstones.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_catalog_administration.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence  # packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:207
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| PostgresPersistence constructor | (self, dsn: Optional[str] = None, *, pool: Optional[asyncpg.Pool] = None, schema: str = "graphindex") -> None | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:226 |
| apply_update | async (self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt; independent transaction and generated commit_id | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:834 |
| list_commits / get_commit | async list_commits(self, ctx, run_id=None, agent_id=None, limit=50); async get_commit(self, ctx, commit_id) | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:1005; packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:976 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| Additional catalog methods | async merge_parties(keep_party_id, merge_party_id, *, user), party_aliases(party_id), record_answer(record), retire_answer(answer_id, *, user, reason), retired_citations(), get_delta_token(source_uri), set_delta_token(source_uri, token); typed obligation-window, source-item, judgement and outbox operations |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- PostgresPersistence is not a ContractCatalogStore; passing TenantContext does not tenant-scope all temporal reads or join apply_update to catalog transactions.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3028`: Catalog search, date windows and verification queue; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Live transactions test party-merge rollback and alias conflicts; historical snapshots remain unchanged.
- [ ] Audit round trips include denied/empty outcomes; retirement suppresses lookup and handoff across versions/renumbering.
- [ ] Cursor/source identity and outbox claims/receipts survive reconnect; tenant isolation and revision conflicts hold.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Live transactions test party-merge rollback and alias conflicts; historical snapshots remain unchanged.
2. Audit round trips include denied/empty outcomes; retirement suppresses lookup and handoff across versions/renumbering.
3. Cursor/source identity and outbox claims/receipts survive reconnect; tenant isolation and revision conflicts hold.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_catalog_administration.py -q`

Store execution logs in `artifacts/logs/task-3029.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3029-contracts-postgres-administration.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: completed the administration surface of `catalog_postgres.py`;
`PostgresContractCatalog.__abstractmethods__` is now empty. `merge_parties` runs one
transaction: validates both identities exist (`UnknownPartyError`), rejects
self-merge, locks matching cards via JSONB containment, rewrites parties
(de-duplicating when both identities sit on one card) and signatories, bumps the
revision, remaps alias rows and enqueues one ontology publication per touched card —
historical version snapshots are untouched. Aliases: `add_party_alias` is idempotent
but raises `AliasConflictError` on a remap, plus `party_aliases`/`all_party_aliases`/
`resolve_party`/`list_parties` (distinct, active-only). Audit: `record_answer`
persists every outcome including denied/empty; `retire_answer` stamps actor/time/
reason; `retired_citations` derives suppressed `(contract_id, node_id)` pairs from
retired answers' citations JSONB, so it is version- and hash-independent. Sources:
delta cursor get/set and `upsert_source_item` preserving the card link across renames
plus tombstones. Judgements: append-only history (force records a new row),
`replace_relations`, `active_relations` and `invalidate_relations` (deactivates
judgements whose endpoint hash moved and their relations). Outbox:
`pending_publications`, `claim_publication` (`FOR UPDATE SKIP LOCKED`, attempts
counter), `complete_publication` (receipt) and `fail_publication` (retryable error);
payloads are immutable once queued.

**Validation**: `pytest .../test_catalog_administration.py -q` -> **18 passed**
against real Postgres 16. Covers merge with signatories/aliases/queued projection and
unchanged snapshots, merge de-duplication, unknown-identity rollback, alias conflict,
audit round trip for lookup/denied/not_found, retirement actor/reason plus
version-independent suppression, cursor and receipt survival across a reconnect,
rename/tombstone identity, judgement history including `none` and force, relation
invalidation, outbox claim/fail/retry/receipt and cross-schema isolation of answers,
aliases and cursors. Whole contracts suite 164 passed
(`artifacts/logs/task-3029.log`); ruff clean.

**Deviations**: none. Suppression is derived from `contract_answers` rather than a
separate table, matching the spec §2 table list.
