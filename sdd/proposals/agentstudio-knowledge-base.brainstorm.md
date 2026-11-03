---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, ai-parrot-loaders, ai-parrot-embeddings, ai-parrot-tools]
tags: [agentstudio, knowledge-base, pgvector, loaders, multi-tenant, rag]
---

# Brainstorm: Agent Studio Knowledge Base (tenant collections, opt-in per agent)

**Date**: 2026-11-02
**Author**: Juan Ruffato (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Agents built in Agent Studio cannot have a knowledge base. A Studio agent's definition
(`StudioAgentDefinition`) carries only `llm`, `model_params`, `system_prompt`, `tools` and a
`config` dict. `vector_store_config` is refused outright (`STUDIO_FORBIDDEN_CONFIG_KEYS`), and
tenants may pass no config keys at all (`STUDIO_TENANT_CONFIG_KEYS = frozenset()`). The live
toolkit-assignment path can attach the LLM-Wiki/PageIndex toolkits, but those store on the pod's
local disk. That storage is lost on restart, and tenant allow-lists usually forbid those toolkits anyway.

The trigger is a real production agent. `verizon360bot` (tenant `verizon360`, prod) must answer
field-team questions whose source of truth is a set of **Gamma.app** documents. Those documents are
linked from a **SharePoint site page**
(`symbits.sharepoint.com/sites/wedevelopulearningdevelopmentcommunity/SitePages/Verizon(1).aspx`),
which also links **Smartsheet** forms. Pasting the content into the system prompt was considered
and rejected as non-scalable. The same SharePoint site holds 104 pages, roughly one per program
(Apple, Assurant, Automated Retail…), so the need repeats for other tenants.

Who is affected:
- Studio authors, who want to give an agent a curated body of knowledge.
- End users chatting with those agents.
- Ops, who need ingestion that survives restarts and stays tenant-isolated.

## Constraints & Requirements

Decisions taken with Juan on 2026-11-02:
- **Ownership**: knowledge lives in **collections owned by the tenant**.
- **Opt-in**: an agent opts in to zero or more collections. The default is none, so adding
  content to a collection never "contaminates" an agent that did not attach it. Agent-private
  knowledge is simply a collection only that agent attaches. There is no second mechanism.
- **Authoring**: tenant admins **and agent authors** can create collections and add sources.
  Attaching collections is part of editing an agent.
- **Storage**: **pgvector**, in the same Postgres as Studio. Prod has extension `vector` 0.8.0
  installed. The DSN is always server-side; no client ever supplies a DSN, schema or table.
- **Embedding model**: chosen by the creator **per collection**, from a catalogue of available
  models, and fixed for the life of the collection. Dimension is fixed per vector table.
- **Retrieval mode per agent**: `off` / `tool` (the agent calls a search tool) / `auto`
  (retrieved chunks are injected every turn), plus `top_k` and a minimum relevance threshold.
- **Freshness**: a **re-sync button per source**. There is no scheduled refresh in v1. Re-sync
  replaces only that source's chunks.
- **Tenant availability**: available to **every tenant** with Studio. No ops setting gates it.
- **v1 source kinds**:
  - Gamma link
  - generic URL
  - uploaded file (PDF, DOCX, PPTX, MD; images)
  - SharePoint page
  - SharePoint library file or folder
  - Smartsheet sheet or report
  - **reference links**: Smartsheet forms and any link we cannot read are kept as a citation
    chunk (link text, surrounding heading, URL) so the agent can point users to them.
- **Images**: described with a vision model at ingest, behind a **per-source toggle**. It is on
  by default for Gamma and SharePoint pages and off for generic URLs.
- **Multi-tenant isolation**: every read and write is partitioned by tenant, the same way
  `ai_agents` is (`StudioPartition`).
- **Durability**: ingestion state survives pod restarts. Today `JobManager` jobs are in-process
  unless a Redis store is passed.
- **Migrations**: Studio storage migrations are applied **by Juan**, never by CI.
- **Legacy**: `ai_bots` stays untouched. The legacy `VectorStoreHandler` must not be exposed to
  tenants, because the client chooses table, schema and DSN there.

---

## Options Explored

### Option A: Studio-native knowledge collections on pgvector

Studio gains first-class **collections** and **sources**, stored in new Studio storage tables
(migrations 0009+). Each collection owns its own pgvector table, named by the server and created
with the collection's embedding dimension. A **durable ingestion worker** processes sources. Its
state machine lives in the `sources` table, not in memory:
1. fetch through the right loader;
2. chunk;
3. embed;
4. optionally run a second phase that describes images with a vision model;
5. atomically replace that source's chunks.

The `StudioAgentBuilder` reads the agent's knowledge settings and wires retrieval **server-side**.
In `auto` mode it configures the bot's vector context for the attached collections. In `tool` mode
it registers a search tool bound to those collections. When the attached collections use different
embedding models, it fans out across them through the existing multi-store machinery.

New parrot loaders:
- **Gamma**: a port of flowtask's `GammaClient`, extended to keep link and button `href`s and
  image references.
- **SharePoint page**: reads the Graph `sitePage` and `canvasLayout`, extracts text and links, and
  turns recognised links into **child sources**.
- **SharePoint file**: reuses `SharePointFileManager`.
- **Smartsheet**: sheet/report export with the existing API key. Forms become reference sources.

✅ **Pros:**
- Matches every decision above: tenant-owned, opt-in, per-collection model, per-agent mode,
  per-source re-sync.
- Tenant isolation by construction. The server names tables and owns the DSN, and the forbidden
  `vector_store_config` key stays forbidden for clients.
- It is built from parts that already exist: `PgVectorStore`, the loaders, `get_vector_context`,
  `VectorStoreSearchTool`, `SharePointFileManager` and `ImageUnderstandingLoader`.
- It rides Studio's existing rebuild path: a version bump makes `StudioAgentRuntime` rebuild the bot.

❌ **Cons:**
- It is the largest option: new tables, a worker, endpoints, a builder hook, four loaders and a
  separate Svelte feature.
- One table per collection means many small tables per tenant, so table and index housekeeping
  is needed.
- Gamma depends on an unofficial GraphQL API, and Cloudflare may challenge datacenter IPs.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pgvector` 0.8.0 (Postgres ext.) | vector storage | already installed in prod `navigator_production` |
| `ai-parrot-embeddings` `PgVectorStore` | store, search, atomic replace | `add_documents(metadata_filters=…)` replaces in one transaction |
| `google-genai` 2.23.0 | vision descriptions + Google embeddings | `GOOGLE_API_KEY` present in the prod Studio Vault |
| OpenAI embeddings | alternative embedding provider | `OPENAI_API_KEY` present in the prod Studio Vault |
| `msgraph-sdk` (via parrot O365 interfaces) | SharePoint files and pages | app credentials `SHAREPOINT_APP_*` work against tenant `symbits` |
| `aiohttp` | Gamma GraphQL client | the flowtask client is pure aiohttp |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-embeddings/src/parrot/stores/postgres.py` — `PgVectorStore`.
- `packages/ai-parrot-server/src/parrot/manager/studio_builder.py` — `StudioAgentBuilder._constructor`,
  the hook point.
- `packages/ai-parrot/src/parrot/bots/abstract.py` — `get_vector_context` / `_build_vector_context`.
- `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py` — `VectorStoreSearchTool`.
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/` — fan-out across collections that
  use different models.
- `packages/ai-parrot-loaders/src/parrot_loaders/` — pdf/docx/ppt/markdown/web loaders,
  `imageunderstanding.py`.
- `packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py` — `SharePointFileManager`.
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/smartsheet.py` — Smartsheet access.
- flowtask `flowtask/interfaces/gamma.py` — `GammaClient`, `snapshot_to_markdown` (to port).

---

### Option B: Unlock per-agent `vector_store_config` over the legacy `VectorStoreHandler`

Allow Studio agents to carry a `vector_store_config` that the server fills: the DSN plus a
per-agent table. Content is loaded through the existing `PUT /api/v1/ai/stores` handler (file
upload and URL scraping). The bot's native `use_vectorstore` path does automatic RAG.

✅ **Pros:**
- Least new code: the factory already maps `vector_store` to `vector_store_config` +
  `use_vectorstore=True`.
- The upload and URL-scraping UI already exists in Svelte (`src/lib/api/stores.ts#loadUrls`).

❌ **Cons:**
- `VectorStoreHandler` has **no tenant or permission scoping**, and the caller picks table, schema
  and even DSN. Exposing it to tenants is a security hole.
- There is **one store per bot**: no shared collections and no opt-in. This contradicts the
  ownership decision.
- Jobs are in memory (24 h TTL), so a restart loses ingestion state. There is no per-source registry,
  so re-sync means a full reload.
- There is no `tool` mode or per-agent mode switch, and no Gamma or SharePoint-page support.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ai-parrot-server` `VectorStoreHandler` | ingestion | default embedding `thenlper/gte-base` (local HF, CPU) |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/stores/handler.py` — the PUT/POST/PATCH handlers.
- `packages/ai-parrot/src/parrot/registry/registry.py:903` — `create_agent_factory`.

---

### Option C: Persisted LLM-Wiki / PageIndex knowledge instead of vectors

Make the existing `wiki` toolkit assignment persistent, and move its storage off the pod onto a
durable backend: ArangoDB for the wiki store, and object storage for the PageIndex trees. Each
collection becomes a wiki or PageIndex bundle that agents query through `LLMWikiToolkit` /
`PageIndexToolkit`.

✅ **Pros:**
- Structure-aware retrieval (a document tree with section navigation) that suits long training
  guides.
- Toolkits are already assignable in Studio, and PageIndex/GraphIndex already exist.

❌ **Cons:**
- It contradicts the pgvector decision, and PageIndex ingestion is LLM-heavy, so it is slow and
  costs more per document.
- It needs a new durable storage backend in prod for each plane.
- There is no `auto` mode. It is tool-only.
- Re-sync per source and the image pipeline would still have to be built.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.knowledge.wiki` / `pageindex` / `graphindex` | knowledge planes | storage is local disk today |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` — `_assign_wiki` (live only).

---

### Option D (unconventional): Flowtask-driven ingestion, Studio holds only the registry

Studio stores collections, sources and agent attachments, but ingestion runs as **Flowtask
pipelines** dispatched through qworker. The pipelines reuse `DownloadFromGamma`,
`DownloadFromSharepoint` and `DownloadFromSmartsheet`, and their last step writes into the
collection's pgvector table. Retrieval wiring in the builder is the same as in Option A.

✅ **Pros:**
- Reuses mature download components as they are, including batch mode.
- Heavy ingestion runs outside the API pods.

❌ **Cons:**
- It couples Studio to Flowtask and qworker deployment, which crosses repos and services, and
  per-source status has to round-trip back into Studio.
- The Gamma and SharePoint-page link and image extraction still has to be built, in Flowtask
  instead of in parrot.
- It is harder to test end to end, and harder to give the re-sync button an immediate status.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `flowtask` | download components | `DownloadFromGamma` (FEAT-028, by William Cabrera) |
| `qworker` | job dispatch | separate deployment |

🔗 **Existing Code to Reuse:**
- flowtask `flowtask/components/DownloadFromGamma.py`, `DownloadFromSharepoint.py`,
  `DownloadFromSmartsheet.py`.

---

## Recommendation

**Option A** is recommended because it is the only option that satisfies every decision taken with
Juan:
- tenant-owned collections with explicit opt-in;
- an embedding model per collection;
- an `off`/`tool`/`auto` mode per agent;
- per-source re-sync;
- strict tenant isolation.

It does this without inventing new infrastructure: pgvector is already installed in prod, both
embedding keys are already in the Studio Vault, and the SharePoint app already reaches the page.

What we trade off:
- **Effort.** Option A is the largest. Most of that effort is glue over existing parrot parts, and
  the riskiest parts were de-risked on 2026-11-02:
  - Graph read the Verizon page and its 6 Gamma links.
  - All 6 Gamma docs are public and fetched cleanly (~12.7k words).
  - A vision probe on real Gamma images produced high-value descriptions (an org chart and a dress
    code that exist only as images) at about 1.3k input and 0.36k output tokens per image.
- **What we drop.** Option B is rejected for security: the client picks the DSN, schema and table.
  It also rejected the sharing model. Option C is rejected because it is not vector based and has no
  `auto` mode. Option D is rejected for cross-service coupling. Flowtask's Gamma code is *ported*
  into a parrot loader instead.

---

## Feature Description

### User-Facing Behavior

**Knowledge section** (tenant-scoped, visible to Studio authors):
- **Create a collection**: name, description, embedding model picked from a catalogue of available
  models (provider, model, dimension), and an image-description default.
- **Add sources to a collection**:
  - paste a Gamma link
  - paste a URL
  - upload files
  - paste a SharePoint page or library URL
  - paste a Smartsheet link
- **Source list**: each source shows kind, title, status (`pending`, `fetching`, `indexed`,
  `indexed_with_warnings`, `failed`), chunk count, image progress (e.g. "images 12/19"), last
  synced time and error text.
- **Per-source actions**: **Re-sync** and **Remove**, plus the "describe images" toggle.
- **SharePoint page sources** expand into child sources: the Gamma, SharePoint-file and Smartsheet
  links found on the page. Unreadable links (Smartsheet forms, unknown hosts) appear as
  `reference` sources.

**Agent → Knowledge tab**:
- Attach and detach the tenant's collections (none by default).
- Choose the retrieval mode: `off` / `tool` / `auto`.
- Set `top_k` and the minimum relevance threshold.
- Saving bumps the agent version, and the live bot is rebuilt.

**Chat**: answers grounded in the attached collections. Reference sources let the agent say "use
this form: <link>". Image-derived chunks carry the image URL so the agent can cite it.

### Internal Behavior

1. **Registry** (Studio storage, tenant-partitioned):
   - `collections`: tenant, name, embedding model and dimension, server-named vector table, owner.
   - `sources`: collection, kind, URI, parent source, title, status, content hash, last synced,
     error, image toggle, image counters.
   - `agent_collections`: the agent↔collection links.
   - Knowledge settings on the agent: mode, top_k, threshold.
   - An image-description cache: tenant, image hash, model, prompt version → description.
2. **Ingestion worker**. It claims `pending` sources, fetches them through the loader for their
   `kind`, chunks, embeds, and writes with `PgVectorStore.add_documents(..., metadata_filters=
   {"source_id": …})`, an atomic delete-and-insert. Chunk metadata stamps `tenant`,
   `collection_id`, `source_id`, `parent_source_id`, `kind` (`text` | `image_description` |
   `reference`) and the origin URL.
   - **Phase 1 (text)** finishes first, and the source becomes `indexed` and queryable.
   - **Phase 2 (images)** downloads each kept image and calls the vision model with the slide or
     section context, using the cache keyed by hash. It then indexes the description chunks.
   - State lives in `sources`, so on restart, sources left mid-flight are reclaimed.
3. **Loaders** (new, in `ai-parrot-loaders`):
   - `GammaLoader`: the port of flowtask's `GammaClient`, extended to keep link and button `href`s
     (as child-source candidates) and image `src` plus Gamma image type.
   - `SharePointPageLoader`: Graph `sites/{host}:/sites/{site}`, then `pages`, then
     `microsoft.graph.sitePage?$expand=canvasLayout`; extracts the text web-parts and links.
   - SharePoint library files go through `SharePointFileManager`, then the loader for the file
     extension.
   - `SmartsheetLoader`: sheets and reports through `SMARTSHEET_API_KEY`. `/b/form/` links become
     `reference`.
   - An `ImageDescriber` service that wraps the vision call. It is reusable by any loader that
     yields image references.
4. **Image selection rules**. These were learned from the probe:
   - Describe Gamma `image.custom`.
   - **Always skip `image.ai-generated`**: the probe showed the model will happily describe a
     decorative illustration instead of answering `DECORATIVE`, so filter by source type before
     calling the model.
   - Skip nodes without `src`, tiny icons and duplicates (by hash).
   - Untyped images: see Open Questions.
5. **Builder wiring** (`StudioAgentBuilder`). If the agent has collections and a mode other than
   `off`, the server constructs the store config: server DSN, the collection's table, and a
   metadata filter on `collection_id`.
   - `auto`: sets the bot's vector context (the `vector_store_config` + `use_vectorstore` channel
     the registry factory already maps), with `top_k` and the threshold as bot defaults.
   - `tool`: registers a server-bound search tool. Its LLM-facing args do not include
     store/DSN/filters.
   - Several collections with different models: fan out across them (MultiStoreSearch).
   - The knowledge capability is server-wired, outside client-supplied tooling, so tenant tool
     allow-lists are not involved (decision: available to every tenant).
