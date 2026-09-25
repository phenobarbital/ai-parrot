# Procedure Graph — Assembly Manuals (FEAT-601)

Ingest vendor assembly/maintenance manuals into an ordered, evidence-backed procedure graph and answer field technicians with the steps, prerequisites, hazards, figures, video segments and technician tips — released only after a completeness check.

> **Scope of this guide.** It documents what is implemented in v1. The spike gate (§8) needs a human-supplied corpus; automated tests passing is not spike acceptance.

---

## 1. Installation

| Capability | Install |
|---|---|
| Catalog + temporal plane (required) | `pip install 'ai-parrot[graphindex,graphindex-postgres]'` |
| Text-PDF ingestion | `pip install 'ai-parrot[pdf]'` (pymupdf / pymupdf4llm) |
| DOCX ingestion, ontology datasource | `pip install ai-parrot-loaders` |
| ArangoDB ontology projection | `pip install 'ai-parrot-embeddings[arango]'` |
| Video transcript alignment | `pip install ai-parrot-loaders[video]` (whisper) |
| Manual card datasource | `pip install ai-parrot-loaders[manualcard]` |

`ai-parrot[manuals]` is what pulls in `graphindex,bookstore` (rapidfuzz, pymupdf, pymupdf4llm) and the optional loaders for video transcripts and the manualcard datasource. `asyncpg` and `rapidfuzz` are imported lazily, so importing `parrot.knowledge.manuals` works without them — you only need them on the paths that use them.

Nothing here requires a scheduler, a new transport, or SQLite.

---

## 2. Tenancy and authorization

Four stores, each with a different job:

| Store | Holds | Authority |
|---|---|---|
| **PostgreSQL** (`manuals` schema) | cards, procedures, versions, aliases, answer audit, source cursors, judgements, publication outbox | **authoritative** |
| **PageIndex** (filesystem) | derived per-node text of the *published* tree | derived |
| **Evidence archive** (filesystem) | immutable per-version node text | derived, append-only |
| **ArangoDB** | the procedures ontology projection | rebuildable |

**One schema per tenant.** The schema name is configuration and is validated as a plain SQL identifier before it can reach a statement; no method accepts a tenant name as an argument, so neither a model nor a document can reach another tenant's rows. A shared bare `manuals` schema is acceptable only for a single-tenant deployment.

```python
from parrot.knowledge.manuals.catalog_postgres import PostgresManualCatalog

catalog = PostgresManualCatalog(
    dsn=os.environ["GRAPHINDEX_PG_DSN"],   # or pool=<your asyncpg pool>
    tenant_id="troc",
    schema="manuals_troc",              # per-tenant schema
)
await catalog.setup()                     # idempotent DDL
```

**Roles:**
- `technician` — read-only access to procedures, tips, and media (traversals, catalog search, PageIndex fallback, media signing, guided resume).
- `manual_curator` — verify/publish/export actions (write paths).

**Default deny:** any request without a valid tenant-scoped role is refused. Missing tenant ⇒ denied (spec G6, AC9).

**Owner rules:** the *most specific* (longest) matching prefix wins; an unmatched document is left unassigned rather than guessed. A manual owner override recorded through `verify_procedure` survives later ingestion.

**Canonical source identity:** identity is resolved by URI first, then by content hash. Unchanged bytes are skipped with a reason and create no revision. The same bytes at a different URI resolve to the existing card and keep its original canonical URI.

---

## 3. Storage

Figures are stored in the tenant bucket via an injected `FileManagerInterface` (S3 in prod, `TempFileManager` in dev). Storage keys are minted once at ingest and never changed; the graph holds only the key and a caption. Presigned URLs are minted per answer after release, never stored (spec G4, §7).

```python
from parrot.interfaces.file import FileManagerInterface

# In prod: S3FileManager injected via navigator-api
# In dev: TempFileManager (file:// paths)
file_manager: FileManagerInterface = ...

# Upload a figure
storage_key = await file_manager.upload_file(
    path=figure_path,
    bucket=f"manuals-{tenant_id}",
    metadata={"manual_id": manual_id, "figure_id": figure_id},
)

# Get a presigned URL (15-min expiry, per answer)
url = await file_manager.get_file_url(storage_key, expiry=900)
```

**Presigned URL policy:** URLs are valid for 15 minutes, scoped to a single answer, and never cached. The `PARROT_MEDIA_URL_HOSTS` environment variable defines an allowlist of allowed hosts (e.g., `s3.amazonaws.com,storage.googleapis.com`) for Telegram/WhatsApp downloads; any URL from an unlisted host is rejected.

**Postgres catalog schema:** the `manuals` schema contains tables for `manuals`, `procedures`, `steps`, `media`, `versions`, `tips`, `applicability`, `hazards`, `prerequisites`, `media_roles`, `callouts`, `verification_queue`, `answer_audit`, `publication_outbox`. The `search_regconfig` GIN index is set to `english` for FTS on procedure titles and equipment names.

---

## 4. Ingestion

