# TASK-3054: Cross-store integration and regression acceptance

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done-with-issues
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3025, TASK-3026, TASK-3027, TASK-3028, TASK-3029, TASK-3030, TASK-3031, TASK-3032, TASK-3033, TASK-3034, TASK-3035, TASK-3036, TASK-3037, TASK-3038, TASK-3039, TASK-3040, TASK-3041, TASK-3042, TASK-3043, TASK-3044, TASK-3045, TASK-3046, TASK-3047, TASK-3048, TASK-3049, TASK-3050, TASK-3051, TASK-3052
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M1–M12 in spec §3 and the corresponding normative §2 behavior. Covers AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8, AC9, AC10, AC11, AC12, AC13; full feature acceptance remains governed by spec §§4–5.

## Scope

- Create shared synthetic English MSA/SOW/amendment/NDA/contradictory-clause fixtures, generated small PDF/DOCX/text/image-only PDF and two tenants reusing slugs/node IDs; freeze dates and inject boundary failures.
- Run real Postgres atomicity/isolation, GraphIndex recovery/history and Arango domain initialization/all ten AQL pattern tests, including first-publish standards, owner changes, retraction, family/search mapping.
- Run fake Graph -> ingest -> verify -> graph/temporal -> both answer producers -> retire -> refresh -> watcher end-to-end and affected bookstore/O365 regressions.
- Use explicit GRAPHINDEX_PG_DSN and temporary schemas only; Arango also requires explicit config. Missing services skip only relevant suites but do not satisfy full acceptance. Save logs in artifacts/logs/.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/contracts/test_integration.py` | CREATE | Focused verification / fixtures |
| `packages/ai-parrot/tests/knowledge/contracts/conftest.py` | CREATE | Focused verification / fixtures |
| `packages/ai-parrot-tools/tests/contracts/test_end_to_end.py` | CREATE | Focused verification / fixtures |
| `packages/ai-parrot-tools/tests/contracts/conftest.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:34
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence  # packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:207
from parrot_tools.o365.base import O365Tool, O365ToolArgsSchema  # packages/ai-parrot-tools/src/parrot_tools/o365/base.py:31
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| PageIndexToolkit | async create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]; delete_tree/get_tree take tree_name | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377 |
| insert_markdown | async (self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None, doc_name: Optional[str] = None) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:692 |
| import_pdf | async (self, tree_name: str, pdf_path: str, parent_node_id: Optional[str] = None, with_summaries: bool = True, with_doc_description: bool = False) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:803 |
| execute_traversal | async (self, ctx: TenantContext, aql: str, bind_vars: dict or None = None, collection_binds: dict[str, str] or None = None) -> list[dict[str, Any]] | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:234 |
| upsert_nodes | async (self, ctx: TenantContext, collection: str, nodes: list[dict[str, Any]], key_field: str) -> UpsertResult; copies key field to _key | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:274 |
| create_edges | async (self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int; UPDATE {} on duplicate endpoints | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:372 |
| edges_incident / remove_edge_by_triple | Edges keyed by source_id/target_id/kind, not just _from/_to | packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:725; packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:752 |
| PostgresPersistence constructor | (self, dsn: Optional[str] = None, *, pool: Optional[asyncpg.Pool] = None, schema: str = "graphindex") -> None | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:226 |
| apply_update | async (self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt; independent transaction and generated commit_id | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:834 |
| list_commits / get_commit | async list_commits(self, ctx, run_id=None, agent_id=None, limit=50); async get_commit(self, ctx, commit_id) | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:1005; packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:976 |
| O365Tool._execute_graph_operation | async (self, client: O365Client, **kwargs) -> Any; _execute handles authentication and ToolResult | packages/ai-parrot-tools/src/parrot_tools/o365/base.py:200 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- OntologyRefreshPipeline.run has no filters argument and no atomic multi-collection publish; create_edges does not update existing edge properties.
- PropertyDef has no datetime/nested-model type; RelationDef has no symmetric flag.
- PostgresPersistence is not a ContractCatalogStore; passing TenantContext does not tenant-scope all temporal reads or join apply_update to catalog transactions.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3025`: Typed contract models and standard aliases; inspect its completed artifact and committed interface before use.
- `TASK-3026`: Tenant-bound asynchronous catalog protocol; inspect its completed artifact and committed interface before use.
- `TASK-3027`: Postgres schema and atomic card writes; inspect its completed artifact and committed interface before use.
- `TASK-3028`: Catalog search, date windows and verification queue; inspect its completed artifact and committed interface before use.
- `TASK-3029`: Catalog aliases, audit, sources and publication state; inspect its completed artifact and committed interface before use.
- `TASK-3030`: Bounded evidenced header and obligation extraction; inspect its completed artifact and committed interface before use.
- `TASK-3031`: Deterministic assembly, status and parent resolution; inspect its completed artifact and committed interface before use.
- `TASK-3032`: Public asynchronous DOCX conversion helper; inspect its completed artifact and committed interface before use.
- `TASK-3033`: Immutable tenant and version-scoped evidence storage; inspect its completed artifact and committed interface before use.
- `TASK-3034`: Staged library ingestion and canonical source identity; inspect its completed artifact and committed interface before use.
- `TASK-3035`: Verification and refresh preserve human decisions; inspect its completed artifact and committed interface before use.
- `TASK-3036`: Contracts ontology vocabulary and allowlisted patterns; inspect its completed artifact and committed interface before use.
- `TASK-3037`: Catalog-backed ContractCard datasource; inspect its completed artifact and committed interface before use.
- `TASK-3038`: Full-catalog graph reconciliation and retraction; inspect its completed artifact and committed interface before use.
- `TASK-3039`: Recoverable GraphIndex temporal revision publisher; inspect its completed artifact and committed interface before use.
- `TASK-3040`: Explicit bounded relation judgements and invalidation; inspect its completed artifact and committed interface before use.
- `TASK-3041`: O365 drive delta pages, validation and retry helper; inspect its completed artifact and committed interface before use.
- `TASK-3042`: SharePoint and OneDrive delta tools and registration; inspect its completed artifact and committed interface before use.
- `TASK-3043`: Deterministic authorized retrieval and typed pattern binds; inspect its completed artifact and committed interface before use.
- `TASK-3044`: Versioned citation and claim verification gate; inspect its completed artifact and committed interface before use.
- `TASK-3045`: Shared answer authorization, release and audit service; inspect its completed artifact and committed interface before use.
- `TASK-3046`: Prefixed read tools and confirming administration; inspect its completed artifact and committed interface before use.
- `TASK-3047`: Executable fixed contracts answer runner; inspect its completed artifact and committed interface before use.
- `TASK-3048`: ReAct ContractsAgent with shared release gate; inspect its completed artifact and committed interface before use.
- `TASK-3049`: Durable O365 delta ingestion job; inspect its completed artifact and committed interface before use.
- `TASK-3050`: Deterministic renewal and obligation reports; inspect its completed artifact and committed interface before use.
- `TASK-3051`: Contracts operator CLI and administrative commands; inspect its completed artifact and committed interface before use.
- `TASK-3052`: Declare approved rapidfuzz extra and refresh lock; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] All configured unit/live integration/regression suites pass with failure injection and no tenant/evidence leak.
- [ ] Every ten-pattern query executes with real bindings; historical evidence survives refresh and crash recovery avoids duplicate logical versions.
- [ ] Record suite results and services actually exercised; unavailable live suites leave feature acceptance pending.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. All configured unit/live integration/regression suites pass with failure injection and no tenant/evidence leak.
2. Every ten-pattern query executes with real bindings; historical evidence survives refresh and crash recovery avoids duplicate logical versions.
3. Record suite results and services actually exercised; unavailable live suites leave feature acceptance pending.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_integration.py packages/ai-parrot-tools/tests/contracts/test_end_to_end.py -q`

Store execution logs in `artifacts/logs/task-3054.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3054-contracts-live-integration.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5), **done-with-issues** — see the upstream defect below.

**Implementation**: created the shared fixtures
(`packages/ai-parrot/tests/knowledge/contracts/conftest.py`,
`packages/ai-parrot-tools/tests/contracts/conftest.py`) — synthetic English MSA/SOW/
amendment/NDA/contradictory-clause corpus, generated DOCX, two-page text PDF and
image-only PDF, heading-less TXT, frozen clocks, and explicit live-service gates
(`GRAPHINDEX_PG_DSN`, `CONTRACTS_ARANGO_URL`) — plus
`test_integration.py` (cross-store) and `test_end_to_end.py` (vertical slice).

**Services actually exercised** (not skipped): PostgreSQL 16 with pgvector
(disposable container, temporary schemas per test) and ArangoDB 3.11.14 (disposable
container, throwaway database per test).

**Validation** (`artifacts/logs/task-3054.log`):
- core contracts suite: **482 passed**
- tools contracts suite: **188 passed**
- regressions: bookstore **150 passed**, ontology **206 passed**, O365 delta
  **51 passed**
- graphindex: 783 passed, 4 failed — **pre-existing on dev**, reproduced in the
  untouched main checkout (`test_schema.py::TestEdgeKind::test_all_values`,
  `test_projection.py::TestMappingTables::test_all_edge_kinds_mapped`, two
  `test_meta_ontology.py::TestEnumCompleteness` cases). Untouched by this feature.

Live coverage includes: ingest -> verify -> refresh against a real catalog with the
human correction surviving and the v1 citation still resolving; an injected failure
rolling back card/versions/outbox; two tenants reusing the same slug and node ids with
no evidence leak and a cross-tenant reference refused; md/txt/docx/text-PDF ingestion
with page anchors and an explicit image-only-PDF skip; SQL reports with no Arango;
temporal successive revisions, recorded history and a faithful crash-after-commit
recovery (outbox reset) reusing the same commit with `list_commits` proving no
duplicate; **all ten AQL patterns executed against real ArangoDB with real bind
values** (first-publish standard link, party role, family de-duplication, signatories,
obligations, effective-version selection, my_contracts, search hits mapping back to
contracts) plus a test that inactive endpoints are filtered; and the full vertical
slice (fake Graph delta -> ingest -> verify -> temporal publish -> fixed flow AND
ReAct producer -> toolkit reads -> retire -> suppressed section -> refresh ->
watcher reports) with every outcome audited, plus idempotent re-runs and an
end-to-end denial for an unauthorized principal.

**BLOCKING UPSTREAM DEFECT (reported, not patched)**:
`OntologyGraphStore.upsert_nodes` builds `UPSERT { @key_field: doc[@key_field] }`;
ArangoDB rejects a bind parameter as an UPSERT example attribute name (ERR 1501,
'expecting object literal with literal attribute names in example'). The individual
fallback path uses the same construct and fails identically, so **no node reaches a
real ArangoDB through that API** — reproduced standalone against 3.11.14 (a literal
attribute name works). It lives in `parrot/knowledge/ontology/graph_store.py`, a
generic module this feature is explicitly forbidden to modify, so it is pinned by
`test_the_generic_node_upsert_is_broken_against_a_real_graph` and reported instead of
patched. Consequence: `ContractGraphLoader.publish_all` cannot be verified end to end
against a live graph until it is fixed; the ten patterns were therefore verified
against documents written with literal-attribute AQL. **AC5/AC6 remain partially
pending on that fix.**

**Deviations**: the two suites are run as two pytest invocations rather than one — both
packages' test trees are rooted at `tests`, so collecting them together collides.

---

## Post-implementation adversarial review (FEAT-539 closing)

Two reviewers ran the same neutral brief (diff vs `dev`, spec §5 acceptance
criteria, changed-file list; no conclusions supplied): `codex exec review
--base dev` and a Claude `code-reviewer` subagent. Every finding below was
re-verified against the source before being actioned — several reviewer
claims did not reproduce (see REJECTED).

### Fixed in `54589ec02` (each with a regression test that fails without the fix)

| # | Finding | Evidence |
|---|---|---|
| 1 | The verifier rebuilt the evidence pointer from the card's *current* revision; the archive is immutable and written once per version, so any administrative write (verification, party merge) made every citation unresolvable and silently degraded evidenced answers to `not_found`. Both reviewers found this independently. | Reproduced against live Postgres: `test_citations_survive_a_revision_bump`, `test_a_verified_card_still_releases_its_citations` |
| 2 | Five state-changing CLI commands (`add`, `add-folder`, `refresh`, `relate`, `publish`) ran with **no** authorization. | `test_state_changing_commands_are_denied_without_the_owner_role` |
| 3 | `ingest_delta` authorized only when a `retrieval` kwarg was passed — omitting a keyword ran the job, including tombstone retractions, unauthenticated. | `test_omitting_the_retrieval_gate_does_not_skip_authorization` |
| 4 | A caller with no `employee_id` matched every *ownerless* contract, because `owner_employee_id is None` compared equal to a missing identity. | `test_an_ownerless_contract_is_not_owned_by_an_identityless_caller` |
| 5 | `ContractsAgent` inherited `ask`/`ask_stream`/`invoke` ungated — the chat/MCP/A2A/HTTP surfaces could obtain the unverified ReAct draft, the exact escape AC10 forbids. | `test_the_generic_bot_entrypoints_refuse_to_release_a_draft` |

Also hardened `test_dependency_boundary.py`, which inherited the ambient
`PYTHONPATH` and could therefore validate an installed `parrot` rather than
the worktree, and extended it to `parrot_tools.contracts`.

### CONFIRMED but deliberately NOT fixed here (for the PR reviewer)

* **Shared mutable producer on the service.** `ContractsAnswerService.producer`
  is instance state that both producers overwrite, so two concurrent requests
  through one service instance can cross-assign producers. Correct fix is to
  pass the producer per call, which changes the service/flow/agent/toolkit
  signatures — a design change, not a review patch. Single-request use is
  unaffected.
* **The ReAct producer can only cite obligations.** `result.obligations` is
  populated for two of the ten patterns, so the other eight release nothing
  through that producer. Fails *safe* (no fabrication), but "both answer
  producers" is only demonstrated for two patterns. **ESCALATE** — what counts
  as citable evidence for party/expiry/history questions is a spec decision.
* **Producer-supplied handoff fields.** `HandoffBrief.question`,
  `why_judgment`, `related_contracts` and `suggested_owner` are not verified
  (only `located_clauses` are). The service's own interpretation path builds
  the brief itself, so this is reachable only via a custom producer.
  **ESCALATE.**
* **`parrot.knowledge.contracts.library` pulls `asyncpg`/`pymupdf`/`msal`.**
  Root cause is `parrot/knowledge/pageindex/__init__.py` eagerly importing
  `builder` → `llm_adapter` → `parrot.clients`, reached from the required
  `NodeContentStore` import. **Not patched**: that is a generic module this
  feature is explicitly forbidden to modify. The package-level guard still
  holds (`parrot.knowledge.contracts` itself leaks nothing).
* **`rapidfuzz` is undeclared for `ai-parrot-tools`**, where
  `retrieval.py` swallows the `ImportError` and degrades counterparty
  resolution to a `Clarification` instead of an install instruction (core
  `carding.py` correctly raises). Declaring a tools extra would contradict
  the TASK-3052 pins asserting rapidfuzz lands in exactly one core extra.
  **ESCALATE** — packaging decision.
* **Ingest promotion failure leaves staging behind** (`library.py`, the
  `EvidenceError` branch does not `discard`, unlike the two branches above
  it) and the already-committed version row then references an unpromoted
  archive.
* **Publication outbox reads ignore `tenant_id`** (`pending_publications`,
  `claim_publication`), while `_set_publication_state` filters by it.
  Harmless under schema-per-tenant, latent under a shared schema.
* **`merge_parties` bumps the revision without a version row** and enqueues
  only the `ontology` target, never `temporal` — relevant to AC7's "every
  revision reaches GraphIndex". **ESCALATE.**
* `codex` additionally raised: retractions share a publication revision;
  abandoned in-flight publication claims are never recovered; historical
  revisions are published from the latest card rather than their own
  snapshot; the ontology patterns filter `active` while
  `OntologyGraphStore.soft_delete_nodes()` sets `_active`; contract-id
  resolution prefers a shorter prefix (`acme` over `acme-sow`); recurrence
  uses `verified_at` as an anchor. All plausible and none security-critical;
  each needs a spec judgement rather than a reflex patch.

### REJECTED (claimed but did not reproduce)

* "`test_dependency_boundary.py` fails on the branch." It passes (33/33, now
  34/34). The reviewer had run it without the worktree `PYTHONPATH`, which is
  the environment-sensitivity the hardening above removes — the failure was
  an artifact of their environment, not the branch.
* "`codex` timed out with empty output." That was the subagent's own nested
  `codex` call. The `codex exec review --base dev` run driven from this
  session completed normally and produced 8 P1 and 11 P2 findings, which are
  folded in above.

## Deferred-review fixes — 2026-09-09

Implemented the follow-up requested by the user after reviewing `fd2f48c28`, on
`feat-FEAT-539-contracts-card-ontology` starting from `a985818e7`:

- Producers are selected per request. The real ContractsAgent uses a private
  ReAct entrypoint with caller-scoped tools and an isolated draft session; public
  ungated entrypoints remain refused. Both producers share field/obligation
  evidence enumeration and selected historical snapshots. Citation provenance
  reflects the matching field's verification state. Handoff metadata is rebuilt
  from the authenticated question and authorized cards.
- Catalog merges and retractions append immutable administrative revisions and
  enqueue ontology and temporal work. Administrative writes preserve the prior
  contractual interval and evidence reference. Outbox reads, claims and writes
  enforce their catalog tenant; separate schemas remain required.
- Temporal drains reserve their connection pool and acquire a nonblocking
  database advisory lock. Catalog claims/receipts share a transaction while
  GraphIndex commits independently. A killed worker rolls back its claim;
  recovery validates the committed payload instead of duplicating history.
  Legacy abandoned in-flight rows are reclaimed under the lock. Historical
  node fields come from their own snapshot, not the latest card.
- Promotion retries preserve staged indexes until sidecars move and recognize
  already-completed promotion after a crash. Unchanged-source retries recover
  pending promotion. Section reads use hash-bound archived bodies, preserving
  access for old unstamped trees and during promotion failures.
- Concrete ContractLibrary imports no longer eagerly load optional database,
  PDF or O365 modules. Missing rapidfuzz reports the documented installation
  requirement. Graph patterns honor `_active`; explicit IDs cannot match a
  shorter prefix; verification timestamps never fabricate recurrence anchors.

Final validation on the user's existing `docker-postgres-1` (`ceaa9a23bcfb`),
using temporary schemas only:

- Core contracts: **492 passed, 3 skipped** (live ArangoDB unavailable).
- Answering/tools contracts, including end-to-end: **222 passed**.
- Bookstore and ontology regressions: **356 passed**.
- O365 delta regressions: **51 passed**.
- Shared two-connection pool tests repeated with pending work for both the same
  tenant and different tenants: **2 passed**.
- Black checks, Ruff checks and `git diff --check` pass.

New regressions include actual agent dispatch, interleaved producers, all eight
previously uncitable pattern dossiers for both producers, forged handoff metadata,
field-level verification, tenant-bound outbox operations, merge/retraction history,
legacy and interrupted tree reads, import boundaries, real process exit immediately
after GraphIndex commit, and competing workers sharing a two-connection pool.

Independent SDD adversarial review identified shared-pool starvation and two
promotion/compatibility edge cases during implementation. All were fixed and
covered by regressions; the follow-up review found no remaining issues in those
adjustments. Logs are in `artifacts/logs/task-3054-fixes-*.log`; the last answering
run is `task-3054-fixes-live.log`.

The separately recorded generic Arango UPSERT defect and live Arango acceptance
were not changed or claimed resolved by this follow-up. No new dependencies,
service messages, or pilot-signoff claims were introduced.

## Upstream defect resolved — 2026-09-11

The **BLOCKING UPSTREAM DEFECT** recorded above (`OntologyGraphStore.upsert_nodes`
sending a bind parameter as an UPSERT example attribute name, ArangoDB ERR 1501)
was fixed the same day this task completed, in `341d56919` ("fix(contracts): make
the demo agent answer end to end on real documents", 2026-09-09) — a later commit
on `dev` this task's completion note predates. `graph_store.py` now interpolates
the key field as a validated literal AQL attribute name (`_literal_attribute()`,
guarded by a plain-identifier regex) in both the batch path and the individual-
upsert fallback, instead of a bind parameter, in both `UPSERT { key: doc.key }`
sites. The regression test that pinned the failure was renamed/flipped from
`test_the_generic_node_upsert_is_broken_against_a_real_graph` to
`test_the_generic_node_upsert_reaches_a_real_graph` and now asserts a real
insert + in-place update with no duplication.

Re-verified today against the live stack (`parrot-arangodb` container, ArangoDB
3.11.14; `docker_postgres_1`, Postgres 17):
- `test_the_generic_node_upsert_reaches_a_real_graph` — **passed**.
- Full `packages/ai-parrot/tests/knowledge/contracts/` +
  `tests/knowledge/test_ontology_graph_store.py` + `tests/knowledge/ontology/` —
  **745 passed**, 0 failed. Log: `artifacts/logs/feat539-upsert-fix-verify.log`.

**AC5/AC6 are no longer blocked by this defect** — the ten AQL patterns can now
be verified against a live graph written through the real `upsert_nodes` path
rather than documents pre-written with literal-attribute AQL. This task's
`done-with-issues` status stands, unrelated to this defect: the `ESCALATE` design
findings above (shared mutable producer, ReAct producer's two-of-ten citable
patterns, unverified handoff fields, `rapidfuzz` packaging, ingest promotion
staging leak, publication outbox tenant filter, `merge_parties` revision bump)
remain open and still require a spec decision, not a code fix.