6. **Endpoints**. These are Studio CBVs under `/api/v1/astudio/knowledge/...`: collections CRUD,
   sources CRUD + re-sync, the embedding-model catalogue, and the agent knowledge settings. All go
   through Studio access checks and `StudioPartition`.

### Edge Cases & Error Handling

- **Gamma**:
  - A 403 means "not public": the source fails with a clear message, and there is no password
    support.
  - A Cloudflare challenge from prod IPs has to be verified from the pod. If it fails, the error
    must be explicit and must not loop retries.
  - Snapshot `content` may be a string or an object, possibly under `default`.
- **SharePoint**:
  - Page links can loop between pages, so dedupe by normalised URL inside the collection and cap
    the expansion depth (1 by default).
  - The prod app is over-privileged (`Sites.ReadWrite.All`, `Sites.Manage.All`,
    `Files.ReadWrite.All`). Ingestion only needs `Sites.Read.All` or `Sites.Selected`.
- **Re-sync while in flight**: refuse, or queue one rerun. Never run two concurrent writers on the
  same `source_id`.
- **Removing a source** deletes its chunks and its child sources. Removing a collection drops its
  table and detaches it from agents, bumping their versions.
- **Embedding model unavailable** (missing key): refuse collection creation up front. The catalogue
  only lists models whose credentials are configured.
