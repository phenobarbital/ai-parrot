---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools]
tags: [bookstore, pageindex, agentic-retrieval, citations, multistoresearch, reindex]
docs:
  policy: required
  pages:
    - wiki/knowledge/bookstore-agentic-retrieval.md
    - wiki/knowledge/bookstore-codex.md
    - wiki/knowledge/bookstore-graph.md
    - wiki/knowledge/pageindex-agentic-retrieval.md
  api_modules:
    - parrot.knowledge.bookstore.library
    - parrot.knowledge.bookstore.toolkit
    - parrot_tools.multistoresearch.origins.bookstore
---

# Feature Specification: Bookstore Agentic Retrieval

**Feature ID**: FEAT-858
**Date**: 2026-11-09
**Author**: Jesus Lara
**Status**: approved
**Target version**: next feature release from dev (current core version: 2.1.2)

## 1. Motivation & Business Requirements

### Problem Statement

PageIndex has a bounded stage-2 reading loop with validated citations, but Bookstore
cannot expose it, and multi-origin search cannot query the library. Re-indexing is
already atomic at tree publication (FEAT-615/831); remaining gaps are unnecessary
graph invalidation, concurrent import races, lazy crash cleanup, and card/tree drift.
The provisional reading budgets need a reproducible evaluation on the host library.

Source: `sdd/proposals/bookstore-agentic-retrieval.brainstorm.md`, Option A. The owner
accepted three corrections on 2026-11-09: a separate Bookstore operation lock;
preservation only when source hash AND TOC match; and an optional expected_revision
guard on segment reads. These supersede the corresponding brainstorm mechanics.

### Goals

- Delegate per-book agentic retrieval to PageIndex without another loop or validator.
- Expose verifiable, revision-pinned book excerpts through a stage-1 Bookstore origin.
- Keep the agentic MCP tool visible without an LLM and explain configuration failures.
- Preserve existing atomic-swap guarantees while implementing all four hardenings.
- Add `bookstore ask` and `bookstore doctor`, including deterministic drift repair.
- Evaluate seven books with 56 baseline plus 84 sweep runs, recording real metrics
  and selecting provisional Bookstore defaults only from adequate evidence.

### Non-Goals (explicitly out of scope)

- Library-wide agentic loops, shared Citation/OriginHit schema changes, or an FTS mirror.
- Changes to clients/base.py or the PageIndex retrieval loop/validator.
- Ebook-heading and large-leaf fixes; evaluation reruns after those fixes are follow-up.
- Re-fixing ledger issue 759176f0cf1a: the brainstorm records its FEAT-615 resolution.
- Running the live evaluation or re-indexing the user's books during spec authoring.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:fe643c945df78c1f5f13c19d48f59c6ae87f723f7a3d624046dd7926c0e35045 evaluation_digest=sha256:50e5b850aa843d68015ac0674597dac1057be84edb6088f2741bf98a2231e3d2 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Option A: Bookstore resolves one card and delegates to the scope's existing
`PageIndexToolkit.agentic_retrieve`. Its serialized bundle is decorated after validation;
no provider SDK, second reading loop, or second citation validator is introduced.
`BookstoreToolkit` exposes the method through normal automatic tool discovery. The actual
surface grows from 13 to 14 tools; the brainstorm's 10-to-11 count is stale.

A separate `BookstoreOrigin` runs only stage 1 and bounded segment reads. It produces exact
single-segment excerpts with immutable addresses in `OriginHit.metadata["citation"]`.
Shared `Citation`, `OriginHit`, and `OriginSection` models remain unchanged. The only enum
addition is `SearchOriginKind.BOOKSTORE = "bookstore"`.

### Component Diagram

```text
bookstore ask / MCP -> Bookstore.agentic_retrieve -> PageIndexToolkit.agentic_retrieve
                             |                             |
                             +-- citation decoration <-----+ validated evidence
MultiStoreSearchToolkit -> BookstoreOrigin -> Bookstore.search + read_segments
                                             |               |
                                             +-- pinned revision validation
bookstore add / doctor -> Bookstore operation locks -> staging / rename / catalog
```

### Integration Points

| Component | Integration | Contract |
|---|---|---|
| PageIndex toolkit, retriever, citations | read-only reuse | Existing budgets, serialization, ledger and validation |
| Bookstore library | extend | Delegation, guarded reads, operation locks, initialization and doctor |
| Bookstore toolkit/MCP | extend | Visible tool and optional read revision guard; stdout remains JSON-RPC |
| MultiStoreSearch origins | extend | New Bookstore origin; additive request-local section hook |
| Shared store models | additive enum only | Citation remains metadata; other model schemas unchanged |
| CLI | extend | ask and doctor; shared model resolution, deterministic repair |
| Host evaluation | new | 140 planned runs, pinned questions, numeric-only report |
| Documentation | update/create | Usage, recovery semantics and report-derived provisional defaults |

### Data Models and Evidence Contracts

The returned agentic dict preserves every EvidenceBundle field, adds `book_id` and
`book_title`, and enriches each serialized citation dict with `book_id`, `title`, and,
when known, `chapter` and `section_path`. Do not add these to the shared Citation model.
`rendered_citations` remains a semicolon-separated string using
`[<title>, <chapter>, <label>]`, or `[<title>, <label>]` without a chapter.
Do not rewrite the drafted answer or alter its grounded/stopped/cost fields.

Ownership decoration uses a separately fetched tree only if its generation equals the
bundle/read generation AND the document revision matches the citation. Resolve the unique
node whose `owned` half-open seq ranges contain the citation, restricted to that document;
use its root-to-node titles as section_path. Ambiguous ownership does not choose arbitrarily.
Otherwise use the citation's stored section path, then a depth-1 TOC entry covering its page
ONLY if derived from the matching tree, otherwise omit chapter/path. Never use a current
catalog TOC to label an old generation. A missing decoration snapshot does not discard
already validated evidence. Citation text and offsets are never modified by decoration.

The exact inherited `stopped` values are `answered`, `budget`, `max_tool_calls`, `timeout`,
`no_tool_calls`, `parse_error`, `provider_error`. There is no `stale` value. Preserve returned
bundles and real errors; do not fabricate a stale bundle. Legacy books fail with the existing
re-index hint before LLM invocation. Explicitly check `has_llm` before PageIndex delegation:
Bookstore's `_NullAdapter` is not a real provider. Missing/unsupported tool-loop configuration
becomes BookstoreError with `PARROT_BOOKSTORE_LLM` guidance, preserving the original reason.
Do not mislabel numeric parameter validation errors as missing LLM configuration.

`read_segments(..., expected_revision=None)` is backward compatible. When set, compare the
expected value with the **actual returned ReadResult.revision** before releasing any result
text to the caller. A mismatch raises `RevisionMismatchError` (a ValueError), propagated by
Bookstore rather than flattened to BookstoreError. Cursor mismatch retains the same exception.
The guard promises that the returned snapshot matches, not that it remains live afterward.
An optional preliminary check may save work but cannot replace the returned-result check.
No changes to PageIndex public read signatures are needed.

### Origin behavior

Constructor accepts scope and book_ids filters, max_books=3, top_k=5, excerpt_chars=600,
name="bookstore", optional description and timeout. Integers must be positive (reject bool),
max_books <= 10, top_k <= 50, scope is project/global/None, timeout if supplied is positive
finite. `search(query, k)` returns at most k hits; k<=0 returns [] without searching.
The origin has `supports_fts=False`: stage-1 BM25 fallback does not promise a separate FTS API.

Intersect explicit book IDs with visible cards and requested scope before shortlisting.
With filters, use catalog relevance order within the filtered set and stable catalog order
as fallback, then cap max_books. If the allowed set is empty, return no hits immediately;
never pass [] to Bookstore.search (which means unfiltered today). Unknown explicitly supplied
book IDs produce an explanatory error. Project precedence is retained for colliding IDs.
Without filters let Bookstore.search perform its existing shortlist behavior.

