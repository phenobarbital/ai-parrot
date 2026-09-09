# Contracts Card & Ontology (FEAT-539)

Installation, configuration and operation of the contracts pilot: one
durable `ContractCard` and PageIndex tree per source document, clause-level
obligations with field-level evidence, a queryable contracts ontology, and
two answer paths that share a single authorization / citation / audit gate.

> **Scope of this guide.** It documents what is implemented. Where a check
> is automated it says so; where a human must sign off (Bob's twelve-case
> pilot review) it says that instead. Automated tests passing is **not**
> pilot acceptance.

---

## 1. Installation

| Capability | Install |
|---|---|
| Catalog + temporal plane (required) | `pip install 'ai-parrot[graphindex,graphindex-postgres]'` |
| Text-PDF ingestion | `pip install 'ai-parrot[pdf]'` (pymupdf / pymupdf4llm) |
| DOCX ingestion, ontology datasource | `pip install ai-parrot-loaders` |
| ArangoDB ontology projection | `pip install 'ai-parrot-embeddings[arango]'` |
| SharePoint / OneDrive delta tools | `pip install 'ai-parrot-tools[office365]'` |

`ai-parrot[graphindex]` is what pulls in `rapidfuzz>=3.0`, used for
deterministic parent resolution and party/title matching (FEAT-539 added it
to that extra). `asyncpg` and `rapidfuzz` are imported lazily, so importing
`parrot.knowledge.contracts` works without them — you only need them on the
paths that use them.

Nothing here requires a scheduler, a new transport, or SQLite.

---

## 2. Storage and tenancy

Four stores, each with a different job:

| Store | Holds | Authority |
|---|---|---|
| **PostgreSQL** (`contracts` schema) | cards, obligations, versions, aliases, answer audit, source cursors, judgements, publication outbox | **authoritative** |
| **PageIndex** (filesystem) | derived per-node text of the *published* tree | derived |
| **Evidence archive** (filesystem) | immutable per-version node text | derived, append-only |
| **ArangoDB** | the contracts ontology projection | rebuildable |
| **GraphIndex Postgres** | recorded-time graph history | append-only |

**One schema per tenant.** The schema name is configuration and is validated
as a plain SQL identifier before it can reach a statement; no method accepts
a tenant name as an argument, so neither a model nor a document can reach
another tenant's rows. A shared bare `contracts` schema is acceptable only
for a single-tenant deployment.

```python
from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog

catalog = PostgresContractCatalog(
    dsn=os.environ["CONTRACTS_PG_DSN"],   # or pool=<your asyncpg pool>
    tenant_id="troc",
    schema="contracts_troc",              # per-tenant schema
)
await catalog.setup()                     # idempotent DDL
```

Temporal drains require a catalog pool with at least two connections. They
reserve a pool before acquiring a connection and take a nonblocking database
advisory lock. A busy drain returns no claimed work for the next scheduled run.
Claims and receipts share a catalog transaction; GraphIndex commits separately.
If a worker dies after the graph commit, the next drain validates that commit
and records its receipt without producing another logical revision. Party merges
and retractions append snapshots and queue both projection targets.

`close()` closes only a pool this object created; an injected pool is left
alone.

### The library

```python
from parrot.knowledge.contracts.library import ContractLibrary, OwnerRule

library = ContractLibrary(
    catalog=catalog,
    storage_root="/srv/contracts/storage",    # published/ + staging/ trees
    evidence_root="/srv/contracts/evidence",  # immutable archives
    adapter=page_index_llm_adapter,           # or None for no-LLM ingestion
    owner_rules=[
        OwnerRule(path_prefix="sharepoint://legal/emea", owner_employee_id="emp-2",
                  department="legal-emea"),
        OwnerRule(path_prefix="sharepoint://legal", owner_employee_id="emp-1",
                  department="legal"),
    ],
)
```

**Owner rules**: the *most specific* (longest) matching prefix wins; an
unmatched document is left unassigned rather than guessed. A manual owner
override recorded through `verify_card` survives later ingestion.

**Canonical source identity**: identity is resolved by URI first, then by
content hash. Unchanged bytes are skipped with a reason and create no
revision. The same bytes at a different URI resolve to the existing card and
keep its original canonical URI.

---

## 3. Ingestion

```python
result = await library.add_contract("/mnt/legal/acme-msa.pdf",
                                    source_uri="sharepoint://legal/acme-msa.pdf")
report = await library.add_folder("/mnt/legal", recursive=True)
```

Supported formats: `.md`, `.txt`, `.docx`, `.pdf` (text). Heading-less
markdown and TXT are sectioned deterministically; text PDFs keep physical
page anchors (`## Page N`).