- **Upstream bugs to work around**:
  - `PgVectorStore` delete-by-filter helpers default to the wrong column
    (`metadata_column or self._document_column`): pass `metadata_column='cmetadata'` or fix it.
  - `ask()` raises any `limit <= 5` to 10: the per-agent `top_k` must not be silently overridden.
- **Privacy**: image descriptions transcribe what is visible, including employee names in org
  charts. This is acceptable for internal tenant bots, but it is the author's toggle.
- **Vision call fails**: that image is marked failed, the source becomes
  `indexed_with_warnings`, and the image is retried on the next re-sync. Text is never blocked.

---

## Capabilities

### New Capabilities
- `studio-knowledge-collections`: tenant-owned collections and sources registry, plus endpoints.
- `studio-knowledge-ingestion`: durable worker, two-phase ingest, atomic per-source re-sync.
- `studio-agent-knowledge-settings`: agent↔collection attachment, plus mode/top_k/threshold wired
  in `StudioAgentBuilder`.
- `gamma-loader`: Gamma.app documents → Markdown + links + image references.
- `sharepoint-page-loader`: SharePoint site pages → text + links (child sources).
- `smartsheet-loader`: sheets/reports → documents; forms → reference sources.
- `image-describer`: contextual vision descriptions with a hash cache.
- `embedding-model-catalogue`: available embedding models per configured credentials.