Normalize both real stage-1 result shapes: LLM `books[].node_list` and BM25
`books[].results[].node_id`. Preserve book/node order, dedupe candidates and cap top_k per
book. Do not emit scoped `context`, summaries or synthetic text as evidence. Read candidates
with a semaphore of four and preserve input order regardless of completion order. The
MultiStoreSearch per-origin timeout encloses search, all reads and validation; cancellation
must cancel child reads and release permits. Direct origin.search obeys its explicit timeout
when configured (otherwise the toolkit's default timeout applies when invoked there).

For each read, load the named immutable revision through SegmentStore using its returned
(doc_id, revision), never the current revision by assumption. Verify seq bounds and require
`stored.text[start:end] == content` as well as find_any_match. Emit one hit per segment;
clip text explicitly to the remaining per-node excerpt_chars allowance because PageIndex
has a 500-character minimum read budget. Adjust end to start+len(clipped_text); never join
segments into one falsely addressed hit. Skip empty or unverifiable segments. Deduplicate
(book_id, doc_id, revision, seq, start, end) and assign native_rank=1..N after filtering.
Hit IDs include those address components; metadata also carries node_id, scope, generation,
book title and the decorated citation (doc_id/revision/seq/start/end/page/ordinal/section/
label/document/excerpt/book_id/title plus optional chapter/section_path). Retain the native
score where provided; never claim scores are comparable across origins.

A new additive `SearchOrigin.search_section(query, k)` returns an existing OriginSection.
Its default awaits search and creates the same successful section as today. Bookstore's
override returns its request-local hits AND a note counting skipped legacy books, stale or
missing revisions and invalid excerpts, including the all-skipped case. No mutable last_note
attribute. The toolkit uses this hook for non-FTS searches when available, retains the
legacy search path for duck-typed origins, and accepts OriginSection results while stamping
origin identity/kind/description from the configured origin. FTS and exception/timeout
handling remain unchanged. Direct BookstoreOrigin.search shares the same private collector
but returns only hits. Whole-backend failures (including missing bm25s) still raise and yield
an error section; partial evidence failures are counted without suppressing healthy hits.

### Re-index and recovery behavior

Use existing `tree_lock` in a **separate storage namespace**:
`<LibraryLocation.root>/.bookstore-operations/` (its .locks subdirectory is created by the
helper). Never hold the live PageIndex publication lock across rename_tree.
`reindex_lock_timeout_s` is a new keyword-only Bookstore constructor option, default 5.0,
positive finite. One monotonic deadline bounds all operation-lock acquisition for a call.
Timeout raises BookstoreError naming the slug/source and saying re-index is already in
progress; no staging or catalog mutation precedes successful locking.

Before catalog identity lookup, acquire deterministic source locks named `path-<sha256 of
canonical path>` and `sha-<source_sha256>` in sorted order in the operation namespace.
Hashing/reading the source and validating its format precede these locks; the brainstorm's
"nothing read" means no catalog decision/ingest, not no filesystem stat/hash. Under those
locks resolve SHA first then path, and choose the live slug. Acquire `book-<slug>` and
re-read identity and slug occupancy before deciding skipped/updated/added. If identity or
occupancy changed, release book lock and retry resolution within the original deadline;
never silently overwrite an unrelated book. For new slugs, use a short allocation lock
while selecting/acquiring the book lock, and create the reserved staging tree before
releasing allocation. Taken slugs include bases of active staging names. Acquire allocation
locks for configured locations in canonical path order so cross-scope creation cannot pick
the same new ID. Keep source/book locks through publication, catalog upsert and graph
invalidation; release before optional relate_books. Lock names cannot collide with reserved
tree names because their storage namespace is separate.

Compute the card from staging as today. Preserve graph and existing community_id/label
only for updated imports with both **nonempty equal source_sha256 AND equal toc_digest**.
Preserve existing manual card override behavior. On change, upsert after successful rename
and invalidate the graph afterward; ingest failures/cancellation clean staging on BaseException
and leave the live tree/card/graph intact. No rollback deletes a successfully published live
tree if catalog upsert subsequently fails: doctor reports/repairs the resulting drift.
Same bytes plus same TOC permits newly generated descriptive fields to update under existing
manual-card rules. Log preservation without including book content.

Keep `_toolkit` synchronous and construction-only. Add awaited `_ready_toolkit(scope)` with
one asyncio lock per scope; the first async scope use awaits recovery, concurrent callers
join it, completion is marked only after the sweep finishes, and cancellation leaves it
retryable. Sweep itself uses raw `_toolkit` to avoid recursion. Route async reads/search,
agentic retrieval, ingest, optimization and removal through readiness before holding book
operation locks. Synchronous catalog/read_section interfaces remain synchronous; they do
not launch background cleanup or create an event loop. This is the executable interpretation
of lazy sweep-on-open. Existing explicit pre-add sweep remains safe and may revisit stale trees.

Sweep acquires each affected `book-<live_slug>` operation lock nonblockingly, skips busy books,
and rechecks reserved/live existence and age after locking. Active staging older than one hour
is not deleted. Restore legacy --replaced- only if live remains absent; otherwise delete the
reserved tree, and delete stale --staging- under the same lock. Vacuum only after releasing
any PageIndex lock, still under the operation lock. Normal cleanup remains best effort and
logged; doctor reports outcomes and failures rather than claiming all cleanup succeeded.
Lock ordering is source -> allocation (new identity only) -> book -> PageIndex. Recovery uses
book -> PageIndex and never acquires source/allocation locks. No nested acquisition of the same
book lock. Bookstore remove and optimize(apply=True) participate in the book operation lock;
direct external PageIndex writers retain their own generation/publication guarantees.

`doctor(scope=None, repair=False, relate=False, use_llm=True)` returns a dict with `reserved`
entries (scope/name/action/reason), `books` entries (scope/book_id/status/repaired),
`unjudged_book_ids`, `errors`, and optional `relate_summary`. Statuses are ok, drift,
orphan_card, busy, error. It scans before sweeping so the report records what was found.
Drift compares derive_toc(live_tree) with the card digest and TOC entries. Repair rereads
under the book operation lock, updates toc/toc_digest/page_count/chapter_count, preserves
manual descriptive fields, and invalidates graph for changed structure. A missing tree is
reported but never reconstructed without its source. Repair cannot prove source identity:
clear source_sha256 to an empty unknown marker so the next import cannot preserve a graph
using an obsolete hash. Do not label a changed source file as the source of the live tree.
TOC-only drift detection cannot detect a crash swapping different text with identical TOC;
this limitation must be reported/documented (full transactional catalog publication is out
of scope). With --relate, select books with zero judgement rows touching either endpoint
across scopes, not zero positive edges; no targets means no relation call. --repair alone
never resolves or calls an LLM. --no-llm makes --relate deterministic.

### CLI behavior

`bookstore ask BOOK_ID QUERY [--llm provider:model] [--budget-chars N] [--max-reads N]
[--timeout S] [--json]` resolves the adapter through the existing helper, reports the
resolved provider/model on stderr, and delegates with draft_answer=True. Normal stdout
shows answer, rendered citations and grounded/stopped/chars_read; JSON stdout is exactly
the serialized bundle. Missing models and Bookstore errors use ClickException. Diagnostics
must not contaminate MCP or JSON output. Reuse `_open_bookstore`/resolve_adapter semantics;
read adapter/client attributes for resolved identity instead of guessing from unset flags.

`bookstore doctor [--global] [--repair] [--relate] [--no-llm] [--llm provider:model] [--json]`
examines project scope by default, global when requested. Recovery sweep runs even without
--repair; that flag controls card repair only. Build without an LLM unless --relate requires
one. Normal stdout summarizes actions; JSON is the report. --repair and --relate may be
combined, with repair preceding relation targeting.

## 3. Module Breakdown

Paths below use C=`packages/ai-parrot/src/parrot`, T=`packages/ai-parrot-tools/src/parrot_tools`;
these are literal path-prefix abbreviations only. Full edit paths are in §6.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not |
|---|---|---|---|
| M1 evidence facade | yes | Delegation, returned revision guard, generation-safe decoration below | — |
| M2 tool surface | yes | Thin wrappers, visible discovery, 14 tools, unchanged MCP stdout | — |
| M3 origin | yes | Dual search shapes, pinned single-segment hits, request-local section hook | — |
| M4 lifecycle/re-index/doctor | no | Lock ordering and failure contracts fixed below | Multi-process and crash behavior needs full reasoning/review |
| M5 CLI | yes | Click wrappers, exact flags, stderr identity, JSON purity | — |
| M6 evaluation/docs | no | Fixed 140-run design and selection rule below | Host corpus and owner-reviewed gold labels required |

### Module 1: Bookstore evidence facade

- **Paths**: C/knowledge/bookstore/library.py; new test_agentic_retrieval.py and
  test_revision_guard.py under packages/ai-parrot/tests/knowledge/bookstore/.
- **Depends on**: existing PageIndex; use M4 readiness when available (shared-file serialization).
- **Interface Skeleton** (new except read_segments extension):

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179
class Bookstore:
    async def agentic_retrieve(self, book_id: str, query: str, top_k: int = 5,
                               draft_answer: bool = True, budget_chars: Optional[int] = None,
                               max_reads: Optional[int] = None,
                               timeout_s: Optional[float] = None) -> dict[str, Any]:
        """Return PageIndex evidence decorated with book identity; require an LLM and segments."""
    # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:434
    async def read_segments(self, book_id: str, start: Optional[int] = None,
                            end: Optional[int] = None, node_id: Optional[str] = None,
                            max_chars: int = 12000, cursor: Optional[str] = None, *,
                            expected_revision: Optional[str] = None) -> dict[str, Any]:
        """Read a snapshot; raise RevisionMismatchError before returning mismatched text."""
    async def _decorate_citations(self, card: BookCard, scope: str,
                                  bundle: dict[str, Any]) -> dict[str, Any]:
        """Copy and enrich validated citations using only matching generation metadata."""
```

Decoration may use a pure private helper within library.py shared with the origin via
Bookstore's facade; do not export PageIndex internals or invent a BookCitation model.
Origin uses `_decorate_citations` with its verified citation list and read generation;
that narrow internal coupling must be covered by integration tests.

### Module 2: Toolkit and MCP exposure

- **Paths**: C/knowledge/bookstore/toolkit.py, mcp_server.py; existing test_toolkit.py,
  test_mcp_server.py. Add new delegation tests there; update exact discovery assertions.
- **Depends on**: M1.
- **Interface Skeleton**:

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:29
class BookstoreToolkit(AbstractToolkit):
    async def agentic_retrieve(self, book_id: str, query: str, top_k: int = 5,
                               draft_answer: bool = True, budget_chars: Optional[int] = None,
                               max_reads: Optional[int] = None,
                               timeout_s: Optional[float] = None) -> dict[str, Any]:
        """Research one book with validated citations; requires PARROT_BOOKSTORE_LLM."""
    # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:140
    async def read_segments(self, book_id: str, start: Optional[int] = None,
                            end: Optional[int] = None, node_id: Optional[str] = None,
                            max_chars: int = 12000, cursor: Optional[str] = None,
                            expected_revision: Optional[str] = None) -> dict[str, Any]:
        """Read exact paragraphs, rejecting a supplied revision that differs from the result."""
```

No llm_dependent_tools declaration. MCP factory signature is unchanged; its docstring and
server description describe the extra tool and truthful degradation matrix.

### Module 3: Bookstore search origin and section diagnostics

- **Paths**: new T/multistoresearch/origins/bookstore.py; modify origins/base.py,
  origins/__init__.py, multistoresearch/toolkit.py and C/models/stores.py.
- **Tests**: new packages/ai-parrot-tools/tests/multistoresearch/test_bookstore_origin.py
  and test_origin_sections.py.
- **Depends on**: M1 guarded read and decoration; no dependency on M2 or M5.
- **Interface Skeleton**:

```python
# SearchOrigin verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:18
class BookstoreOrigin(SearchOrigin):
    """Stage-1 library search with pinned, validated single-segment excerpts."""
    def __init__(self, bookstore: Bookstore, *, scope: Optional[str] = None,
                 book_ids: Optional[list[str]] = None, max_books: int = 3,
                 top_k: int = 5, excerpt_chars: int = 600, name: str = "bookstore",
                 description: Optional[str] = None, timeout: Optional[float] = None) -> None:
        """Configure bounded search; reject invalid limits/scope/timeout."""
    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Return at most k evidence hits in deterministic native order."""
    async def search_section(self, query: str, k: int) -> OriginSection:
        """Return hits plus request-local skip diagnostics without swallowing backend failures."""
# additive default method on SearchOrigin, verified: origins/base.py:18 (full path above)
async def search_section(self, query: str, k: int) -> OriginSection:
    """Wrap search results in a successful section; exceptions remain toolkit-owned."""
# Existing method extended to accept OriginSection, verified:
# packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:304
def _section_from_result(self, origin: SearchOrigin, result: Any) -> OriginSection:
    """Normalize list, section, timeout or error while preserving configured origin identity."""
```

Export BookstoreOrigin from origins/__init__.py. Enum adds BOOKSTORE; all existing values
and shared model fields remain unchanged. Import Bookstore under TYPE_CHECKING where
possible to avoid pulling heavy Bookstore dependencies into unrelated origin imports.

### Module 4: Lifecycle, import serialization and doctor

- **Paths**: C/knowledge/bookstore/library.py, catalog.py; new test_reindex_hardening.py,
  test_doctor.py under core Bookstore tests. Existing library regression tests remain gates.
- **Depends on**: existing tree_lock, PageIndex publication and CatalogStore; independent of M1.
- **Interface Skeleton**:

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:193
class Bookstore:
    def __init__(self, locations: list[LibraryLocation], adapter: Optional[Any] = None,
                 lightweight_model: Optional[str] = None, *,
                 reindex_lock_timeout_s: float = 5.0) -> None:
        """Configure the library and bounded operation-lock acquisition."""
    async def _ready_toolkit(self, scope: str) -> PageIndexToolkit:
        """Await once-per-scope recovery without changing synchronous _toolkit semantics."""
    # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1061
    async def add_book(self, file_path: str | Path, scope: str = "project",
                       title: Optional[str] = None, authors: Optional[list[str]] = None,
                       topics: Optional[list[str]] = None, force: bool = False, *,
                       relate: bool = False) -> tuple[BookCard, str]:
        """Serialize identity/ingest/publication; preserve graph only for equal hash and TOC."""
    async def doctor(self, scope: Optional[str] = None, *, repair: bool = False,
                     relate: bool = False, use_llm: bool = True) -> dict[str, Any]:
        """Sweep safely, report drift/orphans/unjudged books, optionally repair or relate."""
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:163
class CatalogStore:
    def judgement_count(self, book_id: str) -> int:
        """Count rows touching either endpoint, including rel=none; no schema migration."""
```

Private operation-lock context managers live in library.py and follow §2 ordering.
Existing _sweep_reserved_trees, remove_book, optimize_book and async consumers are modified
without changing their public signatures. Doctor collects counts across configured scopes;
CatalogStore.judgement_count uses parameterized SQL and existing connection management.

### Module 5: CLI commands

- **Paths**: C/knowledge/bookstore/cli.py; new test_agentic_cli.py under Bookstore tests.
- **Depends on**: M1 for ask; M4 for doctor. Both use existing resolve_adapter.
- **Interface Skeleton**:

```python
# attach to bookstore group, verified: packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:98
def ask_cmd(book_id: str, query: str, llm: Optional[str], budget_chars: Optional[int],
             max_reads: Optional[int], timeout_s: Optional[float], as_json: bool) -> None:
    """Delegate one cited research question and render human or JSON output."""
def doctor_cmd(global_scope: bool, repair: bool, relate: bool, no_llm: bool,
                llm: Optional[str], as_json: bool) -> None:
    """Report recovery and drift, optionally repair cards and build missing judgements."""
```

Use existing click/asyncio.run pattern only at the synchronous CLI boundary. Keep heavy
imports in command bodies. No application print calls; click.echo handles CLI output.

### Module 6: Host evaluation and documentation

- **Paths**: new C/knowledge/bookstore/agentic_eval.py; new core Bookstore
  test_agentic_eval.py; sdd/state/FEAT-858/agentic-eval-questions.json created by the host
  evaluation task; wiki pages listed in §10. library.py may receive measured default
  constants only after a valid report; serialize that task with M1/M4.
- **Depends on**: M1 and M4, and all user surfaces for final documentation; live execution
  must run on the host with its corpus, never a worker sandbox with invented measurements.
- **Interface Skeleton**:

```python
class EvalQuestion(BaseModel):
    """Question and pinned gold address, never sampled source text."""
    question_id: str
    book_id: str
    question: str
    provenance: Literal["handwritten", "generated"]
    doc_id: str
    revision: str
    generation: int
    gold_kind: Literal["seq", "node", "page"]
    gold_seq: Optional[int] = None
    gold_node_id: Optional[str] = None
    gold_page: Optional[int] = None
class EvalSettings(BaseModel):
    """Validated host invocation and fixed experiment budgets."""
    library: Path
    questions: Path
    llm: str = "google:gemini-3.5-flash-lite"
    concurrency: int = 1
    out_dir: Path = Path("artifacts/logs/bookstore_agentic_eval")
async def generate_questions(settings: EvalSettings) -> list[EvalQuestion]:
    """Generate five questions per book once from >=40-token segments; retain no source text."""
async def evaluate_library(settings: EvalSettings) -> dict[str, Any]:
    """Run the frozen 140-row plan, write numeric evidence, return report paths and recommendation."""
def main(argv: Optional[list[str]] = None) -> int:
    """Run --library/--questions/--llm/--concurrency, or explicit --generate-questions mode."""
```

Use Pydantic v2 validators to enforce exactly one gold address kind, nonempty IDs and
positive concurrency; no placeholder addresses in the executable fixture. Use AbstractClient
through resolve_adapter/Bookstore for generation and retrieval. Five generated questions per
book are sampled once with a recorded deterministic seed; the model never generates its own
gold address. Gold is the paragraph supplied to it. Do not overwrite an existing fixture;
regeneration is explicit and produces a new version.

## Worktree Strategy

- **Isolation**: per-spec, one feature worktree; task sub-worktrees may run concurrently.
- **Dependency graph**: M2 -> M1 (facade signatures); M3 -> M1 (revision guard/decoration);
  M5 -> M1 and M4 (CLI calls); M6 -> M1 and M4 (evaluation), and M2/M3/M5 for final docs.
  Nine dependency edges in total including documentation; task decomposition should use actual artifact needs,
  not a blanket module chain. M1 and M4 have no logical dependency, but share library.py.
- **Shared files**: library.py (M1/M4/measured-default portion of M6), and CLI command
  registrations within M5. Serialize overlapping file tasks; do not create artificial
  dependency chains for independent origin/tool tests.
- **Exclusive resources**: host EPUB re-index, question fixture generation, live evaluation
  and default promotion are parallel:false. No dependency/lockfile migration is planned.
- **Cross-feature dependencies**: FEAT-615, FEAT-831, FEAT-840, FEAT-843, FEAT-846 and
  FEAT-848 contracts are present in the verified base. Do not wait for ebook heading or
  large-leaf fixes; record tree shape and compare in the deferred rerun.

## 4. Test Specification

### Unit Tests

| Area | Required cases |
|---|---|
| Delegation | Exact parameter forwarding; no second LLM loop; no-LLM/unsupported provider; legacy segments |
| Decoration | Ownership/section/page/absent fallback; ambiguous owner; generation mismatch; no mutation of evidence |
| Revision guard | Matching/mismatching revision; swap between lookup and read; cursor mismatch; unchanged default API |
| Origin | LLM node_list and BM25 results; empty scope filter; explicit unknown ID; k cap and stable ranks |
| Excerpts | Clip below 500 chars; nonzero offsets; multiple segments; invalid/missing revisions; validate stored text |
| Diagnostics | Partial and all-skipped notes; concurrent calls cannot leak notes; legacy origins and FTS unchanged |
| Locking | Same SHA/different path, same path/new SHA, same/new slug contention, timeout and cancellation |
| Graph | Equal hash+TOC preserves; changed bytes with same TOC invalidates; changed TOC invalidates; unknown hash invalidates |
| Recovery | Concurrent initialization; cancelled init retries; active staging older than hour survives; stale cleanup/legacy restore |
| Doctor | Drift repair, orphan no repair, busy/error report, judgement rel=none counts, zero targets never relates all books |
| CLI/MCP | 14 tools visible without LLM; expected_revision schema; JSON stdout purity; resolved model stderr; doctor no-LLM |
| Evaluation | 140 planned rows, pinned stale fixture, separate provenance, safe error fields, 80% gate and fixed selection rule |

### Integration Tests

Use real temporary Markdown trees and fake AbstractClient-compatible clients, not a real
provider. Prove add -> agentic -> origin -> revision-guard read; changed-text/same-heading
re-import rejects old citations; two processes importing the same source produce one safe
publication or a clear timeout; sweep skips an actively locked stale-looking staging tree.
Inject failure before rename, after rename/before catalog upsert, and during cleanup.
Run existing Bookstore/segment/PageIndex agentic and multi-origin regressions unchanged.

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/bookstore/test_library.py
- packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py
- packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py
- packages/ai-parrot/tests/knowledge/bookstore/test_segment_reads.py
- packages/ai-parrot/tests/knowledge/bookstore/test_cli.py
- packages/ai-parrot/tests/knowledge/bookstore/test_catalog.py
- packages/ai-parrot/tests/knowledge/bookstore/test_relations.py
- packages/ai-parrot/tests/knowledge/bookstore/test_agentic_retrieval.py
- packages/ai-parrot/tests/knowledge/bookstore/test_revision_guard.py
- packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py
- packages/ai-parrot/tests/knowledge/bookstore/test_doctor.py
- packages/ai-parrot/tests/knowledge/bookstore/test_agentic_cli.py
- packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py
- packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py
- packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py
- packages/ai-parrot-tools/tests/multistoresearch/test_pageindex_origin.py
- packages/ai-parrot-tools/tests/multistoresearch/test_wiki_origin.py
- packages/ai-parrot-tools/tests/multistoresearch/test_bookstore_origin.py
- packages/ai-parrot-tools/tests/multistoresearch/test_origin_sections.py
markers: none

New operands above are created by their owning modules before feature validation. No
real_llm operand is in this deterministic contract; host evaluation is separate evidence.
All test logs go to artifacts/logs/. No deterministic E2E gate is declared for this slice.

### Test Data / Fixtures

Synthetic two-generation Markdown books cover exact whitespace, partial paragraph offsets,
nested ownership, section-only fallback, PDF-style pages, duplicate IDs across scopes,
missing revisions and stale catalogs. Fake clients return both valid and invalid citations
and each real stopped value. Use temporary directories; never mutate the host corpus in tests.

### Host evaluation protocol and question review

Library: the owner's parrot-bookstore project library recorded in the brainstorm; resolve
its actual path on the host at task time. Five current segment-backed books plus Zaratustra
and Kierkegaard EPUBs are included. Re-index the two EPUBs with --force --no-llm before
freezing gold addresses; exclude the two page-extraction duplicates whose source is gone.
If an EPUB fails, mark its planned rows skipped and keep the planned denominator at 140.
Do not silently reduce the denominator or invent replacement corpus rows.

Draft the following 21 handwritten questions for owner review. The gold target column is
an editorial locating hint, **not a verified node/page address**. The host task must inspect
the stored book, bind a real node/page plus doc_id/revision/generation, and obtain the owner's
review before freezing the fixture. If a question is unsupported in the edition, revise it
with the owner; do not guess a node or infer gold from the retrieval answer under evaluation.

| Book | Three handwritten questions | Gold target to verify |
|---|---|---|
| Amor y pedagogía | ¿Qué pretende conseguir Avito con la educación de su hijo? / ¿Qué papel tiene don Fulgencio en ese proyecto? / ¿Cómo cuestiona la novela una educación gobernada únicamente por la ciencia? | Avito's plan; Fulgencio's advice; consequences for Apolodoro |
| Analectas | ¿Cómo relaciona Confucio el aprendizaje con la reflexión? / ¿Qué exige la reciprocidad en el trato con los demás? / ¿Qué diferencia al hombre noble del hombre vulgar? | Corresponding maxims in the stored translation |
| Crítica de la razón pura | ¿Qué distingue los juicios analíticos de los sintéticos? / ¿Qué función tienen el espacio y el tiempo en el conocimiento? / ¿Por qué la razón incurre en antinomias? | Introduction; Transcendental Aesthetic; antinomies section |
| Don Quijote | ¿Por qué interpreta don Quijote los molinos como gigantes? / ¿Qué consejo da don Quijote a Sancho sobre la justicia al gobernar? / ¿Cómo describe el discurso de las armas y las letras sus distintas dificultades? | Windmills; advice to Sancho; arms and letters discourse |
| Meditaciones | ¿Cómo propone Marco Aurelio responder a la ira ajena? / ¿Qué relación establece entre el juicio y el sufrimiento? / ¿Por qué insiste en actuar por el bien de la comunidad? | Verified passages on anger, judgment and common good |
| Así habló Zaratustra | ¿Qué representan el camello, el león y el niño? / ¿Qué critica Zaratustra en el último hombre? / ¿Cómo aparece la idea del eterno retorno? | Three metamorphoses; prologue; eternal-return passages |
| El concepto de la angustia | ¿Cómo distingue Kierkegaard la angustia del miedo? / ¿Qué relación tiene la angustia con la posibilidad y la libertad? / ¿Cómo conecta la inocencia con la ignorancia? | Stored discussion of anxiety, freedom and innocence |

Add five model-generated questions per book from sampled segments >=40 tokens, keeping
questions, provenance and addresses only. Freeze 56 questions once, never regenerate per run.
A gold hit is a validated citation with matching doc_id/revision and seq, or whose seq belongs
to the frozen gold node's owned ranges; page-gold compares the validated citation page.
Node ownership must be checked against the frozen generation; reject stale fixtures before
executing that book's rows. Persist hashes of the fixture and relevant tree snapshots.

Plan: 56 baseline runs at 40000 chars / 12 reads / 20 tool calls / 120 s; then the 21
handwritten questions at each of (20000 chars,12 reads), (60000 chars,12 reads),
(40000 chars,8 reads), (40000 chars,16 reads), keeping other knobs fixed. Total 140.
Use one independent Bookstore and adapter/client per worker; toolkit serialization prevents
useful parallelism within one instance. Default concurrency=1; caller may explicitly raise it.
Cap agentic invocations at the frozen 140 rows and question generation at 35 successful
questions with a bounded retry policy (at most one repair call per generated question).

Each row records question ID/book/settings/provenance, execution status (completed/error/
skipped/stale), actual PageIndex stopped value when present, grounded, gold_hit, kept/rejected
counts, chars_read, tool_calls, usage and monotonic wall seconds. Error rows store only a safe
error category, never provider exception text or answers. Include timeouts/provider_error as
failed executions for tuning coverage even if they return a bundle. Report grouped statistics
per book, provenance and setting with denominators, planned/attempted/completed counts, plus
tree node count/largest-leaf tokens/owned-node count. Never persist source excerpts, prompts,
responses or drafted answers in report/log artifacts. Question fixture contains original
questions and addresses only. Host failure remains visible; no fabricated metrics.

Default-selection rule: require >=112 completed rows out of 140 AND >=17 of the 21
handwritten rows completed in each compared setting. Missing/error rows count as zero for
quality rates. Compare each candidate to the baseline on the same 21 handwritten questions;
qualify only if grounded and gold-hit counts are both no worse. Among qualifying settings
choose lowest median chars_read, then lowest median wall time, then fewer max_reads, then
smaller budget_chars; retain baseline on a complete tie. Do not combine independently winning
knobs into an untested setting. Keep max_tool_calls=20 and timeout_s=120 unchanged. If no
candidate qualifies retain baseline; if coverage is insufficient publish no recommendation.
Generated-question quality is reported separately and cannot replace handwritten evidence.

Write artifacts/logs/bookstore_agentic_eval/<UTC timestamp>/report.md and machine-readable
metrics, with experiment count and hashes in the header. M6 copies values programmatically
from the metrics into the wiki and records the report SHA256. A subsequent measured-default
commit may alter Bookstore-local defaults only; PageIndex defaults remain unchanged. Failed
coverage leaves the task's evaluation evidence incomplete; do not claim completion or tune.

## 5. Acceptance Criteria

- [ ] AC-1: Per-book agentic retrieval delegates once, preserves all validated evidence and actual stop reasons, and decorates labels without a second LLM call.
- [ ] AC-2: Legacy/no-LLM/unsupported-client cases explain the failure; all 14 MCP tools remain discoverable without a model.
- [ ] AC-3: expected_revision rejects mismatched returned text, including a re-import between lookup and read; omitted guard retains compatibility.
- [ ] AC-4: Origin handles both stage-1 shapes, scope filtering, exact clipped single-segment evidence, deterministic k/ranks and revision validation.
- [ ] AC-5: Partial/all-skipped diagnostics are request-local; failures/timeouts isolate Bookstore from other origins; no agentic loop runs in the origin.
- [ ] AC-6: Equal nonempty source hash plus TOC preserves graph/community; either difference invalidates after successful publication/upsert; failed ingestion preserves prior state.
- [ ] AC-7: Cross-process same-source/new-slug imports serialize or fail within the configured acquisition deadline; publication never reacquires a held live lock.
- [ ] AC-8: Awaited initialization is race/cancellation safe; recovery skips active staging even beyond one hour, restores legacy replacements and reports failures.
- [ ] AC-9: Doctor reports drift/orphans/unjudged books, repairs only deterministic structural fields, and never calls a model without --relate; zero targets do not trigger a library-wide relation run.
- [ ] AC-10: ask/doctor flags, human output, JSON purity and stderr model identity match §2.
- [ ] AC-11: The frozen reviewed fixture and actual host report account for all 140 planned rows, separate provenance, protect source text and apply the fixed coverage/tuning policy.
- [ ] AC-12: Tests in the validation contract pass; existing public models and APIs remain compatible; docs include measured defaults and report hash or explicitly insufficient evidence.


## 6. Codebase Contract

Source base: `d643c0c0d4eb5fd1f3ae505fd942bb361d80e332`. The entire brainstorm Code Context is carried below with verified corrections. Path abbreviations inside comments are relative to the explicitly named distribution source root. Do not infer implementations from abbreviated signatures.


### User-Provided Code

None. The brainstorm references below were rechecked at `d643c0c0d4eb5fd1f3ae505fd942bb361d80e332`; this is a signature synopsis, not implementation code. Historical corpus observations are labeled separately.

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):                                     # line 161
    llm_dependent_tools: frozenset[str]  # includes "pageindex_agentic_retrieve"  # lines 206-214
    def __init__(self, adapter=None, storage_dir=None, reranker=None, lightweight_model=None, model=None, ...,
                 agentic_client: Optional[AbstractClient] = None,            # line 236
                 agentic_budget_chars: int = 40000,                          # line 237
                 agentic_max_reads: int = 12,                                # line 238
                 agentic_max_tool_calls: int = 20,                           # line 239
                 agentic_timeout_s: float = 120.0, ...)                      # line 240
    async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]:  # line 741
    async def list_documents(self, tree_name: str) -> list[dict[str, Any]]:  # line 970
    async def read_segments(...)                                             # line 1117
    def _agentic_client(self) -> AbstractClient:                             # line 1223
    async def agentic_retrieve(self, tree_name: str, query: str, top_k: int = 5, draft_answer: bool = True,
                               budget_chars: Optional[int] = None, max_reads: Optional[int] = None,
                               timeout_s: Optional[float] = None) -> dict[str, Any]:  # line 1240
    async def search_documents_scoped(self, tree_names: list[str], query: str, include_tree_context: bool = False,
                                      max_trees: int = _MAX_TREES_HARD_CAP, ...)  # line 1763
REPLACED_MARKER = "--replaced-"                                              # line 153

# From packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py
class AgenticAnswer(BaseModel): answer: Optional[str]; citations: list[ProposedCitation]   # line 65
class EvidenceBundle(BaseModel):                                             # line 72
    tree_name: str; query: str; generation: Optional[int]; candidates: list[dict]; reads: list[LedgerEntry]
    citations: list[Citation]; rejected: list[RejectedCitation]; answer: Optional[str]; grounded: bool
    tool_calls: int; chars_read: int; stopped: StopReason; usage: dict[str, int]; rendered_citations: str
def require_tool_loop(client: AbstractClient) -> None:                       # line 91
def clone_for_tools(client: AbstractClient) -> AbstractClient:               # line 107
class AgenticRetriever:                                                      # line 183
    def __init__(self, *, client: AbstractClient, model: Optional[str], read_tools: Sequence[AbstractTool],
                 load_revision: Callable[[str, str], Optional[DocumentRevision]]) -> None:  # line 188
    async def run(self, *, tree_name: str, query: str, candidates: list[dict[str, Any]], outline: dict[str, Any],
                  generation: Optional[int], budget_chars: int, max_reads: int, max_tool_calls: int,
                  deadline: float, draft_answer: bool) -> EvidenceBundle:    # line 297

# From packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py
class ProposedCitation(BaseModel):                                           # line 40
class Citation(BaseModel):                                                   # line 47
    doc_id: str; revision: str; seq: int; page: Optional[int]; ordinal: int; section: Optional[list[str]]
    start: int; end: int; excerpt: str; label: str; document: str
class RejectedCitation(BaseModel):                                           # line 63
def find_covered_match(segment_text: str, excerpt: str, covered: list[Range]) -> Optional[Range]:  # line 92
def find_any_match(segment_text: str, excerpt: str) -> bool:                 # line 102
def validate_citations(ledger: ReadLedger, load_revision: Callable[[str, str], Optional[DocumentRevision]],
                       proposed: Sequence[ProposedCitation]) -> tuple[list[Citation], list[RejectedCitation]]:  # line 107
def render_citation(citation: Citation) -> str:   # "[<document>, <label>]"  # line 182
def render_citations(citations: Sequence[Citation]) -> str:                  # line 187

# From packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel): seq: int; kind: SegmentKind; page: Optional[int]; ordinal: int;
    section: Optional[list[str]]; level: Optional[int]; text: str; tokens: int; flags: list[str]  # line 33
class DocumentRevision(BaseModel):                                           # line 59
class SegmentRead(BaseModel): address: SegmentAddress; seq: int; kind: SegmentKind; text: str;
    start: int; end: int; truncated: bool = False; flags: list[str]          # line 97
class ReadResult(BaseModel): tree_name: str; doc_id: str; revision: str; generation: Optional[int];
    segments: list[SegmentRead]; truncated: bool; next_cursor: Optional[str]; framed: str  # line 110
def validate_ownership(nodes: Sequence[dict], revision: DocumentRevision) -> list[str]:  # line 490
#   reads node["owned"]: list of half-open [start, end) seq ranges           # lines 498-500
#   PDF segments are built with section=None                                  # line 236
def segment_text(text: str, section: list[str], *, seq_start: int = 0) -> list[Segment]:  # line 240
#   markdown/ebook segments carry section=list(section)                       # line 245

# From packages/ai-parrot/src/parrot/knowledge/pageindex/read_ledger.py
class LedgerEntry(BaseModel):                                                # line 25
class ReadLedger:  def __init__(self, *, budget_chars: int, max_reads: int) -> None:  # lines 47, 50

# From packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py
class TreeLockTimeout(TimeoutError):                                         # line 30
def lock_path(storage_dir: Path, tree_name: str) -> Path:                    # line 34
@asynccontextmanager
async def tree_lock(storage_dir: Path, tree_name: str, *, timeout: float) -> AsyncIterator[None]:  # line 48

# From packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
_STAGING_MARKER = "--staging-"                                               # line 69
_STAGING_MAX_AGE_S = 3600                                                    # line 70
class _NullAdapter:                                                          # line 150
class Bookstore:                                                             # line 179
    def __init__(self, locations: list[LibraryLocation], adapter: Optional[Any] = None,
                 lightweight_model: Optional[str] = None, ...) -> None:      # line 193
    def has_llm(self) -> bool:                                               # line 216
    def _toolkit(self, scope: str) -> PageIndexToolkit:                      # line 234
    def _staging_tree_name(self, slug: str) -> str:                          # line 271
    def _scan_reserved_trees(trees_dir: Path) -> list[tuple[str, bool, float]]:  # line 276 (staticmethod)
    async def _sweep_reserved_trees(self, scope: str) -> None:               # line 293
    def list_books(self) -> list[BookCard]:                                  # line 330
    def catalog_search(self, query: str, top_k: int = 8) -> list[BookCard]:  # line 334
    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]:  # line 338
    async def search_book(self, book_id: str, query: str, top_k: int = 8) -> list[dict[str, Any]]:  # line 365
    async def _document_of(self, card: Any, toolkit: PageIndexToolkit) -> dict[str, Any]:  # line 404
    def _book_result(card: Any, result: dict[str, Any]) -> dict[str, Any]:  # line 412 (staticmethod)
    async def read_segments(self, book_id: str, start: Optional[int] = None, end: Optional[int] = None,
                            node_id: Optional[str] = None, max_chars: int = 12000,
                            cursor: Optional[str] = None) -> dict[str, Any]:  # line 434
    async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3,
                     top_k: int = 5, expand_related: bool = False) -> dict[str, Any]:  # line 495
    async def relate_books(self, book_ids: Optional[list[str]] = None, *, use_llm: bool = True,
                           communities: bool = True, communities_only: bool = False, force: bool = False,
                           resolution: float = 1.0, ...)                     # line 711
    def _clear_communities(self) -> None:                                    # line 945
    async def add_book(self, file_path: str | Path, scope: str = "project", title: Optional[str] = None,
                       authors: Optional[list[str]] = None, topics: Optional[list[str]] = None,
                       force: bool = False, *, relate: bool = False) -> tuple[BookCard, str]:  # line 1061
    def _invalidate_graph(self, book_id: str) -> None:                       # line 1421
    async def remove_book(self, book_id: str) -> bool:                       # line 1434

# add_book edit sites (library.py)
#   await self._sweep_reserved_trees(scope)                                  # line 1107
#   staging = self._staging_tree_name(slug)                                  # line 1126
#   await toolkit.rename_tree(staging, slug, overwrite=status == "updated")  # line 1229
#   catalog.upsert(card)                                                     # line 1239 (PR #2052: now before invalidation)
#   if status == "updated": self._invalidate_graph(slug)                     # lines 1240-1241

# From packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py
class BookstoreToolkit(AbstractToolkit):                                     # line 29
    name = "bookstore"; tool_prefix = "bookstore"                            # lines 36-37
    def __init__(self, bookstore: Bookstore, **kwargs: Any) -> None:         # line 39
    async def read_segments(self, book_id: str, start=None, end=None, node_id=None, max_chars: int = 12000,
                            cursor=None) -> dict[str, Any]:                  # line 140
    async def search(self, query: str, book_ids: Optional[list[str]] = None, max_books: int = 3,
                     expand_related: bool = False) -> dict[str, Any]:        # line 249

# From packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py
class CatalogStore:
    def upsert(self, card: BookCard) -> None:                                # line 300
    def find_by_sha(self, sha256: str) -> Optional[BookCard]:                # line 380
    def find_by_path(self, source_path: str) -> Optional[BookCard]:          # line 386
    def delete_relations(self, book_id: Optional[str] = None, origin: Optional[str] = None) -> int:  # line 526
    def delete_judgements(self, book_id: str) -> int:                        # line 650

# From packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
class BookCard(BaseModel):  # line 152; fields at lines 159-181
    book_id: str; title: str; authors: list[str]; toc_digest: str = ""; toc: list[TocEntry]; tree_name: str
    scope: Literal["project", "global"]; source_path: str; source_format: Literal[...]; page_count: Optional[int]
    chapter_count: int; added_at: str; card_origin: Literal["llm", "fallback", "manual"]
    community_id: Optional[str]; community_label: Optional[str]

# From packages/ai-parrot/src/parrot/knowledge/bookstore/config.py
Scope = Literal["project", "global"]                                         # line 29

# From packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py
def resolve_adapter(...) -> tuple[adapter, lightweight_model, client]  # all None when no LLM  # line 42

# From packages/ai-parrot/src/parrot/models/stores.py
class SearchOriginKind(Enum): VECTOR = "vector"; PAGEINDEX = "pageindex"; GRAPHINDEX = "graphindex"; WIKI = "wiki"  # line 31
class OriginHit(BaseModel): id: Optional[str]; content: str; score: Optional[float]; metadata: Dict[str, Any];
    origin: str; origin_kind: SearchOriginKind; native_rank: int           # line 79
class OriginSection(BaseModel): origin: str; origin_kind: SearchOriginKind; description: str; status: str;
    note: Optional[str]; hits: List[OriginHit]                              # line 106

# From packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py
class SearchOrigin(ABC):                                                     # line 18
    name: str; kind: SearchOriginKind; description: str; supports_fts: bool = False; timeout: Optional[float] = None
    async def search(self, query: str, k: int) -> List[OriginHit]:          # line 42 (abstract)
    async def fts_search(self, query: str, k: int) -> List[OriginHit]:      # line 54

# From packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/wiki.py
class ParrotWikiOrigin(SearchOrigin):                                       # line 21
    def __init__(self, store: "BaseWikiStore", embedder=None, category: Optional[str] = None,
                 name: str = "wiki", description: Optional[str] = None, ...)  # line 46
    async def search(self, query: str, k: int) -> List[OriginHit]:          # line 71

# From packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py
class MultiStoreSearchToolkit(AbstractToolkit):                              # line 39
    def __init__(self, origins: List[SearchOrigin], ..., k_per_origin: int = 20, ...)  # line 65
    async def store_search(...)                                              # line 85
    async def list_search_origins(self) -> List[Dict[str, Any]]:             # line 193
```

#### Verified Imports
```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER   # library.py:31 imports both
from parrot.knowledge.pageindex.agentic import AgenticRetriever, EvidenceBundle, require_tool_loop, clone_for_tools
from parrot.knowledge.pageindex.citations import Citation, find_any_match, render_citation, render_citations
from parrot.knowledge.pageindex.segments import SegmentRead, ReadResult, DocumentRevision
from parrot.knowledge.pageindex.locks import tree_lock, TreeLockTimeout
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.bookstore.toolkit import BookstoreToolkit
from parrot.knowledge.bookstore.models import BookCard, TocEntry
from parrot.models import OriginHit, SearchOriginKind            # re-exported at parrot/models/__init__.py:109 (multi-line from .stores import); used by origins/pageindex.py:26
from parrot_tools.multistoresearch.origins import SearchOrigin, PageIndexOrigin, ParrotWikiOrigin  # origins/__init__.py
from parrot_tools.multistoresearch import MultiStoreSearchToolkit  # multistoresearch/__init__.py:13
```

#### Key Attributes & Constants
- `PageIndexToolkit.llm_dependent_tools` → `frozenset[str]` containing `"pageindex_agentic_retrieve"`
  (`pageindex/toolkit.py:206-214`) — Bookstore deliberately does **not** adopt this (discovery decision).
- `PageIndexToolkit._agentic_budget_chars/_agentic_max_reads/_agentic_max_tool_calls/_agentic_timeout_s`
  (`pageindex/toolkit.py:279-282`) — the defaults Bookstore inherits until the eval fixes its own.
- `Bookstore._toolkit(scope)` builds one `PageIndexToolkit` per scope with `generation_grace_s=_STAGING_MAX_AGE_S`
  and `_NullAdapter()` when no adapter (`library.py:234-243`) → explicitly check Bookstore.has_llm before delegation; do not assume a null client raises ValueError.
- `Bookstore.search` returns `{"query", "books": [{"book_id", "title", "scope", "results": [...] | per-node items}]}`;
  the LLM branch spreads `search_documents_scoped` items (`library.py:540-575`), the BM25 branch uses
  `results` from toolkit.search, with node_id/title/summary/score/source (`library.py:365-378`, `:565-574`). The LLM branch returns node_list/context, not results.
- `Bookstore.read_segments` returns `_book_result(card, ReadResult.model_dump())` → `{"book_id","book_title", **ReadResult}` (`library.py:446-460`, `:412`).
- `bookstore mcp` degradation matrix (the prose tool count is stale: test_mcp_server.py:50 verifies 13 tools): `mcp_server.py:7-18`.
- `bookstore` CLI commands: add, add-folder, list, show, toc, search, card, update, related, relate,
  communities, export-wiki, optimize, remove, mcp, locations (`cli.py:102-654`) — **no `doctor`**.
- Existing tests to extend: `packages/ai-parrot/tests/knowledge/bookstore/{test_library,test_toolkit,test_mcp_server,test_segment_reads}.py`,
  `packages/ai-parrot-tools/tests/multistoresearch/{test_pageindex_origin,test_wiki_origin,test_toolkit}.py`,
  `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py`.
- Evaluation harness pattern: `pageindex/optimizer_eval.py` (`python -m …`, writes `artifacts/logs/<name>/<ts>/report.md`).
- Historical library state from the brainstorm, NOT re-measured during specification (2026-11-09) (`~/proyectos/parrot/parrot-bookstore/.parrot/library`):

  | book | format | segments | with `section` | nodes | nodes with `owned` |
  |---|---|---|---|---|---|
  | amor-y-pedagogia-unamuno-miguel | mobi | 1393 | 1393 | 1 | 1 |
  | analectas-confucio | pdf | 1187 | 0 | 44 | 44 |
  | critica-de-la-razon-pura-immanuel-kant | pdf | 1097 | 0 | 4 | 4 |
  | don-quijote-de-la-mancha-cervantes-miguel | mobi | 3708 | 3708 | 9 | 9 |
  | las-meditaciones-de-marco-aurelio-marco-aurelio | pdf | 1045 | 0 | 16 | 15 |
  | asi-hablo-zaratustra-friedrich-nietzsche | epub | none | — | 8 | 0 |
  | el-concepto-de-la-angustia-kierkegaard-soren | epub | none | — | 1 | 0 |
  | analectas-extraccion-por-paginas-pdf | md | none | — | 146 | 0 |
  | meditaciones-extraccion-por-paginas-pdf | md | none | — | 103 | 0 |

  Every card is `card_origin` `fallback` or `manual`; `book_relations`, `relation_judgements` and
  `communities` are empty. The Meditaciones node without `owned` is the empty "Preface" leaf of
  issue `33ad15e686e9`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_tools.multistoresearch.origins.BookstoreOrigin`~~ — no Bookstore origin; `origins/` holds only
  `base, vector, pageindex, graphindex, wiki, lancedb`.
- ~~`SearchOriginKind.BOOKSTORE`~~ — enum has `VECTOR, PAGEINDEX, GRAPHINDEX, WIKI` only (to be added).
- ~~`Bookstore.agentic_retrieve`~~ / ~~`BookstoreToolkit.agentic_retrieve`~~ / ~~`bookstore_agentic_retrieve`~~ — not present.
- ~~`BookstoreToolkit.llm_dependent_tools`~~ — only `PageIndexToolkit` has it; Bookstore will not add it.
- ~~`parrot.knowledge.bookstore.models.BookCitation`~~ — no such model (decision: metadata, not a model).
- ~~`bookstore doctor`~~ and ~~`bookstore ask`~~ CLI commands — do not exist.
- No public chapter-resolution helper exists. `pageindex/optimizer.py:834` already builds an internal seq-to-owner map in reconcile_key_items; Bookstore needs a read-only document/generation-aware lookup, not that mutating optimizer function.
- ~~`parrot.knowledge.bookstore.agentic_eval`~~ — no Bookstore evaluation harness yet.
- ~~`OriginHit.citation`~~ — `OriginHit` has no citation field (Option C, rejected).
- ~~Per-slug lock in `Bookstore.add_book`~~ — no `lock`/`Lock` usage in `library.py` today.
- ~~`AgenticRetriever.run(tree_names=[...])`~~ — `run()` takes a single `tree_name` (Option B would need this).

---

### Additional verified contracts and corrections

| Contract | Exact source anchor | Consequence |
|---|---|---|
| tree_lock(storage_dir: Path, tree_name: str, *, timeout: float) -> AsyncIterator[None] | packages/ai-parrot/src/parrot/knowledge/pageindex/locks.py:48 | Non-reentrant; separate operation storage namespace |
| WriteTransaction.publish() -> PublishReport acquires destination lock | packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py:203 | Never hold the live lock around rename_tree |
| Bookstore._toolkit(scope: str) -> PageIndexToolkit | packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:234 | Synchronous; introduce async readiness wrapper |
| derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str] | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:124 | Rendered heading/page digest, not a content hash |
| SegmentStore(storage_dir: str or Path, cache_size: int = 8) | packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py:28 | Read exact immutable revision for evidence validation |
| load_revision(self, tree_name: str, doc_id: str, revision: str) -> Optional[DocumentRevision] | packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py:87 | Missing revision returns None, never current text |
| ReadResult.revision and generation; RevisionMismatchError(ValueError) | packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:110 | Check actual result before returning text |
| PageIndex read budget minimum 500 | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:886 | Explicit origin clipping is required |
| SearchOrigin.search(query: str, k: int) -> List[OriginHit] | packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:42 | Add search_section without changing search return type |
| Successful OriginSection currently has note=None | packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:304 | Add request-local successful diagnostics hook |
| CatalogStore.judged_pairs(src: str) -> set[str] | packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:641 | Outgoing only; add count touching either endpoint for doctor |
| Actual MCP discovery count is 13 | packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py:50 | New surface has 14 tools |
| Bookstore remove/optimize mutate live tree and card | packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1434 and :1463 | Join the operation-lock protocol |

Additional verified imports:

```python
from parrot.knowledge.pageindex.segment_store import SegmentStore  # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/segment_store.py:25
from parrot.knowledge.pageindex.segments import RevisionMismatchError, RevisionUnavailableError  # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:123
from parrot.knowledge.bookstore.carding import derive_toc  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:124
from parrot.knowledge.bookstore.config import LibraryLocation  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:33
from parrot.knowledge.bookstore._llm import resolve_adapter  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py:42
from parrot.models import OriginSection  # verified: packages/ai-parrot/src/parrot/models/__init__.py:115
```

New symbols that do not yet exist: expected_revision on either Bookstore read wrapper,
_ready_toolkit, doctor, CatalogStore.judgement_count, SearchOrigin.search_section,
BookstoreOrigin, and the agentic evaluation module. StopReason has no stale/error member;
use actual upstream states and separate evaluation execution status.

### Edit Sites (Blueprint Anchors)

Verified against `d643c0c0d4eb5fd1f3ae505fd942bb361d80e332`. Counts below were obtained with
`grep -cF -- <verbatim anchor> <path>`; every MODIFY anchor is unique. Class/group anchors
identify the existing container for multiple method edits, whose exact method locations
are documented above. Reverify before task blueprint generation.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `class Bookstore:` | `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | MODIFY | `class CatalogStore:` | `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:163` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` | MODIFY | `class BookstoreToolkit(AbstractToolkit):` | `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:29` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py` | MODIFY | `def create_bookstore_mcp_server(` | `packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py:61` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `def bookstore() -> None:` | `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py:98` | 1 |
| `packages/ai-parrot/src/parrot/models/stores.py` | MODIFY | `class SearchOriginKind(Enum):` | `packages/ai-parrot/src/parrot/models/stores.py:31` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py` | MODIFY | `class SearchOrigin(ABC):` | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:18` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` | MODIFY | `from .wiki import ParrotWikiOrigin` | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py:12` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py` | MODIFY | `class MultiStoreSearchToolkit(AbstractToolkit):` | `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:39` | 1 |
| `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py` | MODIFY | `EXPECTED_TOOLS = {` | `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py:13` | 1 |
| `packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py` | MODIFY | `def test_mcp_tools_list_has_thirteen_tools(seeded_locations):` | `packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py:48` | 1 |
| `wiki/knowledge/bookstore-codex.md` | MODIFY | `## Start a session` | `wiki/knowledge/bookstore-codex.md:35` | 1 |
| `wiki/knowledge/bookstore-graph.md` | MODIFY | `## Degradation matrix` | `wiki/knowledge/bookstore-graph.md:142` | 1 |
| `wiki/knowledge/pageindex-agentic-retrieval.md` | MODIFY | `## Related` | `wiki/knowledge/pageindex-agentic-retrieval.md:264` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/bookstore.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/agentic_eval.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_retrieval.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_revision_guard.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_reindex_hardening.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_doctor.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_cli.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_eval.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/multistoresearch/test_bookstore_origin.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/multistoresearch/test_origin_sections.py` | CREATE | — | — | — |
| `wiki/knowledge/bookstore-agentic-retrieval.md` | CREATE | — | — | — |
| `sdd/state/FEAT-858/agentic-eval-questions.json` | CREATE | — | — | — |


## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first I/O, existing resource/lifecycle patterns, Pydantic v2 for new structured
  evaluation models, self.logger for runtime messages, Click for command output.
- Reuse existing dependencies only. Offload blocking filesystem/catalog reads in new async
  orchestration paths using the repository's existing asyncio.to_thread I/O pattern; do not
  execute synchronous DB/file loops on the event loop or use threads for CPU-heavy work.
- Existing AbstractToolkit discovery and docstring-based descriptions remain authoritative.
  New bookkeeping helpers are private and must not appear as MCP tools.
- Do not touch clients/base.py, agentic.py, citations.py, segment models, or PageIndex
  publication implementation. All new behavior composes verified primitives.
- Preserve Python positional compatibility by appending optional parameters; constructor
  reindex options and library revision guard are keyword-only. Do not add dependencies.
- Tests use deterministic fixtures/fake clients. Live provider work belongs only in the
  bounded host task, with real recorded results and explicit model/concurrency arguments.

### Known Risks / Gotchas

- A metadata TOC digest is not proof of text identity; the accepted source hash condition
  reduces false graph preservation. Repaired/unknown source hashes never qualify.
- Catalog and live tree publication are still two steps. Doctor detects structural drift;
  identical-TOC content drift requires broader future transaction metadata. Do not claim
  complete crash-consistency for the catalog.
- Holding the PageIndex destination lock across rename deadlocks. Operation locks must use
  their separate directory and fixed ordering; recovery cannot delete a busy import.
- Direct PageIndex writers do not acquire Bookstore operation locks. PageIndex generation
  checks remain authoritative; doctor must avoid claiming a snapshot is permanently current.
- `_ready_toolkit` cannot be called recursively from sweep. Repeated asyncio.run use in CLI
  tests must not retain a pending task or lock bound to a closed loop; only store completed
  readiness state and use scope locks in the active loop.
- Success-note support touches multi-origin orchestration; regression-test all existing
  origins, duck-typed adapters and FTS. Never use mutable last-result fields.
- Bookstore's no-LLM adapter is not None; guard explicitly before calling stage 2.
- The host corpus includes a one-node Unamuno tree and a very large Quijote leaf; keep them
  in the evaluation, report shape, and treat selected budgets as provisional.
- Gold questions above are drafts; executable gold IDs must be host-verified and owner-reviewed.
  Never manufacture metrics or addresses to finish an unavailable host task.

### External Dependencies

| Package | Verified declaration | Use |
|---|---|---|
| pydantic | >=2.12.5,<3, packages/ai-parrot/pyproject.toml:54 | Existing models; evaluation schemas |
| bm25s | >=0.2, optional, packages/ai-parrot/pyproject.toml:379 | Existing no-LLM stage-1 search |
| google-genai | >=2.34.0, packages/ai-parrot-client-google/pyproject.toml:36 | Existing Google AbstractClient implementation for host evaluation only |
| click / asyncio / pathlib / hashlib | Existing CLI imports at cli.py:13-20; stdlib | CLI, locking orchestration and report hashes |

No installation or new package is part of this feature.

## Decisions

```yaml
schema_version: 1
document_id: bookstore-agentic-retrieval
entries:
  - id: separate-operation-lock
    statement: Bookstore must use a separate operation-lock namespace rather than hold the PageIndex destination lock across rename_tree.
    relation: requires
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py]
    contradicts: []
    supersedes: []
    rationale: The owner accepted this correction because destination publication reacquires a non-reentrant tree lock.
    rejected_alternatives: [Holding the live tree_lock throughout ingestion and rename]
  - id: graph-preservation-proof
    statement: Re-index may preserve relations and communities only when both nonempty source_sha256 and toc_digest match the existing card.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py]
    contradicts: []
    supersedes: []
    rationale: The owner accepted the stronger condition because the TOC digest describes headings and pages rather than content.
    rejected_alternatives: [Preserving graph on TOC equality alone]
  - id: returned-revision-guard
    statement: A supplied expected_revision must match the returned segment-read revision before Bookstore exposes the result text.
    relation: requires
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py]
    contradicts: []
    supersedes: []
    rationale: Preflight document lookup can race with re-import; the owner approved an explicit read guard.
    rejected_alternatives: [Checking only the live revision before the read]
