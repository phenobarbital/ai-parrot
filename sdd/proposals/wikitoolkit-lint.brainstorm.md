---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [wikitoolkit, lint, knowledge-graph, adr, mcp, data-integrity]
---

# Brainstorm: wikitoolkit lint

**Date**: 2026-10-03
**Author**: Jesus (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

The wikitoolkit knowledge graph (SQLite plane, the ArangoDB backend, the
markdown/OKF export, and the memories/ADR plane) has no integrity gate anyone
can run. Integrity helpers exist (`broken_edges`, `orphan_sources`,
`missing_bodies`) and a Python-only `LLMWikiToolkit.lint()` exists, but:

- the CLI and MCP server do not expose any lint;
- `fix` is a documented no-op, so problems are never repaired;
- nothing checks for duplicate titles or slugs, frontmatter schema, edge
  symmetry, ADR status consistency, contradictions between memories, or scope
  (namespace/project) violations;
- the export writes outgoing `relates_to` only, so "related" is one-way and
  navigation is lopsided.

The graph is the agents' durable memory ("the agent forgets, the graph does
not"). When it rots, agents get confidently wrong context: stale memories,
superseded ADRs presented as current, dangling links. This hurts developers
and agents using `wiki_query`/`wiki_page`, and operators maintaining wikis.

## Constraints & Requirements

- **Report by default.** `--fix` is opt-in and applies only deterministic,
  safe fixes. It never deletes pages or edges.
- **Backend-agnostic.** Runs against any `BaseWikiStore` (SQLite, ArangoDB,
  Postgres, InMemory, Federated) through the abstract interface. Backend
  fast-paths are optional.
- **Covers all four surfaces:** SQLite plane, ArangoDB backend, exported
  markdown wiki, memories/ADR plane.
- **Bidirectional `related`:** when A→B exists without B→A, `--fix` adds the
  inverse as an `asserted` edge, attributed to `lint`, and logs it to the
  audit log (`WikiBookkeeper.log_operation`).
- **Contradictions:** deterministic rules plus ADR status rules by default.
  LLM-judged contradiction is opt-in (`--llm`) with a hard cap on the number
  of pairs compared.
- **Unfixable findings go to three places:** the work ledger
  (`LedgerService.open_issue`, idempotent per finding fingerprint), a
  JSON/markdown report, and `wikitoolkit note` on the affected page.
- **Exposed as a CLI subcommand (`wikitoolkit lint`) and an MCP tool
  (`wiki_lint`).** Must be async and must not block.
- **Generalize the existing OKF lint** into a shared rule/report engine;
  OKF keeps working unchanged (`OKFToolkit.lint_knowledge_base`).
- **Hard cuts OK.** `LLMWikiToolkit.lint` / `WikiLintReport` may be
  reshaped, as long as every caller is updated in-feature.

---

## Options Explored

### Option A: Shared rule-pack engine (generalize OKF lint)

Extract a backend-neutral core from `okf/lint.py`: a `Finding` model
(rule id, severity info/warning/error, subject id(s), message, fixable flag,
fingerprint), a `LintRule` protocol (`check(ctx) -> findings`, optional
`fix(ctx, finding) -> FixResult`), and a `LintRunner` that runs selected rule
packs, applies fixes in `--fix` mode, and renders reports. Rule packs:

- **okf**: today's four checks, ported, so the output stays identical.
- **plane**: broken links, orphans, duplicate titles/slugs, missing bodies,
  stale sources, rebuilding the index (FTS rebuild + `meta` repair),
  `related` symmetry.
- **export**: frontmatter schema, a dangling `relates_to`, drift between the
  export and the plane (in the plane but not the export, or the reverse).
- **memory/adr**: superseded-but-active, a broken `supersedes` chain, accepted
  ADRs that cite the same symbols and conflict, memories pointing at deleted
  pages, scope violations (an edge across namespaces or projects that is not
  allowed).
- **llm** (opt-in): pairwise contradiction judging over candidate pairs
  (same linked page, overlapping tags), capped.

`LLMWikiToolkit.lint`, the CLI and the MCP tool are all thin adapters over
`LintRunner`.

✅ **Pros:**
- One engine with one severity model, one report format and one fix
  contract for both OKF and the wiki.
- Rules can be tested in isolation against `InMemoryWikiStore`.
- New checks are cheap to add; `--rules` / `--skip` selection comes for free.

❌ **Cons:**
- Porting OKF needs parity tests.
- More upfront design than bolting checks on.

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | Finding/Report models | already a dependency |
| `jsonschema` or Pydantic models | frontmatter schema validation | prefer Pydantic (no new dependency) |
| `click` | CLI subcommand | already used by `wiki/cli.py` |
| `rapidfuzz` (optional) | near-duplicate titles | only if exact plus normalized matching is not enough; stdlib `difflib` is the fallback |

🔗 **Existing Code to Reuse:**
- `knowledge/pageindex/okf/lint.py` — `LintFinding`, `LintReport`, `lint_knowledge_base`
- `knowledge/wiki/toolkit.py:415` — `LLMWikiToolkit.lint` (becomes an adapter)
- `knowledge/wiki/store.py` — `broken_edges`, `orphan_sources`, `missing_bodies`, `dump_pages`, `dump_edges`, `add_edges`, `rebuild_from_tree`
- `knowledge/wiki/sources.py:532` — `is_stale`
- `knowledge/wiki/export.py:86,125` — `page_frontmatter`, `export_okf_bundle`
- `knowledge/wiki/decisions/` — `DecisionRecord.source_status`, supersedes parsing
- `knowledge/wiki/ledger/service.py:168` — `open_issue`
- `knowledge/wiki/bookkeeper.py:175` — `log_operation("LINT", ...)`

---

### Option B: Extend `LLMWikiToolkit.lint` in place

Keep the current method and `WikiLintReport` with their flat lists. Add new
list fields for duplicates, asymmetric edges, frontmatter errors and ADR
conflicts. Make `fix=True` do something, and wire it into the CLI and MCP.
Leave OKF lint alone.

✅ **Pros:**
- Fastest path; the smallest diff.

❌ **Cons:**
- Two lint engines keep diverging, against the user's decision to generalize.
- There is no per-finding severity or fixable flag, so routing findings to
  the ledger/report/notes needs ad-hoc code for each list.
- Every new check grows the report model.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:** `toolkit.py:415`, `models.py:302`, and the store integrity helpers.

---

### Option C: Declarative SQL/AQL rule catalogue (unconventional)

Express each rule as a query: SQL for SQLite and Postgres, AQL for Arango.
Store them in a YAML catalogue, and keep fixes as paired query templates. The
runner executes the queries for the active backend and maps rows to findings.

✅ **Pros:**
- Very fast on big planes because work is pushed into the database.
- Operators can add rules without writing Python.

❌ **Cons:**
- Every rule has to be written two or three times (SQL, AQL, InMemory).
- The export, frontmatter and LLM rules don't fit the model at all.
- Fix templates that write raw SQL bypass the store's triggers, audit log and
  CAS (`compare_and_swap_page`).
- It is hard to unit test.

📊 **Effort:** High

📦 **Libraries / Tools:** `pyyaml` (already present).

🔗 **Existing Code to Reuse:** the store integrity queries (`store.py:2344+`, `arango_store.py:1149+`).

---

## Recommendation

**Option A** is recommended because:

- It matches the decision already made: generalize into a shared engine.
- It is the only option where findings carry severity, a fixable flag and a
  fingerprint uniformly. That makes the three-way routing (ledger with an
  idempotent fingerprint, report, page note) and the safe-fix contract
  generic rather than handled per check.
- Option C's speed can be kept selectively. A rule can call a backend
  fast-path (the existing `broken_edges()` is already one) and fall back to
  `dump_pages`/`dump_edges`, which keeps the engine backend-agnostic.

What we give up: more upfront work than Option B, and parity tests for the
OKF port. Both are acceptable because hard cuts are allowed and OKF's surface
is small (four checks).

---

## Feature Description

### User-Facing Behavior

```
wikitoolkit lint [--path P] [--backend sqlite|arango|...] [--ns NAME]
                 [--rules plane,export,adr,memory,okf,llm] [--skip RULE_ID...]
                 [--fix] [--llm --llm-max-pairs N]
                 [--report json|md] [--output FILE]
                 [--ledger/--no-ledger] [--notes/--no-notes]
                 [--fail-on error|warning]
```

- The default run is a dry run. It prints a grouped summary
  (rule → count → severity) and exits non-zero when `--fail-on` is reached.
- `--fix` applies safe fixes only:
  - add inverse `related` edges;
  - rebuild FTS and repair `meta` (the "rebuild the index" ask);
  - re-export pages whose export drifted from the plane;
  - normalize frontmatter fields that can be derived from the plane.
  Each fix is logged as `LINT_FIX` in the audit log. The summary lists fixed
  versus remaining findings.
- Unfixable findings are routed to:
  - the ledger, one issue per fingerprint, deduplicated on re-run and
    `discovered_from=lint:<rule>`;
  - a report file (JSON plus markdown);
  - a `note` on the subject page.
  Each routing target can be turned off.
- The MCP tool `wiki_lint` has the same parameters and returns a compact
  JSON summary plus the report path. `fix` defaults to false.

### Internal Behavior

1. **Resolve the store.** Use the existing CLI resolution (`--path`,
   `--backend`, namespace) to get a `BaseWikiStore`.
2. **Build the lint context.** A `LintContext` lazily caches the pages, the
   edges, the source manager, the export dir and the decision records, so
   each piece is loaded once per run.
3. **Run the rule packs.** `LintRunner` runs the selected packs. Each rule
   yields `Finding`s. Severity can be overridden from the config.
4. **Apply fixes (`--fix` only).** The runner calls `rule.fix()` for fixable
   findings:
   - Writes go through store APIs (`add_edges`, `upsert_pages`,
     `rebuild_from_tree`, FTS rebuild) so triggers and CAS stay valid.
   - Fixes are idempotent.
   - After the fixes, the affected rules run again to confirm the findings
     are gone.
5. **Route what is left.** Remaining findings go to the report, the ledger
   and page notes.
6. **Log the run.** The whole run is logged as `LINT` in the audit log.

**Symmetry rule.** The inverse relation comes from a relation table:
- `related`/`references` are symmetric and get the inverse `related`.
- `supersedes` gets `superseded_by`.
- `contains` is excluded because it is hierarchical.

The table is configurable.

**Rule catalogue (initial):**
- `broken-link`
- `orphan-page`
- `orphan-source`
- `duplicate-title` (exact and normalized)
- `duplicate-slug`
- `missing-body`
- `stale-source`
- `stale-memory`
- `frontmatter-schema`
- `export-drift`
- `asymmetric-related`
- `fts-index-drift`
- `adr-superseded-active`
- `adr-supersedes-broken`
- `adr-conflict`
- `memory-dangling-link`
- `scope-violation`
- `contradiction-llm`

### Edge Cases & Error Handling

- **Federated store.** Edges that cross namespaces are classified using the
  existing federation logic. A cross-namespace edge is a `scope-violation`
  only when the policy forbids it, not by default.
- **Arango unreachable (VPN).** The run fails fast with a clear error and
  never falls back silently to SQLite.
- **Schema version mismatch** (v2 code against a v3 plane). The run reports
  this and refuses `--fix`.
- **Concurrent writers.** Fixes use CAS where it is available. On a conflict
  the finding is reported as `fix-conflict` and retried by the next run.
- **Ledger flooding.** A per-rule cap; findings over the cap are aggregated
  into one issue per rule.
- **LLM pass.** Pair cap, timeout and cost guard. A failure degrades to an
  "llm-skipped" note. It never fails the deterministic run.
- **Empty plane or fresh `meta`.** Reported (`fts-index-drift`/meta), and
  fixable through the rebuild.

---

## Capabilities

### New Capabilities
- `lint-engine`: a shared rule/finding/runner/report core (generalized from OKF).
- `wiki-lint-rules`: rule packs for the plane, export, ADR, memory, scope and llm.
- `wiki-lint-fix`: a safe idempotent fix contract (inverse edges, index
  rebuild, export resync, frontmatter repair).
- `wiki-lint-routing`: routes findings to the ledger, the report and page notes.
- `wiki-lint-cli-mcp`: the `wikitoolkit lint` command and the `wiki_lint` MCP tool.

### Modified Capabilities
- OKF lint (`okf/lint.py`, `OKFToolkit.lint_knowledge_base`) becomes a rule
  pack over the shared engine.
- `LLMWikiToolkit.lint` and `WikiLintReport` become adapters over
  `LintRunner`; `fix` becomes real.
- `export.py` optionally emits symmetric `relates_to` once the plane edges
  are symmetric (the export itself does not invent edges).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `knowledge/pageindex/okf/lint.py` | modifies | ported onto the engine; parity tests |
| `knowledge/wiki/toolkit.py` (`lint`) | modifies | adapter; hard cut of the report shape |
| `knowledge/wiki/models.py` (`WikiLintReport`) | modifies | replaced by or wraps `LintReport` |
| `knowledge/wiki/cli.py` | extends | new `lint` command (FEAT-569 also edits cli.py — sequence it) |
| `knowledge/wiki/tools.py`, `mcp_server.py` | extends | `WikiLintTool` in `create_wiki_tools` |
| `knowledge/wiki/store.py`, `arango_store.py` | depends on / maybe extends | optional fast-paths (duplicate titles, asymmetric edges) |
| `knowledge/wiki/ledger/service.py` | depends on | `open_issue` with fingerprint dedup |
| `knowledge/wiki/decisions/` | depends on | status and supersedes data |
| `knowledge/wiki/bookkeeper.py` | depends on | `LINT` / `LINT_FIX` ops |

---

## Code Context

### Verified Codebase References

All paths are relative to `packages/ai-parrot/src/parrot/knowledge/`.

#### Classes & Signatures
```python
# wiki/toolkit.py:415
async def lint(self, wiki_name: str, fix: bool = False) -> dict[str, Any]:  # fix is a documented no-op today

# wiki/models.py:302
class WikiLintReport(BaseModel): ...  # flat lists, total_issues computed

# pageindex/okf/lint.py
class LintFinding(BaseModel):  # :46  kind: orphan|broken_link|missing_concept|stale; severity: warning|error
class LintReport(BaseModel):   # :63
def lint_knowledge_base(...):  # :91  pure; stale_days=90; no fix
# pageindex/okf/tools.py:287 — OKFToolkit.lint_knowledge_base(stale_days=90)

# wiki/store.py
SCHEMA_VERSION = "3"                                    # :50
class BaseWikiStore(ABC):                               # :525
    async def orphan_sources(self) -> list[str]: ...    # :600 (abstract)
    async def broken_edges(self) -> list[dict[str, Any]]: ...  # :603 (abstract)
    # also abstract: missing_bodies, upsert_pages, add_edges, delete_page, dump_pages, dump_edges, stats, neighbors
    # concrete: compare_and_swap_page (:610), get_meta/set_meta, rebuild_from_tree, page_hashes
# SQLite impls: orphan_sources :2344, broken_edges :2354, missing_bodies :2364
# Tables: pages(concept_id PK, title, category, summary, body, origin['ingest'|'memory'|'authored'], asserted_by, content_hash, ...),
#         edges(src, dst, rel DEFAULT 'references', provenance DEFAULT 'extracted' [extracted|inferred|asserted], PK(src,dst,rel)),
#         sources, meta, embeddings, symbols, pages_fts/symbols_fts (external-content FTS5 + triggers)

# wiki/arango_store.py:135 — ArangoDBWikiStore (wiki_pages / wiki_edges); integrity helpers :1149/:1161/:1182
# wiki/federation.py:622 — FederatedWikiStore (broken_edges classifies cross-namespace edges)

# wiki/export.py
def page_frontmatter(page, relates_to): ...             # :86  type,title,id,tags,timestamp,summary?,relates_to?
async def export_okf_bundle(store, output_dir, wiki_name): ...  # :125  outgoing edges only

# wiki/sources.py:532 — SourceCollectionManager.is_stale(source_id)  (sha1/mtime/missing)
# wiki/bookkeeper.py:175 — WikiBookkeeper.log_operation(wiki_dir, operation, details, timestamp=None)
# wiki/ledger/service.py:116 — LedgerService.from_root(root=None)
# wiki/ledger/service.py:168 — async open_issue(title, body, kind="bug", severity="minor", discovered_from="", about=None, actor="agent:sdd") -> str
# wiki/mcp_server.py:91 — create_wiki_mcp_server(root); wiki/tools.py:807 create_wiki_tools(...)
# wiki/decisions/models.py — DecisionRecord.source_status: unknown|proposed|accepted|rejected|deprecated|superseded (:153);
#                            DecisionLink.relation: explains|supported_by|supersedes (:115)
# wiki/decisions/parser.py:28 — FRONTMATTER_KEYS = ("id","title","status","supersedes")
# wiki/cli.py — click group `wiki` :1446; `link` :4033 → store.add_edges([(src,dst,rel,"asserted")]); `status` :2148; `export` :3480
# CLI entry: packages/ai-parrot/pyproject.toml:204  wikitoolkit = "parrot.knowledge.wiki.entry:main"
```

### Does NOT Exist (Anti-Hallucination)
- ~~`wikitoolkit lint` subcommand~~ / ~~`wiki_lint` MCP tool~~ — neither exists
- ~~working `fix=True`~~ — `LLMWikiToolkit.lint(fix=...)` is a no-op
- ~~reverse/bidirectional edge sync~~, ~~`related:` frontmatter key~~ — the export writes outgoing `relates_to` only
- ~~frontmatter schema validator~~ for exported pages
- ~~title/slug uniqueness constraint or duplicate detection~~
- ~~`memories` / `notes` tables~~ — memories are `pages.origin='memory'`
- ~~per-finding severity at wiki level~~ — only OKF `LintFinding` has one
- ~~check that a superseded ADR has a matching supersedes edge~~
- ~~a `related` relation in use today~~ — relations seen: contains, references, supersedes, calls, defines, imports, mentions, depends_on

---

## Parallelism Assessment

- **Internal parallelism:** after the engine core lands, the rule packs
  (plane, export, adr/memory, llm), the routing layer and the CLI/MCP
  adapters are largely independent. Width is about 4 after a one-task core
  wave.
- **Cross-feature independence:**
  - FEAT-569 (wikitoolkit-http-mcp) and the wikitoolkit-inbox brainstorm both
    touch `cli.py`, `tools.py` and `mcp_server.py`. Schedule the CLI and MCP
    tasks last.
  - FEAT-578 (ADR plane) is a read-only dependency.
- **Recommended isolation:** `per-spec`, with the CLI/MCP tasks ordered last.
- **Rationale:** all the code sits in one package directory (`knowledge/`),
  and the shared models are touched by every pack.

---

## Open Questions

- [x] Surfaces in scope — *Owner: Jesus*: SQLite plane, ArangoDB, the exported markdown wiki, and memories/ADR.
- [x] Fix default — *Owner: Jesus*: report by default; `--fix` is opt-in and safe only.
- [x] Contradiction semantics — *Owner: Jesus*: deterministic rules, ADR status conflicts, and LLM-judged (opt-in).
- [x] Relation to OKF lint — *Owner: Jesus*: generalize into a shared engine.
- [x] Asymmetric `related` handling — *Owner: Jesus*: add an inverse asserted edge, attributed to lint; never delete.
- [x] Finding destinations — *Owner: Jesus*: ledger + JSON/md report + page notes.
- [x] Execution surface — *Owner: Jesus*: CLI + MCP tool, LLM opt-in.
- [x] Relation-inverse table — *Owner: Jesus*: yes, `references` is treated as symmetric `related`, and the inverse is added on `--fix`.
- [x] Scope-violation policy — *Owner: Jesus*: an edge is out of scope when it is a broken link (its target does not resolve in the wiki or namespace).
- [x] Duplicate-slug definition — *Owner: Jesus*: compute the slug of each page and look it up in the wiki; if it already exists for another page, it is a duplicate.
- [x] Stale memory severity — *Owner: Jesus*: warning.
- [x] Run in hook/CI — *Owner: Jesus*: run the deterministic lint in CI (`--fail-on error`); not in the post-commit hook.
- [ ] Which LLM client and model does the `--llm` pass use, and what is the default for `--llm-max-pairs`? — *Owner: Jesus* (decide during /sdd-spec)