### Modified Capabilities
- `agentstudio-db-storage` — new Studio storage tables (migrations 0009+).
- Studio agent definition — knowledge settings are added server-side. `vector_store_config` stays
  forbidden for clients.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `ai-parrot-server` `handlers/studio/storage` | extends | new tables + repositories + migrations 0009+ (applied by Juan) |
| `ai-parrot-server` `manager/studio_builder.py` | modifies | `_constructor` wires knowledge server-side |
| `ai-parrot-server` `handlers/studio/` | extends | new knowledge CBVs, ingestion worker startup |
| `ai-parrot-loaders` | extends | Gamma, SharePoint page, Smartsheet loaders |
| `ai-parrot-embeddings` `PgVectorStore` | depends on / small fix | delete-by-filter default column |
| `ai-parrot` `bots/base.py` | small fix | `limit <= 5 → 10` override vs per-agent top_k |
| navigator-svelte | separate feature | Knowledge section + agent Knowledge tab (own spec and FEAT-ID) |
| navigator-agent-studio | config only | Vault already has the Google/OpenAI/SharePoint/Smartsheet keys; CORS unchanged |
| Prod Postgres | new tables | `vector` 0.8.0 present |

---

## Code Context

### User-Provided Code

None. The design decisions were given verbally (see Constraints).

