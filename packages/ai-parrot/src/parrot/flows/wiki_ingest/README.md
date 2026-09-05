# Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent (`wiki_ingest`)

**FEAT-481.** An async agent flow that faithfully executes the *Obsidian
LLM-Wiki operating contract* for Fireflies.ai meetings: it fetches meeting
transcripts + summaries, semantically **compiles** them into a
contract-structured Obsidian vault (canonical meeting pages, living project
pages, entity/concept pages, a daily diary, contradiction pages, indexes),
and keeps a derived GraphIndex/PageIndex plane for retrieval.

- **Spec (authoritative):** `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
  (see its **Amendments** section for post-implementation refinements).
- **Operating contract (acceptance oracle):** `sdd/references/obsidian-wiki-operating-contract.md`
- **Hard dependency:** FEAT-472 `MeetingRegistry` (id-keyed dedup).
- **Agent contract name:** `fireflies_wiki_kb` (`@register_agent`).

---

## The six intents

The agent (`agent.py:FirefliesWikiKBAgent`) exposes six plain-English intents:

| Intent | What it does | LLM? |
|---|---|---|
| `ingest` | The §27 workflow: fetch-gate → compile → §34 validate. Scheduled hourly via `@schedule(CRON)`. | yes |
| `query` | §28 retrieval: GraphIndex search → Obsidian verify. | yes (strong) |
| `health` | §29 fast operational health check. | no |
| `lint` | §30 integrity lint (optionally applies safe auto-fixes). | no |
| `archive` | §31 rolling active window (moves old daily notes + project meeting-index refs). | no |
| `build_graph_report` | §32 derived graph report. | no |

---

## Ingest pipeline (§27, per meeting, in order)

```
fetch-gate (dedup, participant filter, rate-limit-safe)
  → chronological sort (oldest → newest)
  → per meeting  (transactional: any failure rolls back all compiled writes)
      1. raw bundle capture         (Raw/Incoming → Raw/Processed, hashed, immutable)
      2. classify / categorize      (§15, summary-first)                 [STRONG]
      3. contradiction detection    (§22, vs existing project claims)    [STRONG]
      4. meeting source page        (§17)                                [CHEAP]
      5. project reconcile          (§16/§19, primary + additional)      [STRONG]
      6. entities + concepts        (§20/§21, ONE batched call)          [CHEAP]
      7. daily synthesis            (§23)                                [CHEAP]
      8. §34 post-op validation gate  → on failure: rollback + quarantine (Module 17)
      9. registry mirror + §33 log
  → indexes/overview (§18/§24)  → archive (§31)  → derived GraphIndex rebuild (§13)