**A scanned / image-only PDF is skipped with an explicit reason** — OCR is
out of pilot scope, and a no-text PDF must never become an empty "successful"
card.

Carding is bounded at **1 + N** model calls: one structured header call plus
at most `max_obligation_sections` (default 12) obligation calls. PageIndex
indexing and relation judgement are separate budgets. With no adapter (or a
failed header call) ingestion falls back to filename/type/date heuristics at
confidence 0.3 with `card_origin="fallback"` and **no invented obligations**.

Every quote is checked verbatim against the indexed node before it can
substantiate a field; an absent or invalid quote caps confidence at 0.5.

Ingestion builds the tree in `staging/`, archives the evidence, commits the
catalog transaction, and only then promotes the staged tree. A failure
anywhere in between leaves the previously published card, tree and evidence
usable.

---

## 4. Verification, refresh and the two clocks

```python
await library.verify_card("acme-msa", {"title": "ACME MSA"},
                          user="bob@troc", expected_revision=3)
await library.verify_card("acme-msa", None, user="bob@troc")  # whole card
await library.refresh_card("acme-msa", source="/mnt/legal/acme-msa.pdf")
```

* A value equal to the current one (or `None`) **confirms** the field and
  leaves its origin alone; a different value is a **correction** and moves
  the origin to `manual`.
* The whole card is only marked verified once every gap is resolved: missing
  evidence, unresolved low-confidence fields and stale fields all block it,
  and the blockers are returned.
* `expected_revision` gives optimistic concurrency: a concurrent
  verify/refresh loses with `CatalogConflictError` rather than overwriting.

**Refresh preserves human decisions.** For each previously verified field the
stored quote is compared against the refreshed text:

| Evidence after refresh | Result |
|---|---|
| nonempty quote found verbatim | verified value preserved, evidence rebound to its new node |
| quote changed or missing | **previous value kept**, incoming value recorded as a `candidate`, field marked stale |
| empty quote | never proves anything — treated as changed |

**Remote sources**: a card ingested from SharePoint/OneDrive has no local
path, so `refresh_card` needs the freshly downloaded bytes — pass
`source=`, or let `ingest_delta` supply them through its downloader.

### Effective time vs recorded time

Two different questions, deliberately answered separately:

* **Effective (contractual) time** — `contract_in_force`, over the card's
  embedded `versions[]`. "Which wording applied on 1 August?"
* **Recorded time** — the GraphIndex plane (`graph_as_of`,
  `contract_history`, `contract_diff`). "What had we recorded by then?"

An amendment effective 1 July but recorded on 9 September answers *July* on
the first and *September* on the second. An unknown effective date stays
unresolved; it never silently becomes today.

---

## 5. Publication

```python
report = await graph_loader.publish_all()      # ontology (ArangoDB)
drain  = await temporal.drain(tenant_context)  # GraphIndex temporal plane
```

* `publish(card)` deliberately delegates to `publish_all()`: the generic
  refresh diff soft-deletes anything absent from the extraction it is given,
  so a single-card snapshot would retract the rest of the catalog.
* **A partial target failure is not success.** `publish_all` reads back the
  intended node and edge sets and only then sets `published=True`; an empty
  `errors` list is not evidence. The CLI exits nonzero when either target
  failed.
* Publication work lives in a durable outbox. Temporal publication is
  serialized per tenant with a stable `run_id`, so a crash between commit and
  receipt is **recovered** (`list_commits` + payload validation) instead of
  emitting a duplicate logical version.
* Retraction marks the contract and its obligations inactive, removes their
  incident feature-owned edges and queues tombstones. Catalog history,
  archived evidence, the answer audit, shared parties/people and unrelated
  collections all survive.

---

## 6. Answering

Two producers, **one gate**:

```
question
  -> closed-set triage        (evaluative/deontic -> interpretation_required)
  -> authorize                (contract_reader OR contract_owner, default deny)
  -> deterministic retrieval  (ten allowlisted patterns, no LLM, no dynamic AQL)
  -> bounded enumerated dossier
  -> draft                    (the ONLY model call: fixed flow or ReAct agent)
  -> verify citations/claims  (archived evidence, version + hash + page)
  -> audit                    (every outcome, including denials)
  -> release
```

**Retrieval is LLM-free.** It classifies the question against ten patterns,
resolves entities against the *authorized* catalog and binds every value
itself — including an explicitly-null obligation `kind`, injected dates, a
bounded `top_k`, and the full `employees/<id>` graph id for `my_contracts`.
Uncertainty fails closed: an unsupported question or an ambiguous entity
returns a typed clarification, never a guess.