### Verified Codebase References

Verified against `origin/dev` @ `9764d91f01` on 2026-11-02.

#### Classes & Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/storage/models.py
STUDIO_TENANT_CONFIG_KEYS: Final[frozenset[str]] = frozenset()          # :19
STUDIO_FORBIDDEN_CONFIG_KEYS: Final = frozenset({..., "vector_store_config"})  # :20-31 ("vector_store_config" at :29)
class StudioAgentDefinition(BaseModel):                                  # :122  extra="forbid"
    # config validator rejects forbidden/moved keys at :143

# packages/ai-parrot-server/src/parrot/manager/studio_builder.py
class StudioAgentBuilder:                                                # :52
    async def build(self, snapshot, app, *, part) -> tuple[AbstractBot, Path]  # :63
    def _constructor(self, snapshot: StudioAgentSnapshot) -> tuple[BotConfig, dict[str, Any]]  # :104
        # BotConfig(..., model=None, config={}, startup_config={}) — no vector_store set (:117-122)
    def _stamp_and_bind(...)                                             # :171

# packages/ai-parrot-server/src/parrot/manager/studio_runtime.py
class StudioAgentRuntime:                                                # :71
    async def reload(self, key: StudioAgentKey) -> ReloadResult          # :288

# packages/ai-parrot/src/parrot/registry/registry.py
def create_agent_factory(self, config: BotConfig) -> AgentFactory        # :903
    # if config.vector_store: merged_args["vector_store_config"] = asdict(...); ["use_vectorstore"] = True  (:984-985)