```

**Model tiers (G7).** Two provider-agnostic `provider:model` clients:
- **Strong** (`WIKI_KB_LLM_STRONG`, default `google:gemini-2.5-pro`) — classification, contradiction reasoning, project reconciliation, overview materiality.
- **Cheap** (`WIKI_KB_LLM_CHEAP`, default `google:gemini-2.5-flash`) — meeting-page extraction, daily synthesis, and the **batched** entity/concept extraction.

---

## Directory layout

```
wiki_ingest/
├── agent.py            FirefliesWikiKBAgent façade — the six intents; builds the tier clients
├── runner.py           §27 ingest orchestrator + IngestProfile (full / backfill)
├── conf.py             all WIKI_KB_* config (navconfig, resolved at import)
├── vault.py            own ObsidianToolkit instance, §11 init, §25 mirror, §8.1 link-fixup
├── graph.py            derived GraphIndex/PageIndex plane (Module 13)
├── models.py           §10 frontmatter schemas (Pydantic)
├── validation.py       §34 post-operation validation (the executable QA oracle)
├── naming.py           §8.2 filename/id helpers
├── definition.py       flow definition wiring
├── nodes/              pipeline nodes:
│   ├── fetch_gate.py         dedup gate + rate-limit-safe paged fetch (max_new)
│   ├── classify.py           §15 summary-first classification
│   ├── meeting_page.py       §17 canonical meeting page extraction
│   ├── project_reconcile.py  §16/§19 diff-guarded project reconciler
│   ├── entities.py           §20 entity resolver (match-before-create)
│   ├── concepts.py           §21 concept resolver
│   ├── entity_concept_batch.py   ONE cheap-tier call for all entities+concepts (cost)
│   ├── contradictions.py     §22 contradiction protocol
│   ├── daily.py              §23 daily diary synthesis
│   ├── indexes.py            §18/§24 project meeting indexes + wiki index + overview
│   ├── review_queue.py       §26 Review Queue (ALLOWED_REVIEW_TYPES)
│   ├── log.py                §33 operation log
│   ├── raw_bundle.py         §13/§14 immutable raw capture + hashing
│   ├── quarantine.py         Module 17 failure quarantine / bounded reprocess
│   ├── archive.py            §31 rolling active window
│   ├── health.py / lint.py / graph_report.py / query.py / email.py
│   └── ...
└── render/             deterministic §19/§17/§20/§21/§23 page renderers + parsers
```

The agent **never** emits page Markdown from the LLM (§3.1): the LLM returns
typed structured fields; `render/` writes the pages deterministically.

---

## Configuration (`WIKI_KB_*`, via navconfig / `env/.env`)

| Key | Default | Purpose |
|---|---|---|
| `WIKI_KB_VAULT_PATH` | *(required)* | Absolute path to your Obsidian vault |
| `WIKI_KB_LLM_STRONG` | `google:gemini-2.5-pro` | Strong tier (`provider:model`) |
| `WIKI_KB_LLM_CHEAP` | `google:gemini-2.5-flash` | Cheap tier |
| `WIKI_KB_INGEST_CRON` | `0 * * * *` | 5-field cron for the scheduled ingest (hourly) |
| `WIKI_KB_INGEST_LIMIT` | unset | Cap on the listing examined per run (steady-state throughput) |
| `WIKI_KB_MAX_NEW_PER_RUN` | unset | Cap on NEW meetings fetched per run (backfill chunk size) |
| `WIKI_KB_INGEST_PROFILE` | `full` | Cost/fidelity profile: `full` or `backfill` |
| `WIKI_KB_MAX_CATCHUP_DAYS` | `90` | Large-backlog guard for a wide-window ingest (raise for backfill) |
| `WIKI_KB_MAX_REPROCESS_ATTEMPTS` | `3` | Module 17 bounded auto-retry cap |
| `WIKI_KB_ACTIVE_WINDOW_DAYS` | `14` | Rolling active window (§18/§31 archive) |
| `WIKI_KB_PARTICIPANTS` | unset | Comma-separated participant-email allowlist (empty = all) |
| `WIKI_KB_RAW_ROOT` | `Raw` | Vault-relative root for the immutable raw capture |
| `FIREFLIES_WIKI_EMAIL_ENABLED` | `false` | §G9 email digests (shipped disabled) |

Also required in the environment: **`FIREFLIES_API_KEY`** (the agent reaches
Fireflies via its MCP tools) and the provider credential(s) for the tiers
(e.g. `GOOGLE_API_KEY`). `FIREFLIES_SYNC_OVERLAP_DAYS` is reused from FEAT-472.

---

## Running it

### As a long-lived daemon (recommended)
See `examples/agents/fireflies_wiki_daemon.yaml`.

```bash
uv pip install "ai-parrot-integrations[agentd]"
parrot serve examples/agents/fireflies_wiki_daemon.yaml      # scheduler runs ingest hourly
# from another terminal:
parrot status fireflies-wiki-kb
parrot attach fireflies-wiki-kb        # then use /invoke (below)
parrot ask   fireflies-wiki-kb "what did we decide about X?"   # the query intent
```

Inside `parrot attach`, trigger intents with `/invoke <method> <json>`:
```
/invoke ingest {}                       # steady-state: process new meetings
/invoke health {}
/invoke lint {"fix": false}
/invoke archive {}
```

### Expose to Claude Code over MCP
```bash
claude mcp add fireflies-wiki-kb -- parrot mcp-serve fireflies-wiki-kb
```

---

## One-time historical backfill (rate limits + cost)

The Fireflies MCP **shares the account's API rate limits** (Free 50/day ·
Pro 500/day · Business/Ent. 60/min). Each new meeting costs ~2 Fireflies
calls (transcript + summary); a ~1000-meeting year is ~2,000 calls, fetched
up front. **Run the backfill OFF the hourly schedule** (the schedule is for
steady-state new meetings only).

1. Set `WIKI_KB_MAX_CATCHUP_DAYS=280` (covers a 2026 Jan 1 → today window).
2. Use the **`backfill`** profile to cut LLM cost, and `max_new` to chunk:
   ```
   # Business/Enterprise — one shot (resumable; re-run if it stops):
   /invoke ingest {"since":"2026-01-01","profile":"backfill"}

   # Or chunk to bound cost / watch it build (repeat until 0 processed):
   /invoke ingest {"since":"2026-01-01","max_new":100,"profile":"backfill"}
   ```
3. When drained, flip the daemon back to `full`/steady-state.

**Why `max_new`, not `limit`?** The fetch-gate lists newest-first; a small
`limit` re-lists the newest (already-processed) meetings and *stalls*.
`max_new` caps the NEW meetings while paging past already-known ones, so a
chunked backfill actually walks backward. It also bounds per-run Fireflies
calls (~2×`max_new`) and LLM cost. Rate-limit failures are handled
gracefully: a failed content fetch is skipped this run (never fabricating an
empty transcript) and retried next; after 3 consecutive failures the run
stops early and resumes cheaply via the raw-id gate.

### Cost/fidelity profiles

| | `full` (default) | `backfill` |
|---|---|---|
| classify | summary-first + transcript fallback | **summary-only** |
| project reconcile | primary **+ additional** projects | **primary only** |
| contradiction detection | on | **off** |
| per-run overview update | on | **off** |
| entities/concepts | **batched, cheap tier** | **batched, cheap tier** |

Entity/concept resolution is a **single batched cheap-tier call** per meeting
in both profiles (was one strong-tier call per person/product/company/concept
— the dominant per-meeting cost). Under `backfill`, a multi-project meeting's
link to a non-primary project may dangle until a later `full` run reconciles
it (caught by `lint`, not the §34 gate).

---

## Vault structure the agent manages

```
<vault>/
├── Wiki/            index.md, overview.md, log.md, Review Queue.md,
│                    Sources/Meetings/…, Entities/{People,Companies,Products}/…,
│                    Concepts/…, Contradictions/…, Registry/processed-sources.md
├── Projects/<Name>/<Name>.md  +  <Name>/Meeting Summaries/{index.md, Archive/index.md}
├── Diary/Daily Notes/<date>.md  (+ Diary/Archive/<year>/…)
├── Raw/             Incoming/ · Processed/… (immutable, hashed) · Failed/… (quarantine)
└── Private/         NEVER read, listed, searched, indexed, or traversed (§1)
```

`Human Notes` sections are human-authored and preserved **verbatim** (§2 r13).
`Private/` is excluded from **both** the vault toolkit and the derived
GraphIndex plane.

---

## Failure handling (Module 17)

Every per-meeting compile is **transactional**: on a §34 validation failure
or any compile exception, all compiled writes are rolled back (never `Raw/`),
the raw bundle is quarantined to `Raw/Failed/<id>/` (not marked processed, so
it stays reprocessable), and a `failed-processing` Review Queue item is
written. Subsequent ingests auto-retry quarantined bundles from the local
bytes (no re-download) up to `WIKI_KB_MAX_REPROCESS_ATTEMPTS`; after the cap
the item is re-typed `reprocess-exhausted` for a human. A best-effort
entity/concept batch failure surfaces an `entity-resolution-failed` item but
does not fail the meeting.

---

## Testing

```bash
source .venv/bin/activate
pytest packages/ai-parrot/tests/unit/test_wiki_kb_*.py \
       packages/ai-parrot/tests/integration/test_wiki_kb_*.py -q
ruff check packages/ai-parrot/src/parrot/flows/wiki_ingest/
mypy         packages/ai-parrot/src/parrot/flows/wiki_ingest/
```

The `test_wiki_kb_contract.py` suite is the contract-conformance oracle
(runs the full pipeline against fake tier clients and asserts the vault
matches the operating contract).