```python
result = await library.add_manual(
    "/mnt/manuals/assembly-guide.pdf",
    equipment=["Model X", "Model Y"],
    revision="B",
    source_uri="sharepoint://manuals/assembly-guide.pdf",
)
report = await library.add_video(
    "https://youtube.com/watch?v=abc123",
    manual_id="assembly-guide",
    transcript=None,  # let the loader extract
)
report = await library.refresh("assembly-guide", source="/mnt/manuals/assembly-guide.pdf", revision="C")
```

**Supported formats:** `.md`, `.txt`, `.docx`, `.pdf` (text). Heading-less markdown and TXT are sectioned deterministically; text PDFs keep physical page anchors (`## Page N`).

**A scanned / image-only PDF is skipped with an explicit reason** — OCR is out of v1 scope, and a no-text PDF must never become an empty "successful" card.

**Ingestion flow:**
1. **sha256 dedup** — compare source bytes against existing cards; unchanged bytes are skipped.
2. **markdown extraction** — PDF via `pymupdf4llm` with `write_images=True`; DOCX via the existing heading promotion.
3. **PageIndex tree** — `create_tree` → `insert_markdown` → `get_tree` → `derive_toc`.
4. **figure extraction** — bboxes and caption regex → three-pass carding (header, per-procedure, deterministic `assemble_card`).
5. **vision captions** — capability-resolved `ask_to_image` for descriptive metadata.
6. **upload figures** — via `FileManagerInterface.upload_file`.
7. **carding** — `ManualCard` with procedures, steps, applicability, hazards, prerequisites, media refs.
8. **catalog upsert** — `ManualCatalogStore.upsert(card, version=…)`.
9. **graph publish** — `ManualGraphLoader.publish_all()`.
10. **tip re-link** — idempotent re-linking of `tech_tip_on` edges by `step.source_identity` → exact `content_hash` equality.
11. **verification queue** — entry for curator review.

**Video alignment flow:**
1. **transcript extraction** — `YoutubeLoader` / `VideoLocalLoader` whisper blocks (`start_seconds`/`end_seconds`/`text`).
2. **bm25s alignment** — step ↔ block alignment with ordinal hints.
3. **media nodes** — `Media(kind="video_segment", uri, t_start, t_end)` above threshold; below threshold an LLM-judged tail with a judgement log and `--force` (bookstore `relate_books` pattern).
4. **coverage < 30%** ⇒ procedure-level `role="overview"` only.

---

## 5. Curation

```python
await library.verify_procedure("assembly-guide", "step-1-assembly")
await library.queue(limit=50)  # list verification queue
await library.relink_tips("assembly-guide")
```

**Verification:** curators mark procedures as verified after confirming steps, hazards, prerequisites, and media. A procedure with missing required fields or unsupported critical fields is blocked from release.

**Queue:** the verification queue lists procedures awaiting curator review. Curators can filter by equipment, revision, or status.

**Tip re-linking:** tips survive re-ingest through immutable step identity. The `relink_tips` operation:
- Matches `step.source_identity` → exact `content_hash` equality.
- Re-attaches `tech_tip_on` edges to the new step.
- Orphaned tips (no matching step) are marked `orphaned=true` with their source revision.
- Curator candidates (rapidfuzz on text, never on hashes) are surfaced for manual review.

**Applicability:** serial-qualified steps carry `Applicability(models[], serial_ranges[])` with evidence. Curators can review and correct applicability ranges.

**Hazards and prerequisites:** hazards and prerequisites are extracted with evidence and can be verified by curators.

---

## 6. Answering and channels

**Answer flow:**
1. `ProceduresAgent.ask()` → transport adapter → `ProceduresAnswerService.answer()`.
2. `ProcedureRetrieval.authorize` — tenant-scoped role check (technician for reads, curator for writes).
3. **Hybrid entry resolution** — catalog FTS on equipment/procedure names with `rapidfuzz`, `Clarification` when ambiguous; PageIndex `search` over the manual tree as fallback.
4. **Deterministic trigger-table plan** — AQL traversal.
5. **`assemble_procedure`** — ordered steps, prerequisites, hazards, media refs, citations from the selected revision.
6. **`ProcedureVerifier`** — completeness + evidence; a missing required step or unsupported critical field **blocks** release as a complete procedure.
7. **Audit row** — every outcome, including denials.
8. **Presign media** — 15-min URLs for figures and video segments.
9. **Released `ProcedureAnswer`** wrapped in an `AIMessage` carrying `image_urls` / `media_urls` (M12).

**Guided mode:**
- `proc_start_guided` — begins a task with a procedure, steps, and plan_complete=True.
- `proc_next_step` / `proc_mark_done` — wrap `update_step` / `set_resume_hint`.
- `proc_resume` — uses `recall_task` + `select_task` with the durable `TaskAssociationStore` so "¿dónde me quedé?" works the next day.
- Completion records `record_episode(category=EpisodeCategory.WORKFLOW_PATTERN, metadata={procedure_id, manual_id, revision})`.