# packages/ai-parrot-embeddings/src/parrot/stores/postgres.py
class PgVectorStore(AbstractStore):                                      # :49
    async def add_documents(self, documents, table=None, schema=None, embedding_column='embedding',
                            content_column='document', metadata_column='cmetadata',
                            metadata_filters: Optional[Dict[str, Any]] = None, **kwargs) -> None  # :579
        # metadata_filters given → delete matching + insert in one transaction
    async def similarity_search(self, query, table=None, schema=None, k=None, limit=None,
                                metadata_filters=None, score_threshold=None, metric=None, ...,
                                include_parents=False) -> List[SearchResult]          # :766
    async def delete_documents_by_filter(...)                            # :2338
    # BUG: metadata_column = metadata_column or self._document_column or 'cmetadata'  (:2280, :2379, :2589)

# packages/ai-parrot/src/parrot/bots/abstract.py
self._use_vector: bool = kwargs.get("use_vectorstore", False)            # :601
def configure_store_router(...)                                          # :3152
async def get_vector_context(self, question, search_type="similarity", search_kwargs=None,
                             metric_type="COSINE", limit=10, score_threshold=None,
                             ensemble_config=None, return_sources=False, expand_to_parent=None) -> str  # :3287
async def _build_vector_context(...)                                     # :4040

# packages/ai-parrot/src/parrot/bots/base.py
#   if limit <= 5: ... (raised to 10)                                    # :1241