```

## Consequences

<!-- decision-audit: input_digest=sha256:fe643c945df78c1f5f13c19d48f59c6ae87f723f7a3d624046dd7926c0e35045 evaluation_digest=sha256:50e5b850aa843d68015ac0674597dac1057be84edb6088f2741bf98a2231e3d2 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `possible-supersession` [advisory]; waived_by: not recorded; participants: adr:spec:bookstore-agentic-retrieval#graph-preservation-proof@1, adr:spec:bookstore-agentic-retrieval#returned-revision-guard@1; scope: file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py; message: adr:spec:bookstore-agentic-retrieval#graph-preservation-proof and adr:spec:bookstore-agentic-retrieval#returned-revision-guard share targets and about without an explicit link
- `possible-supersession` [advisory]; waived_by: not recorded; participants: adr:spec:bookstore-agentic-retrieval#graph-preservation-proof@1, adr:spec:bookstore-agentic-retrieval#separate-operation-lock@1; scope: file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py; message: adr:spec:bookstore-agentic-retrieval#graph-preservation-proof and adr:spec:bookstore-agentic-retrieval#separate-operation-lock share targets and about without an explicit link
- `possible-supersession` [advisory]; waived_by: not recorded; participants: adr:spec:bookstore-agentic-retrieval#returned-revision-guard@1, adr:spec:bookstore-agentic-retrieval#separate-operation-lock@1; scope: file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py; message: adr:spec:bookstore-agentic-retrieval#returned-revision-guard and adr:spec:bookstore-agentic-retrieval#separate-operation-lock share targets and about without an explicit link

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: agentic-retrieval, citations, multistoresearch, reindex
- Targets resolved: 1/1
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 1,
    "targets_total": 1,
    "unmapped_tags": [
      "agentic-retrieval",
      "citations",
      "multistoresearch",
      "reindex"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:50e5b850aa843d68015ac0674597dac1057be84edb6088f2741bf98a2231e3d2",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:22846e2844ddaa04ab477000a07d830016bc7c96a85555f1876f82b46d19906f",
      "kind": "possible-supersession",
      "message": "adr:spec:bookstore-agentic-retrieval#graph-preservation-proof and adr:spec:bookstore-agentic-retrieval#returned-revision-guard share targets and about without an explicit link",
      "participants": [
        {
          "decision_id": "adr:spec:bookstore-agentic-retrieval#graph-preservation-proof",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:bookstore-agentic-retrieval#returned-revision-guard",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:5a94959f31836dffdd79359c71e10ebba8bad9daba4e215db62ddbc70b5f5d43",
      "kind": "possible-supersession",
      "message": "adr:spec:bookstore-agentic-retrieval#graph-preservation-proof and adr:spec:bookstore-agentic-retrieval#separate-operation-lock share targets and about without an explicit link",
      "participants": [
        {
          "decision_id": "adr:spec:bookstore-agentic-retrieval#graph-preservation-proof",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:bookstore-agentic-retrieval#separate-operation-lock",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:caf57313fb4242d01e41b46118cea31d37851a97210a7c4fcd45f0761905a8a2",
      "kind": "possible-supersession",
      "message": "adr:spec:bookstore-agentic-retrieval#returned-revision-guard and adr:spec:bookstore-agentic-retrieval#separate-operation-lock share targets and about without an explicit link",
      "participants": [
        {
          "decision_id": "adr:spec:bookstore-agentic-retrieval#returned-revision-guard",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:bookstore-agentic-retrieval#separate-operation-lock",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:fe643c945df78c1f5f13c19d48f59c6ae87f723f7a3d624046dd7926c0e35045",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:cb31decc976db5fe7c2016d9730c1132da32ce3e857aeb76f39f3e6d5b0c569d",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

The following original resolutions are carried forward verbatim for auditability. Where an
original answer says same-TOC preservation or the original lock mechanics, the three explicit
owner amendments below and §2 govern implementation. Historical library counts describe the
brainstorm session, not a new measurement by this specification.


- [x] Flow type / base branch — *Owner: Jesus Lara*: feature on `dev`.
- [x] Is the re-index race still open? — *Owner: Jesus Lara*: no — FEAT-615 already implements
  staging + `rename_tree(overwrite)` + post-swap invalidation; issue `759176f0cf1a` closed with
  `resolved_by spec:FEAT-615`; this slice adds the four hardenings listed in the Problem Statement.
- [x] Shape of stage-2 inheritance in Bookstore — *Owner: Jesus Lara*: per-book
  `bookstore_agentic_retrieve` delegating to the scope toolkit; library-wide loop (Option B) rejected
  for this slice.
- [x] How citations appear in `multistoresearch` — *Owner: Jesus Lara*: new `BookstoreOrigin`,
  citation address in `OriginHit.metadata["citation"]`; `OriginHit` unchanged (Option C rejected).
- [x] What `BookstoreOrigin.search()` runs — *Owner: Jesus Lara*: stage 1 (`Bookstore.search`) plus
  bounded segment reads for exact excerpts; never the agentic loop.
- [x] MCP exposure without LLM — *Owner: Jesus Lara*: keep the Bookstore pattern — tool visible,
  explanatory error; do not adopt `llm_dependent_tools`.
- [x] Citation label for books — *Owner: Jesus Lara*: PageIndex `Citation` unchanged, Bookstore adds
  `book_id`/`title`/`chapter` in metadata and renders `[<title>, <chapter>, <label>]`.
- [x] Which hardenings — *Owner: Jesus Lara*: all four (graph preservation on same `toc_digest`,
  per-slug lock, sweep on open / `doctor`, card-vs-tree drift detection + repair).
- [x] Budget evaluation in this slice — *Owner: Jesus Lara*: yes, host run over seven of the nine indexed
  books with `google:gemini-3.5-flash-lite`; report fixes Bookstore defaults.
- [x] `SearchOriginKind` value — *Resolved in brainstorm*: add `BOOKSTORE = "bookstore"` (additive);
  reusing `PAGEINDEX` would hide which plane answered in `list_search_origins`.
- [x] `chapter` resolution — *Owner: Jesus Lara*: the owning node first (the node whose `owned`
  ranges contain the citation's `seq`), then the segment's `section` path, then the depth-1
  `TocEntry` covering the page, else omitted; `section_path` carries the full title path. Reason: the
  depth-1 TOC is useless as a chapter on this library (Analectas has one root node, Kant one node for
  pages 2–206, EPUB/MOBI have no pages).
- [x] Lock behaviour on re-index — *Owner: Jesus Lara*: fail fast. `reindex_lock_timeout_s`, default
  5 s, then a clear "re-index in progress" error; the identity check moves inside the lock.
- [x] Does `bookstore doctor` handle the relation graph — *Owner: Jesus Lara*: it reports books with
  no relation judgements; `--relate` runs `relate_books` on them; `--repair` stays deterministic and
  never calls an LLM. (Today the library has 0 relations, 0 judgements, 0 communities.)
- [x] CLI exposure — *Owner: Jesus Lara*: yes, `bookstore ask` in this slice, reusing the
  `--llm` resolution of `bookstore optimize`.
- [x] Evaluation question set — *Owner: Jesus Lara*: both — three hand-written questions with a gold
  node per book (drafted in the spec, reviewed by the owner) and five generated from sampled
  segments with a known gold `seq`, reported separately. Card `topics` are unusable as a source:
  every card is `fallback` or `manual`, so topics are TOC titles. Fixture holds questions and
  addresses only, no book text.
- [x] Which books, and when — *Owner: Jesus Lara*: seven books as indexed today, without waiting
  for `0a693a57b138` / `ab5235978ad7`: the five with a segment store, plus the two EPUBs re-indexed
  with `--force --no-llm` first. The two page-extraction duplicates are excluded because their
  source is gone. (A first answer chose all nine; it was re-asked once it turned out four of them
  have no segment store and cannot run agentic retrieval.) Consequence: the defaults are provisional
  and the report records tree shape per book for a later comparison.
- [x] Evaluation run size — *Resolved in brainstorm*: a full 3×3 grid over 56 questions would be
  504 serialised agentic runs. The plan is 56 runs at the current defaults plus a one-dimensional
  sweep of four settings over the 21 hand-written questions, 140 runs in all, with `--concurrency`
  through separate `Bookstore` instances. The spec may change the grid; the number of runs must stay
  in the report header.
- [ ] Follow-up, not this slice: re-run the evaluation after the ebook-heading and large-leaf fixes
  land and the books are re-indexed, and compare against this report. — *Owner: Jesus Lara*


### Owner-approved spec amendments (2026-11-09)

- [x] Use a separate Bookstore operation lock rather than holding the live PageIndex lock
  across rename_tree — *Owner: Jesus Lara*: "yes, accept" to the three proposed corrections.
- [x] Preserve graph only when source_sha256 AND toc_digest are unchanged and known —
  *Owner: Jesus Lara*: "yes, accept". This tightens the original same-TOC decision.
- [x] Add optional expected_revision on the Bookstore segment read interface —
  *Owner: Jesus Lara*: "yes, accept". Compare it against the returned read, not only preflight.
- [ ] Implementation-stage prerequisite: owner reviews the 21 draft handwritten questions
  and the host task binds real gold addresses before running evaluation. — *Owner: Jesus Lara*

No unresolved product/architecture blocker remains. The original rerun is deferred out of
scope; question/address review is part of the host evaluation task, not spec-time corpus work.

## 9. Design Research Cross-Check

Status: completed. Reviewer: independent native Codex read-only agent `/root/design_review`;
model inherited from the session (exact identifier not exposed). The owner accepted the input
and amendments in conversation even though the source document still says exploration.
The initial status-based skip was superseded by this review. No draft was supplied.
Transcript: `sdd/state/FEAT-858/design_research/` (brief, raw review, normalized suggestions,
run metadata and triage). Normalization was performed by the spec author; raw output is retained.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Await scope initialization explicitly (architecture) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 recovery; M4 |
| S2 | Coordinate recovery and imports with operation locks (risk) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 lock protocol; M4 |
| S3 | Check expected revision against returned read (api) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 guard; M1 |
| S4 | Decorate only against matching generation (risk) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 evidence; M1 |
| S5 | Handle empty filters and request-local notes (api) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 origin; M3 |
| S6 | Clip and validate against the stored revision (risk) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 origin; M3 |
| S7 | Pin gold fixtures and specify deterministic tuning (testing) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §4 host evaluation; M6 |

7 confirmed; 0 rejected; 0 escalated.


## 10. Documentation

- **Policy**: required.
- **Pages**:
  - `wiki/knowledge/bookstore-agentic-retrieval.md` — create: tools, origin configuration,
    revision guards, labels, real stop values, ask/doctor, lock/recovery limitations,
    live evaluation protocol and programmatically copied measured defaults/report SHA256.
  - `wiki/knowledge/bookstore-codex.md` — update: new research funnel, visible agentic tool,
    no-LLM configuration guidance, revision-aware reread example and ask CLI.
  - `wiki/knowledge/bookstore-graph.md` — update: equal source-hash-plus-TOC preservation,
    deterministic doctor repair, judgement counts and --relate behavior.
  - `wiki/knowledge/pageindex-agentic-retrieval.md` — update: link the Bookstore facade and
    evaluation; clarify PageIndex defaults and shared citation models remain unchanged.
- **API modules**: parrot.knowledge.bookstore.library, parrot.knowledge.bookstore.toolkit,
  parrot_tools.multistoresearch.origins.bookstore. Google-style public docstrings must cover
  budgets, degradation, revision mismatch and cancellation behavior.
- Documentation is an informational SDD closeout requirement; insufficient evaluation evidence
  must be stated explicitly, never replaced by made-up default numbers.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara (spec prepared with Codex) | Option A formalized; three owner amendments; seven independent research corrections |