**Channel media behaviour:**
- **Teams:** renders `image_urls[:3]` as `ImageSection` entries and links the overflow with their labels.
- **Slack:** renders every URL as an image block.
- **Telegram:** downloads each URL to a bounded temp file (allowlisted hosts from `PARROT_MEDIA_URL_HOSTS`, redirect validation, size/time caps, cleanup) and reuses `send_photo(FSInputFile)`.
- **WhatsApp:** passes the URL straight to `client.send_image(image=url)` (the `chart.public_url` precedent) and falls back to download on provider rejection.

**Completeness gate:** an answer is only released if all required steps are present and all critical fields (hazards, prerequisites, media) are substantiated. An incomplete answer carries a `incomplete` flag and a reason.

**Guided mode:** the guided mode composes task memory; episodes use `WORKFLOW_PATTERN`.

---

## 7. Offline export

```python
await library.export("assembly-guide", out_dir="/tmp/export", include_tips=True, zip_bundle=True)
```

**Bundle layout:** `<manual_id>-<revision>.bundle/`:
- `manifest.json` — manual/revision/generated_at/sha256s, files dict (relative path → sha256).
- `procedures.json` — steps, applicability, hazards, prerequisites, media roles, active tips.
- `captions.json` — figure captions.
- `videos.json` — video segments with URIs + `t_start`/`t_end`.
- `figures/<media_id>.png` — figures downloaded from storage.
- Optional `.zip` — zipped bundle.

**No presigned URLs, no graph internals.** The bundle is self-contained and authorized as a curator action.

**Curator-only:** export requires the `manual_curator` role.

---

## 8. Spike gate

The four spikes (figure pairing, media round-trip, video alignment, tip survival) are the first milestone (M0) and gate M5–M9 sign-off. Spike reports are written under `artifacts/logs/FEAT-601/`.

**Spike thresholds:**
- **Figures:** ≥ 90% steps in order with no missing required step and ≥ 80% correct primary figure on captioned figures.
- **Video:** ≥ 70% of steps get a segment containing the demonstrated action.
- **Tips:** 3/3 re-link outcomes exactly as expected.
- **Media:** one figure delivered on Teams, WhatsApp and Telegram.

**Spike corpus:** the owner-supplied corpus carries an `expected.json` of hand counts (per `corpus_dir_from_env`'s documented convention); `tips`/`media` additionally read their `revisions`/`answer`+`channels` from that same file so every spike kind shares one `--corpus` contract.

**Spike commands:**
```bash
parrot manuals spike figures --corpus /path/to/corpus
parrot manuals spike media --corpus /path/to/corpus
parrot manuals spike video --corpus /path/to/corpus
parrot manuals spike tips --corpus /path/to/corpus
```

**Spike reports:** each spike writes a JSON report to `artifacts/logs/FEAT-601/<spike_name>-<timestamp>.json` with pass/fail status, counts, and any errors.

**Spike gate acceptance:** all four spikes must pass before M5–M9 sign-off. Spike reports are reviewed by the owner; automated tests passing is not spike acceptance.

---

## 9. v1 limitations

- **OCR:** no OCR for scanned / image-only manuals — refused with a clear message in v1 (`PDFLoader.is_image_only` semantics kept). Image-only PDFs are skipped with an explicit reason.
- **Callouts:** exploded-view callouts are gated on spike 1 passing. Until then, callouts are disabled.
- **Serial applicability semantics:** unknown applicability ⇒ the step is shown with an explicit applicability note (not hidden, not dropped).
- **Offline viewer:** the per-device offline viewer that consumes the export bundle (G12) is not included in v1. The bundle format is in scope, the app is not.

---

## 10. Command reference

```bash
# Ingest
parrot manuals add <source> --equipment <eq> --revision <rev> [--source-uri <uri>] [--force]
parrot manuals add-video <url> --manual <id> [--transcript <file>] [--force]
parrot manuals refresh <manual_id> <source> --revision <rev>

# Curation
parrot manuals verify <manual_id> <procedure_id>
parrot manuals queue [--limit <n>]
parrot manuals relink-tips <manual_id>

# Export
parrot manuals export <manual_id> --out <dir> [--zip/--no-zip] [--include-tips/--no-include-tips]

# Spike gate
parrot manuals spike <name> --corpus <path>
```

**Options:**
- `--tenant <id>` — tenant id (required).
- `--user <id>` — authenticated operator id (required).
- `--role <role>` — role granted by the deployment (repeatable, required for state-changing commands).
- `--dsn <dsn>` — Postgres DSN (default: `GRAPHINDEX_PG_DSN` env var).
- `--storage-root <path>` — storage root for figures (default: `manuals_storage`).
- `--evidence-root <path>` — evidence root for archives (default: `manuals_evidence`).

**Exit codes:**
- `0` — success.
- `1` — failure (including a partially failed publication).
- `2` — refused (missing `--confirm`, bad argument).
- `3` — denied (authorization).
- `4` — audit outage.

**Deployment configuration lives outside the package — wire it once:**
```python
from parrot_tools.procedures.cli import main
raise SystemExit(main(factory=build_manual_services))
```