# packages/ai-parrot/src/parrot/tools/vectorstoresearch.py
class VectorStoreSearchTool(AbstractTool):                               # :48
    def __init__(self, store_config: StoreConfig, name=None, description=None,
                 additional_columns=None, content_column='document', embedding_column='embedding',
                 metadata_column='cmetadata', id_column='id', **kwargs)  # :76

# packages/ai-parrot/src/parrot/loaders/abstract.py
class AbstractLoader(ABC):                                               # :100
    async def _load(self, source: str | PurePath, **kwargs) -> list[Document]   # :485 (abstract)
    def create_metadata(...)                                             # :835
    def create_document(self, content, path, metadata=None, **kwargs) -> Document  # :939

# packages/ai-parrot-loaders/src/parrot_loaders/imageunderstanding.py
class ImageUnderstandingLoader(AbstractLoader):                          # :82
    # model: str = "gemini-3.1-flash-image" (:98) — local paths only; no surrounding-context input

# packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py
class SharePointFileManager(GraphDriveFileManager):                      # :12  (site/library/path; no sitePage)

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py
class JobManager:                                                        # :22  (optional RedisJobStore, :19)

# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py
async def put_toolkit(...)                                               # :337  (persisted ai_agent_tooling; bumps version)

# packages/ai-parrot/src/parrot/tools/tooling_policy.py
class TenantToolingPolicy(BaseModel, frozen=True):                       # :135
    def check_tool(self, slug: str, *, subject: ToolingSubject) -> None  # :164