Flows and agents pass their producer to the service per request; constructing
another producer does not change an existing flow. Direct service callers can
configure a default producer or pass `producer=` to `answer()`/`stream_answer()`.
The shared dossier includes field provenance as well as obligations, and uses
the selected version's snapshot for historical questions. Handoff metadata is
built from the authenticated request and authorized cards.

**Drafting never releases.** Whatever a model returns is a draft. A claim
whose citations do not survive verification is deleted, and unrelated
surviving evidence cannot rescue it; zero surviving citations turns a lookup
into `not_found`. Streaming buffers the substantive answer until the whole
chain has succeeded.

**Audit is mandatory.** If the audit write fails, the request fails — an
unaudited answer is never returned.

Answer kinds: `lookup` (text + ≥1 citation), `interpretation_required`
(handoff, never a judgment), `not_found` / `out_of_scope` / `denied` (no
text, no evidence).

### Retirement

Retiring an answer suppresses **every** `(contract_id, node_id)` pair it
cited, for that tenant, from future lookups, handoffs and section reads. The
suppression is deliberately broad and version-independent: renumbering an
unchanged excerpt on refresh cannot evade it.

---

## 7. O365 delta and the watcher jobs

Two tools ship in `parrot_tools.o365`: `DeltaSharePointFilesTool` and
`DeltaOneDriveFilesTool`. They follow `@odata.nextLink` to the final
`@odata.deltaLink`, expose tombstones, and retry throttling/transient
failures with bounded backoff, honouring `Retry-After` in full.

Continuation links are validated **before** any credential is forwarded:
they must sit on a configured Microsoft Graph origin *and* address the delta
endpoint of the drive being enumerated. Origin alone is not enough —
`DeltaRequestBuilder.with_url()` replaces the whole URL, so a same-origin
link could otherwise point the authenticated request at another drive, or at
a file's `/content`.

A 410 means the cursor is dead, never that everything was deleted. The tool
re-enumerates the drive once and reports `reset_performed`.

### Scoping a source to a folder

Microsoft's delta feed **omits `parentReference.path`** and tells clients to
"always track items by id". A path filter therefore cannot decide membership
on its own, so the tools resolve `folder_path` to the folder's item id and
then match by ancestry — walking each item's parent chain, cached per run.

Prefer passing `folder_id` when you know it; it skips the lookup. If
membership still cannot be decided (an unreadable parent, or a folder that
will not resolve) the tools **refuse** rather than quietly returning the
whole drive, and name `folder_id` in the error. `strict_folder_scope=False`
opts out of that refusal deliberately.

Three jobs live in `parrot_tools.contracts.jobs`. They import no scheduler
and send nothing:

| Job | Default cadence (deployer's choice) | Returns |
|---|---|---|
| `ingest_delta` | every few hours | per-file outcomes + cursor state |
| `renewals_report` | daily | 0-30 / 31-60 / 61-90 day buckets |
| `obligations_digest` | weekly | due / recurring / needs-review |

**Cursor rule**: `ingest_delta` commits the final delta link only when the
enumeration completed *and* every item was durably processed or explicitly
skipped. Otherwise the old cursor is retained and the batch replays
idempotently. A failed enumeration is not an empty one — it retains the
cursor too, rather than advancing over changes nobody saw.

**Expired cursors and reconciliation.** When a cursor expires the job
re-enumerates the drive in full; simply retaining the dead cursor would
stall that source forever, because every later run hits the same 410. A
deletion that happened while the cursor was expired appears in no page, so
the recovered rescan is reconciled against what the catalog already holds.

That reconciliation is the only destructive path in these jobs, so it is
deliberately timid. It withdraws a contract only when absence is genuinely
evidence:

- the rescan is **complete** and carries its final cursor;
- it covers the **whole drive** — a folder-scoped rescan sees only part of
  it, so its missing items are reported in `suspected_deletions` for a human
  instead of being acted on;
- the stored item belongs to the **drive that was scanned** (one source name
  may span drives);
- **no item errored** in the run;
- **no other live file** still backs the same card (identical files
  deduplicate onto one contract).

Retraction withdraws the projection before marking the source item deleted,
so a partial failure is retried rather than stranding a contract that is
flagged gone but still indexed. As everywhere else, catalog history, the
archived evidence and the original document survive; only the indexed
projection is withdrawn.

`SourceConfig` fields: `source` (also the cursor key), `drive_id`,
`folder_path`, `folder_id` (the exact filter — forwarded only when set) and
`download`.

`obligations_digest` interprets only recognised, *anchored* recurrences;
anything else is surfaced under `needs_review` rather than guessed.

Wiring is the deploying agent's job:

```python
@schedule(cron="0 7 * * *")            # your scheduler, not ours
async def daily_renewals():
    report = await renewals_report(retrieval=retrieval, principal=service_principal)
    await send_result(report)          # your delivery, not ours
```

The service principal is a `RequestContext` like any other: a principal with
a read role covers the catalog, one with only an employee identity is
narrowed to its own contracts exactly like `my_contracts`.

---

## 8. Operator CLI

```bash
python -m parrot_tools.contracts --user bob@troc --role contract_reader queue
python -m parrot_tools.contracts --user bob@troc --role contract_reader search "SOC 2"

# State-changing commands require the owner role (default deny), and are
# authorized before the write happens — the CLI is a transport like any
# other, not an exemption from the gate:
python -m parrot_tools.contracts --user bob@troc --role contract_owner \
  add /mnt/legal/acme-msa.pdf
python -m parrot_tools.contracts --user bob@troc --role contract_owner \
  add-folder /mnt/legal --recursive
python -m parrot_tools.contracts --user bob@troc --role contract_owner \
  refresh acme-msa --source /mnt/legal/acme-msa.pdf
python -m parrot_tools.contracts --user bob@troc --role contract_owner \
  relate acme-msa --force
python -m parrot_tools.contracts --user bob@troc --role contract_owner publish

# Administrative actions need --confirm AND the owner role:
python -m parrot_tools.contracts --user bob@troc --role contract_owner --confirm \
  verify acme-msa --set title="ACME MSA" --expected-revision 3
python -m parrot_tools.contracts --user bob@troc --role contract_owner --confirm \
  merge-parties party-acme party-acme-old
python -m parrot_tools.contracts --user bob@troc --role contract_owner --confirm \
  retire-answer ans-abc123 --reason "wrong clause"
```

Exit codes: `0` success, `1` failure (including a partially failed
publication), `2` refused (missing `--confirm`, bad argument), `3` denied
(authorization), `4` audit outage.

Deployment configuration lives outside the package — wire it once:

```python
from parrot_tools.contracts.cli import main
raise SystemExit(main(factory=build_contract_services))
```

`--confirm` is a flag the human types; no tool argument and no model output
can set it. Tool metadata (`requires_confirmation`) marks the write tools for
HITL transports, but the **service** re-checks the owner role and the
confirmation itself.

---

## 9. Testing and acceptance

Live suites are opt-in and never silently target another database:

```bash
export GRAPHINDEX_PG_DSN="postgresql://parrot:parrot@127.0.0.1:55439/contracts"
export CONTRACTS_ARANGO_URL="http://127.0.0.1:58529"
export CONTRACTS_ARANGO_PASSWORD=parrot

python -m pytest packages/ai-parrot/tests/knowledge/contracts/ -q
python -m pytest packages/ai-parrot-tools/tests/contracts/ -q
```

Run the two packages as separate invocations — both test trees are rooted at
`tests`, so collecting them together collides. A missing service skips only
its own suite and **does not** count as acceptance.

Benchmark procedure and measured results:
[`contracts-performance.md`](contracts-performance.md).

### Pilot signoff

Automated tests do not close the pilot. Acceptance is Bob's review of the
twelve agreed question/answer cases (the two client questions plus his ten
common ones), each with citations and explicit handoffs, recorded in
[`contracts-pilot-acceptance.md`](contracts-pilot-acceptance.md).

---

## 10. Pilot exclusions

Out of scope, deliberately:

* legal advice, compliance determinations, redline acceptance;
* OCR / scanned PDFs (skipped with a reason);
* bilingual analyzers — the pilot is English-only;
* a SQLite backend;
* the verification UI (separate `contracts-verification-ui` spec);
* new scheduler or transport infrastructure, and any automatic delivery.

### Known limitation

`OntologyGraphStore.upsert_nodes` (generic module
`parrot/knowledge/ontology/graph_store.py`) builds
`UPSERT { @key_field: doc[@key_field] }`, and ArangoDB rejects a bind
parameter as an UPSERT example attribute name (ERR 1501). The fallback path
uses the same construct, so **no node reaches a real ArangoDB through that
API**; it is pinned by a test in
`packages/ai-parrot/tests/knowledge/contracts/test_integration.py`. The ten
AQL patterns are verified against a real graph, but the ontology publish path
cannot be exercised end to end until that generic module is fixed — which is
outside this feature's owned files. The catalog, evidence, temporal plane and
both answer paths are unaffected: SQL search, windows, queues and reports all
work with no ArangoDB at all.

### Recovery and evidence compatibility

An unchanged-content ingestion retry finishes a committed tree promotion before
reporting the source as unchanged. Section tools read the source-hash-bound
immutable archive, including for trees created before promotion hash markers.
A verification timestamp is not a contractual recurrence anchor: recurring
obligations without evidenced schedule anchors remain in `needs_review`.