```

```python
# flowtask (separate repo) — flowtask/interfaces/gamma.py (port source, not importable from parrot)
GRAPHQL_URL = "https://api.gamma.app/graphql"
def extract_doc_id(url_or_slug) -> str
def text_from_inline(nodes) -> str        # ignores `link` marks (href lost)
def node_to_md(node, depth=0) -> str      # no image/embed handler
def snapshot_to_markdown(title, snapshot_content) -> str
class GammaClient(CredentialsInterface):  # warm_up(url), get_document(doc_id), get_snapshot(snapshot_id), close()
# flowtask-specific deps to replace when porting: ComponentError, CredentialsInterface
```

#### Key Attributes & Constants
- Studio storage migrations present: `0001`–`0008` in
  `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/`. New work starts at `0009`.
- Gamma image node attrs: `src` (on `cdn.gamma.app`), `source` ∈ {`image.custom`,
  `image.ai-generated`, missing}, `meta` (width/height). Button nodes carry `href`.
- Prod Studio Vault (`navapi/agentstudio-production`) key **names** present: `OPENAI_API_KEY`,
  `GOOGLE_API_KEY`, `SHAREPOINT_APP_ID/SECRET/TENANT_ID/TENANT_NAME(=symbits)`,
  `SMARTSHEET_API_KEY`. `O365_*` credentials return `invalid_client`.

### Probe Evidence (2026-11-02, read-only)
- Graph app token roles: `Sites.Read.All`, `Sites.ReadWrite.All`, `Sites.Manage.All`,
  `Files.ReadWrite.All`, `Sites.Selected`.
- The Verizon page (last modified 2026-10-20) is readable with `$expand=canvasLayout`. It has 17
  links: 6 `gamma.app`, 3 `app.smartsheet.com/b/form/…`, plus internal Graph and CDN links.
- The 6 Gamma docs are all public: 508 / 793 / 2,306 / 7,983 / 1,100 / 42 words. The 42-word
  "WWU EBook" is made of `button` nodes whose `href`s hold the content.
- Real images (with `src`) total about 19 across the 6 docs.
- Vision probe with `gemini-3-flash-preview` on 4 images: ~1.27k input and ~0.36k output tokens
  each. `image.custom` images yielded org-chart and dress-code content absent from the text. The
  `image.ai-generated` image was decorative but was described anyway.

### Does NOT Exist (Anti-Hallucination)
- ~~A Studio "collection" / "knowledge base" entity, table or endpoint~~.
- ~~An agent↔collection mapping, or per-agent retrieval mode / top_k / threshold in Studio~~.
- ~~A source registry for pgvector (source URI, status, last synced, hash)~~. The wiki SQLite
  `sources` table and the contracts catalog are unrelated.
- ~~Durable ingestion job status~~. `JobManager` is in-memory unless given a `RedisJobStore`, and
  `VectorStoreHandler` passes none.
- ~~Tenant/permission scoping in `VectorStoreHandler`~~.
- ~~Upsert by id in `PgVectorStore`~~. `add_documents` always assigns a fresh uuid4.
- ~~A Gamma loader, a SharePoint *site page* reader (`sitePage`, `canvasLayout`, `webParts`), or
  SharePoint sharing-URL (`/shares/u!…`) resolution~~ in parrot. A grep of `packages/` returns
  nothing.
- ~~Href/link or image extraction in flowtask's Gamma converter~~.
- ~~A score threshold in `MultiStoreSearchToolkit` / `VectorStoreOrigin`~~.
- ~~A per-agent default for `use_vector_context`~~. `ask()` always defaults it to `True`.

---

## Parallelism Assessment

- **Internal parallelism**: high. The loaders (Gamma, SharePoint page, Smartsheet) and the image
  describer are independent of each other and of the registry, so each can be its own worktree.
  Registry + migrations, then the worker, then the builder wiring, then the endpoints form a chain.
- **Cross-feature independence**: it touches `studio_builder.py` and Studio storage models and
  migrations. Any in-flight Studio feature that adds migration `0009` or edits `_constructor`
  collides, so migration numbers must be reserved at spec time. The Svelte work is a separate
  feature with its own FEAT-ID.
- **Recommended isolation**: `mixed`.
- **Rationale**: the loaders are leaf modules with no shared files and parallelise cleanly. The
  storage → worker → builder → endpoints spine shares models and must run sequentially.

---

## Open Questions

- [x] Who owns knowledge: agent or tenant? — *Owner: Juan*: tenant-owned collections; agents opt in; default none; agent-private = a collection only that agent attaches.
- [x] Storage backend? — *Owner: Juan*: pgvector.
- [x] Retrieval mode? — *Owner: Juan*: configurable per agent (off / tool / auto) with top_k and threshold.
- [x] Freshness? — *Owner: Juan*: per-source re-sync button; no scheduler in v1.
- [x] Who manages collections? — *Owner: Juan*: tenant admins and agent authors can create collections and add sources.
- [x] SharePoint in v1? — *Owner: Juan*: yes, pages and library files (the existing Graph access works).
- [x] Embedding model? — *Owner: Juan*: chosen by the creator per collection from a catalogue of available models.
- [x] Gate per tenant? — *Owner: Juan*: no; available to all Studio tenants for now.
- [x] Smartsheet? — *Owner: Juan*: download and index sheets/reports; forms become reference sources.
- [x] Images? — *Owner: Juan*: describe with vision at ingest, per-source toggle (validated by the 2026-11-02 probe).
- [ ] Untyped Gamma images (no `source` attr, e.g. 5 in "Mileage/Navigator"): describe or skip by default? — *Owner: Juan*
- [ ] Vector table layout: one table per collection (proposed) vs one per (tenant, embedding model) with `collection_id` filter? — *Owner: spec*
- [ ] Where the ingestion worker runs: in-process in agentstudio-api with DB-claimed rows (proposed) vs qworker? — *Owner: Juan*
- [ ] Least-privilege SharePoint app (`Sites.Selected` on the WeDevelopU site) instead of the current over-privileged one? — *Owner: Juan / M365 admin*
- [ ] Gamma fetch from prod pod IPs: does Cloudflare challenge them? Verify before relying on it. — *Owner: spec / ops*
- [ ] Vision model default and the embedding catalogue contents (e.g. `gemini-3-flash-preview` vs newer `gemini-3.x-flash`; OpenAI `text-embedding-3-small` vs Google). — *Owner: spec*
- [ ] Quotas per tenant (max collections, sources, images per source, file size). — *Owner: Juan*
- [ ] Should the chat UI render cited images inline (v2 front work)? — *Owner: Juan*
