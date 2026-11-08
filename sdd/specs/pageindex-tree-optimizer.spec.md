---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — carried from sdd/proposals/pageindex-tree-optimizer.brainstorm.md; this slice touches only core files (the ai-parrot-tools origin is unchanged, see §1 Non-Goals)
tags: [pageindex, tree-optimizer, bookstore, prompt-injection, mcp]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-tree-optimizer.md]
  api_modules: [parrot.knowledge.pageindex.optimizer, parrot.knowledge.pageindex.optimizer_llm, parrot.knowledge.pageindex.optimizer_eval]
---

# Feature Specification: PageIndex Tree Optimizer

**Feature ID**: FEAT-846
**Date**: 2026-11-08
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> Sixth and last slice of the umbrella brainstorm
> `sdd/proposals/pageindex-tree-optimizer.brainstorm.md` (rev 4). The other five are on
> `dev`: `pageindex-generation-publication` (FEAT-831), `pageindex-segment-store` (FEAT-840),
> `pageindex-local-mcp-toolkit` (FEAT-842), `pageindex-agentic-retrieval` (FEAT-843) and
> `pageindex-layout-structure` (FEAT-845). Code references were verified at `dev` @ `09d3377826`.

---

## 1. Motivation & Business Requirements

### Problem Statement

From the brainstorm, the two gaps this slice closes:

> **The tree shape is never optimized.** A leaf is split only when it exceeds 10 pages *and*
> 20,000 tokens (`ConfigLoader._DEFAULTS`), so large leaves are common. BM25 sees only the
> first 4,000 characters of a node body (`_BM25_TEXT_LIMIT`), so most of a large leaf is
> invisible to lexical ranking. Siblings that share one page get the same page text and
> therefore near-identical summaries. Every node is summarized with its own LLM call over raw
> page text.

Slices 2–5 changed the substrate but not the shape: a node now owns exact segment ranges
(`owned`), its body is a rendered view of them, PDF structure comes from bookmarks and
printed headings, and agents can read pages and paragraphs with citable addresses. What is
still missing is everything that makes a tree *good to navigate*: leaves sized for ranking
and for a bounded reading loop, siblings that do not duplicate each other, concepts that
prose hides inside a long leaf, summaries that are short, built from the node's own text and
composed bottom-up, and a way to bring an existing tree (Bookstore books, repository trees
served over MCP) to that state without re-importing it.

Today, on `dev`:

- No optimizer of any kind exists, and the PDF path never merges or splits anything after
  the structure is chosen. Since `f426e44f8d`, `md_to_tree` keeps short sections and the text
  before the first heading (it no longer calls `thin_tree`), so markdown revisions now carry
  tiny sections that only a merge rule can tidy.
- Summaries are one LLM call per node over raw page text (`builder.py:1522-1550`) or per
  markdown section (`md_builder.py:226-248`), unframed, with no word limit, and parents are
  summarized independently of their children.
- `key_items` is read by `outline` (`toolkit.py:941`) but nothing writes it, and neither
  BM25 nor the embedding text would see it.
- A node body edited by hand on a segment-backed node is no longer the view over its owned
  ranges; FEAT-840 left "what happens to such a node when the tree is optimized" to this
  slice (its §8).

### Goals

Carried from the brainstorm's *Constraints & Requirements* and resolved questions:

- **G1 — Expansion first.** Better per-node ranking and cheaper agentic navigation through
  *more* nodes, not fewer: finer leaves, more concepts covered, shorter summaries. Merging is
  the exception (duplicate spans, empty leaves, tiny contiguous siblings).
- **G2 — Nodes only for printed headings.** A split happens only at a heading segment or a
  heading-like printed line inside the leaf. Concepts found in prose become `key_items`
  anchored to a paragraph, tagged `literal` or `abstractive`. No synthetic nodes.
- **G3 — Token cost model.** The expansion trigger is a token target over owned segments,
  not a page count, so paged and unpaged sources are treated alike; expand when one routing
  step plus the largest child costs less than scanning the node; the minimum leaf is the floor.
- **G4 — Ownership is preserved.** Every pass keeps the owned ranges of each document a
  partition of its segments; the candidate is rejected before publication otherwise.
- **G5 — Runs at import and on demand, never implicitly after an edit.** Every import path
  that produces a revision optimizes the new subtree before publishing; an explicit
  `optimize` (toolkit tool, `parrot pageindex optimize`, `bookstore optimize`) works on
  existing trees, defaults to a dry run with a report, and publishes a generation when applied.
- **G6 — Idempotent.** Per-pass completion records on each node (consumed-input hash,
  settings hash, execution context and optimizer version) make a second run with the same
  inputs and execution context change nothing even though LLM passes are not deterministic.
- **G7 — Scope.** Only subtrees that came from an import (`doc_id`) and are not `locked`;
  subtree optimization preserves ownership outside its selected scope.
- **G8 — Bottom-up summaries.** Leaves from their own segments; a short leaf uses its text
  with no LLM call; parents composed from child summaries, their own segments and
  `key_items`; deepest first under the existing concurrency gate; a lower word limit.
- **G9 — `key_items` are indexed.** They join the BM25 text, the embedded text (and its cache
  key) and the tree the LLM walk sees.
- **G10 — OKF identity.** A node removed by a merge keeps resolving: its `concept_id` becomes
  an alias of the node that absorbed it; its title survives as a literal `key_item`. An
  exported OKF bundle rewrites links to it to the absorbing node.
- **G11 — Hardening.** Every piece of document text that enters an optimizer or summary
  prompt is framed with the FEAT-840 helpers; model output that names segments or headings
  is validated against the segments it was shown.
- **G12 — Bookstore.** New books are optimized at import; existing books opt in per book
  (`bookstore optimize <book_id>`); the card's TOC is rebuilt afterwards.
- **G13 — Provisional, configurable sizes** with an evaluation harness that reports what the
  defaults do on a corpus, and one deterministic tuning run inside this feature that may
  adjust `target_leaf_tokens` by a fixed rule (M6).

### Non-Goals (explicitly out of scope)

- Changing how structure is *found* (bookmarks, layout, LLM fallback): FEAT-845 owns it.
- Any change to the read tools, the ledger, citations or the agentic loop (FEAT-840/843).
  `outline` already passes `key_items` through.
- Traffic-driven expansion (brainstorm Option C) — rejected; retrieval never writes to a tree.
- Re-partitioning a tree after `add_node`/`delete_node`. Edits do not trigger the optimizer
  (G5); the next explicit `optimize` repairs ownership gaps those edits left (§2).
- Replacing the builder's legacy summary functions (`generate_node_summary`,
  `generate_prefix_summaries`); they stay for callers that bypass the toolkit. `thin_tree`
  stays as a function for explicit callers; `md_to_tree` already stopped calling it (§8).
- An `aliases` field in OKF sidecar frontmatter or in the OKF bundle (`parrot.knowledge.okf`
  is shared with the ontology work). Aliases resolve through `OKFToolkit`, and the PageIndex
  bundle exporter rewrites links and `relates_to` targets that name an alias to the
  absorbing concept (G10, §8).
- Citations in `parrot_tools/multistoresearch` and Bookstore `agentic_retrieve` (FEAT-843 §8).
- Tuning the LLM-dependent defaults (`summary_max_words`, `max_key_items`,
  `routing_tokens_per_child`) and the deterministic floors (`min_leaf_tokens`,
  `inline_summary_tokens`). The M6 tuning run is deterministic and may adjust only
  `target_leaf_tokens` (G13, §8); an LLM-mode run is a ledger follow-up.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:8ed1ff34933e033998fdf974d55bce38057547d8191c18075b2e4dcdd2075846 evaluation_digest=sha256:f6c7286f746e864f936b00a3867806b7d1890728df856287f0a9ad821c067704 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

The optimizer is a **planner over segments**. It never touches a `DocumentRevision` (a
revision is immutable; only a re-import creates one), so every citation and read cursor
stays valid across optimization. It reads the revision of each document in scope, rewrites
the *shape* of the imported subtree — which nodes exist, which segment ranges each owns,
their titles, summaries, `key_items` and stamps — validates that the owned ranges still
partition every affected document exactly once, and publishes the result as one generation
through the FEAT-831 `WriteTransaction` (bodies re-rendered with `render_body` and staged by
`concept_id`-keyed `body_ref`). Dry runs never open a transaction.

Two layers, kept in two modules so the first is testable without any model:

1. **Deterministic passes** (`optimizer.py`, pure functions over tree dicts + revisions):
   - *scope* — the roots to consider: nodes carrying `doc_id` whose revision file exists,
     minus every node flagged `locked` and its descendants (G7). With `node_id` given, only
     that subtree; nodes outside it keep their owned ranges byte-identical.
   - *repair* — gaps in a document's partition (left by `delete_node`, or by an `add_node`
     under an imported parent, which owns nothing) are re-owned by the deepest in-scope
     ancestor whose `span` covers them and counted as `repaired_gaps`; overlaps are an
     error and abort planning for that document (the brainstorm prefers keeping a small leaf
     to dropping or duplicating text; an overlap cannot be repaired without choosing a loser).
   - *normalize* — siblings with the identical `span` collapse into the first one; leaves
     with no owned segments are removed; sibling leaves under `min_leaf_tokens` merge into a
     contiguous sibling (the previous one, else the next) when the merged owned ranges stay
     contiguous and neither node is `locked`. A merged leaf's title is kept on the absorber as
     a `literal` `key_item` anchored to its heading segment (or first owned segment), and its
     `concept_id` is appended to the absorber's `aliases` (G10).
   - *assign ownership* — after every structural change, parent spans widen to cover their
     descendants and parents own only what no child owns, computed with the FEAT-840
     `_subtract` rule; an intro leaf is allowed only for a printed heading, otherwise leading,
     interstitial and trailing text stays with the parent.
   - *expand at headings* — a leaf over `target_leaf_tokens` is split at the heading segments
     inside its owned ranges (the shallowest heading level present first, recursively), then
     at heading-like lines the LLM pass proposes (see 2 below). Each piece is a new child
     owning the range from its heading to the next split; the text before the first heading
     stays with the parent (no synthetic "introduction" node).
   - *decide* — a split is taken only when `routing_cost(pieces) + max(piece_tokens)` is
     smaller than the leaf's own tokens and every piece is at least `min_leaf_tokens`;
     `routing_cost` is the token count of the pieces' titles and summaries when present, else
     `routing_tokens_per_child` per piece (G3).
   - *prepare pass inputs* — deterministic planning never writes completion stamps.
     Preserve the input tree's stamps for per-pass comparison; structural changes invalidate
     dependent passes. Only a matching, previously completed pass may be skipped. After
     requested passes and candidate validation succeed, finalize their completion records
     using the pass inputs actually consumed (see the stamp lifecycle below). Deterministic
     passes are idempotent by construction; an unchanged second run reports zero actions (G6).
   - *validate* — per affected document, `validate_ownership(all nodes of that doc,
     revision)` must return no problems; every `key_item.seq` must fall inside an owned range
     of its node; `locked` nodes and out-of-scope nodes must be unchanged except for
     `node_id`; otherwise the plan is rejected and nothing is published (G4).

2. **LLM passes** (`optimizer_llm.py`, each prompt framed with `frame_segments` and
   `DATA_FRAMING_INSTRUCTION` as the system prompt; G11), run only with a *live* adapter —
   `adapter.client is not None` — because Bookstore hands the toolkit a `_NullAdapter`
   (`client = None`, `ask()` → `""`) when no LLM is configured (`library.py:150-176, 238`):
   - *heading proposals* — for a leaf still over target that holds no heading segment in its
     owned ranges, the model is shown the framed segments and asked for the `seq` of the
     segments that are printed sub-headings. A proposal is accepted only when the segment is
     inside the leaf's owned ranges, is a single line of at most `MAX_HEADING_WORDS` words,
     does not end with a period and is not a `table`/`code`/`caption`; the accepted segment
     then acts as the heading of its piece (G2: the line is printed in the document; the
     node is not synthetic). Rejected proposals are counted, never applied.
   - *concept key_items* — for a leaf still over target after expansion (or one that cannot
     be split), up to `max_key_items` labels, each with the `seq` of the paragraph that
     anchors it and a kind. A `literal` label must occur, case-folded and whitespace-collapsed,
     in its anchor text; an `abstractive` one needs only a valid anchor. Anchors outside the
     node's owned ranges drop the item.
   - *bottom-up summaries* — deepest first with `_limited_gather` (the optimizer sets the
     `_LLM_SEMAPHORE` ContextVar when it is unset, exactly like `build_page_index`): a leaf
     whose owned tokens are at most `inline_summary_tokens` takes its own text as summary
     with no call (`summary: "inline"`); a larger leaf gets one framed call capped at
     `summary_max_words` (`"llm"`); a parent is composed in one call from its children's
     summaries, its own owned segments and its `key_items` (`"composed"`), or
     deterministically (`"<own text>. Subsections cover: <child titles>"`) when there is no
     live adapter; a matching completed summary pass keeps its summary and stamp byte-for-byte.
     `"kept"` is a reporting outcome, never a replacement for persisted summary provenance.

**Stamp lifecycle and retry cache (normative).** Completion is per pass (`headings`,
`key_items`, `summary`), not a blanket node flag. Each record contains the optimizer version,
settings digest, pass-input digest, execution-context digest and completion time. A pass
record is created only after that pass succeeds and the candidate validates; failed or
unrequested passes get no new completion record. In particular, `with_summaries=False`
does not mark summaries complete, and unavailable/disabled model passes remain pending.
Successful empty heading/key-item proposals count as completed work. No-model summaries
can complete in deterministic mode; a later live-model request invalidates that mode.

The structural digest covers `(doc_id, revision, owned, title, [(child.title, child.span)])`.
Each pass also hashes all data it actually consumes: key-item extraction uses the post-split
ownership; summary input includes own key items and the ordered child titles, summaries,
key items and spans. Evaluate summary digests deepest-first after children finish. The
execution digest identifies deterministic versus live mode, pass/prompt version and, for
live calls, provider/client type and effective model (never credentials). Switching from
no model to a live model, or changing a child summary, therefore schedules the affected work.
Short inline summaries remain deterministic even with a live adapter.
Effective live mode requires both `settings.llm_passes` and a live adapter; disabling model
passes selects deterministic summary fallback without marking heading/key-item work complete.
`skipped_stamped` counts a node only when all its requested, eligible passes have matching
completion records; deferred/unavailable work is not reported as completed stamp reuse.

Use the same complete `(pass, version, settings, input, execution)` key for the in-memory
retry cache. Cache only accepted successful outputs; revalidate proposal anchors against
the retry candidate. Recompute scope, ownership and pass keys on every retry; never reuse
candidate object identities across retries. Records for passes invalidated by a later
structural change in the same run are discarded, not restamped against unconsumed inputs;
evaluate those passes on the final shape before claiming completion. Preserve matching
records and their timestamps unchanged. An identical final tree and body references mark
the standalone transaction `noop`; stamp checks alone never publish a generation.

**Import.** `import_pdf`, `insert_markdown` and `insert_ebook` call the optimizer on the
new subtree inside their existing transaction, right after `_stage_document`, when
`optimize_on_import` (default `True`). The builder's own summary passes are switched off on
that path (`if_add_node_summary: "no"`) so a PDF import makes far fewer calls: structure from
layout, summaries bottom-up with inline short leaves. The document description, which the
builder only produced inside its summary block, is generated by the toolkit afterwards with
the optimizer-owned `describe_document` helper: serialize
`create_clean_structure_for_description` output as quoted data with `frame_text`, then call
the live adapter with `DATA_FRAMING_INSTRUCTION`. Instructions stay outside the frame;
document-derived titles and summaries stay inside it. Do not call the legacy, unframed
`builder.generate_doc_description` on this optimized path. The legacy helper stays unchanged
for `optimize_on_import=False` and callers that bypass the toolkit.
`insert_content`/`import_file` reach the same hook through `insert_markdown`. With
`optimize_on_import=False` every import behaves exactly as on `dev` today.

**Explicit optimize.** `PageIndexToolkit.optimize(tree_name, node_id=None, apply=False,
llm_passes=True, …)` plans on a deep copy of the loaded tree and returns an `OptimizeReport`
(nodes before/after, leaves over target before/after, merges, expansions, `key_items` added,
summaries written, repaired gaps, skipped locked/stamped nodes, LLM calls made, documents,
errors). With `apply=True` it runs through `_mutate`: the apply closure re-plans on
`txn.tree` (so a stale snapshot is simply re-planned and the LLM results of the first pass
are reused through the complete per-pass cache key above), replaces the scoped subtree,
calls `reindex_node_ids`, assigns `concept_id` to new nodes with sibling-scoped dedup
(`derive_concept_id` + `dedup_concept_ids`; `ensure_concept_ids` alone would let two equal
headings under one parent collide), and stages bodies only for mutable nodes in the selected
scope whose rendered body or identity changed (`render_body` → `txn.set_body`, empty →
`drop_body`). Effective locks include locked ancestors, even above the selected subtree;
locked nodes, their descendants and out-of-scope nodes retain their original bodies and
`body_ref` byte-for-byte. Removing a node is allowed only within that mutable scope.
Validate ownership across each complete affected document and protected-node equality
again after staging and stamp finalization, immediately before publication. Validation errors
abort the transaction without publishing; identical candidates use `txn.noop`. The existing
`set_body`/`drop_body` helpers enforce no optimizer lock policy, so the toolkit must enforce
these guards explicitly. The outermost `_write` publishes only a changed valid candidate.
The tool is **not** LLM-dependent: without a model the dry run,
the deterministic passes and the deterministic summaries work; the report says
`llm_passes: "skipped (no model)"`.

**Locked nodes.** `locked: true` on a node excludes it and its descendants from every pass;
its owned ranges are treated as fixed when its ancestors are re-partitioned. It is set
explicitly through `update_node(locked=…)` and **automatically by `update_node_content` on a
segment-backed node** (`doc_id` present), with `locked_reason: "body_edited"` — this resolves
FEAT-840's open question: a hand-edited body is never overwritten by a re-render, at the
price of that node no longer being a view (its addresses stay valid; §7 lists the trade-off).

**Bookstore.** `add_book` needs no change: the toolkit optimizes at import, and `derive_toc`
already runs after the import. `Bookstore.optimize_book(book_id, apply, llm_passes)` wraps
`toolkit.optimize` and, when applied, rewrites the card's `toc`, `toc_digest`,
`chapter_count` and `page_count` (the same fields `refresh_card` recomputes). `bookstore
optimize BOOK_ID [--apply] [--no-llm]` exposes it. `parrot pageindex optimize TREE
--storage-dir DIR [--node ID] [--apply] [--llm SPEC]` does the same for any storage
directory (the repository trees the MCP template serves).

**Resolved brainstorm decisions reflected here** (also listed in §8): expansion-biased goal;
printed headings only + anchored `key_items`; import + explicit command, never after an
edit; `doc_id` scope + `locked`; alias record for merged `concept_id`; per-node stamp; merge
triggers and min-leaf floor; parent residual text rendered in document order with gap
markers (unchanged from FEAT-840 `render_body`); `literal`/`abstractive` tagging; Bookstore
opt-in per book, new books at import; legacy trees via `index_segments` revisions
(section addresses — the deterministic passes and `key_items` work; expansion has no page
headings to find unless the stored bodies carried markdown headings); provisional sizes +
evaluation task.

### Component Diagram
```
                     import_pdf / insert_markdown / insert_ebook           optimize(apply=True)
                     ──────────────┬───────────────────────────            ─────────┬─────────
                                   │ _stage_document(txn, revision, roots)          │ _mutate
                                   ▼                                                ▼
                        PageIndexToolkit._optimize_import ──────┐      PageIndexToolkit.optimize
                                                                 │               │
                                                                 ▼               ▼
   DocumentRevision ──▶ optimizer.plan_deterministic ──▶ OptimizePlan ──▶ optimizer_llm.run_llm_passes
   (SegmentStore)        scope · repair · normalize ·     candidate +      headings · key_items ·
                         ownership · expand · decide ·    report           bottom-up summaries
                         pass inputs                        │              (framed prompts; deterministic fallback)
                                                            ▼
                                             optimizer.validate_candidate ──▶ errors ⇒ reject (no publish)
                                                            │ ok
                                                            ▼
                               reindex_node_ids · concept ids (dedup) · scoped body staging
                                                            │
                                      finalize successful pass stamps · validate final candidate
                                                            │
                                                            ▼
                                        WriteTransaction.publish  (FEAT-831: lock, stale check, generation)

   key_items ──▶ HybridPageIndexSearch._flatten_corpus (BM25)  ·  NodeEmbeddingStore text + key  ·  outline (already)
   aliases   ──▶ OKFToolkit._by_concept_id  (get_concept / cite resolve a merged concept_id)
             ──▶ export_okf_bundle  (links and relates_to naming an alias → the absorber)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `WriteTransaction` (`generation.py:116`) | uses | optimize publishes through it; bodies staged with `set_body`/`drop_body`; never a new revision |
| `PageIndexToolkit._mutate` / `_write` (`toolkit.py:322, 267`) | uses | apply path; stale snapshots are re-planned inside the retry |
| `_stage_document` call sites (`toolkit.py:1706, 1763, 1906`) | extends | `_optimize_import` right after each |
| `segments.render_body` / `validate_ownership` / `_subtract` (`segments.py:475, 490, 323`) | uses | body views, the partition check, parent residual computation |
| `SegmentStore.load_revision` (`segment_store.py:64`) | uses | revisions of the documents in scope |
| `framing.frame_segments` / `DATA_FRAMING_INSTRUCTION` (`framing.py:33, 10`) | uses | every optimizer and summary prompt |
| `builder._limited_gather` / `_LLM_SEMAPHORE` (`builder.py:80, 75`) | uses | summary fan-out under the shared gate |
| `optimizer_llm.describe_document` (new) + `utils.create_clean_structure_for_description` | uses | framed document description after bottom-up summaries; legacy builder helper is not called |
| `layout_structure.heading_title` / `MAX_HEADING_WORDS` (`layout_structure.py:61, 23`) | uses | heading-like acceptance rule |
| `tree_ops.reindex_node_ids` (`tree_ops.py:22`) | uses | after structural changes |
| `okf.concept_id.derive_concept_id` / `dedup_concept_ids` (`concept_id.py:72, 103`) | uses | ids for new nodes |
| `HybridPageIndexSearch._flatten_corpus` / result dict (`hybrid_search.py:165, 420-426`) | modifies | `key_items` labels in the BM25 text and in search results |
| `NodeEmbeddingStore.content_key` / `build_tree_matrix` (`embedding_store.py:96, 243`) | modifies | labels in the embedded text; key changes only when labels exist |
| `OKFToolkit.__init__` (`okf/tools.py:66-85`) | modifies | aliases map to the absorbing node |
| `export_okf_bundle` / `_export_frontmatter` (`okf/bundle.py:252, 185`) | modifies | on export, an alias maps to the absorber's file and `concept_id`; no new frontmatter key |
| `PageIndexNode` (`schemas.py:118`) | extends | `key_items`, `locked`, `locked_reason`, `aliases`, `optimizer` |
| `Bookstore` / `bookstore` CLI (`library.py:179`, `cli.py:98`) | extends | `optimize_book`, `bookstore optimize` |
| `parrot` CLI registry (`cli/__init__.py:170-`) | extends | `"pageindex": "parrot.knowledge.pageindex.cli"` |
| `mcp/_toolkit_templates/pageindex.yaml` | comment only | `pageindex_optimize` named among the tools that work without `llm:` |

### Data Models
```python
# knowledge/pageindex/optimizer.py (new)
OPTIMIZER_VERSION = "v1"

class OptimizerSettings(BaseModel):
    """Provisional defaults (brainstorm: tuned later by the evaluation task)."""
    target_leaf_tokens: int = 1500      # a leaf above this is a candidate for expansion / key_items
    min_leaf_tokens: int = 200          # merge floor and expansion floor
    inline_summary_tokens: int = 120    # leaf at or below this: summary = its own text, no LLM call
    summary_max_words: int = 60
    max_key_items: int = 8
    routing_tokens_per_child: int = 48  # cost-model estimate when a piece has no summary yet
    max_depth: int = 8                  # never expand below this depth
    llm_passes: bool = True             # heading proposals, key_items, LLM summaries (live adapter only)

    def settings_hash(self) -> str: ...  # sha256 of the sorted dump, 16 hex chars

class KeyItem(BaseModel):
    label: str
    kind: Literal["literal", "abstractive"]
    seq: int                            # segment index in the node's revision
    page: Optional[int] = None
    ordinal: int = 0

class PassStamp(BaseModel):
    version: str                        # OPTIMIZER_VERSION
    input: str                          # sha256[:16] of all inputs consumed by this pass
    settings: str                       # OptimizerSettings.settings_hash()
    execution: str                      # digest of mode, prompt version, provider/client type and effective model
    at: str                             # UTC ISO-8601

class OptimizerStamp(BaseModel):
    passes: dict[Literal["headings", "key_items", "summary"], PassStamp]
    summary: Literal["inline", "llm", "composed", "none"] = "none"  # provenance, never rewritten to "kept"

class MergeAction(BaseModel):
    absorbed_concept_id: Optional[str]; absorbed_title: str; into_concept_id: Optional[str]; into_title: str
    reason: Literal["duplicate_span", "empty", "under_minimum"]

class ExpandAction(BaseModel):
    parent_title: str; parent_concept_id: Optional[str]; pieces: list[str]; source: Literal["layout", "llm"]

class OptimizeReport(BaseModel):
    tree_name: str; node_id: Optional[str]; dry_run: bool
    generation_before: Optional[int]; generation_after: Optional[int]
    documents: list[str]                 # doc_ids in scope
    nodes_before: int; nodes_after: int
    leaves_over_target_before: int; leaves_over_target_after: int
    merged: list[MergeAction]; expanded: list[ExpandAction]
    key_items_added: int; summaries_written: int; repaired_gaps: int
    skipped_locked: int; skipped_stamped: int; rejected_proposals: int
    llm_passes: str                      # "ran" | "skipped (no model)" | "skipped (disabled)"
    llm_calls_estimated: int; llm_calls_made: int
    errors: list[str]                    # non-empty ⇒ nothing was published
    settings: OptimizerSettings

# Node fields (all optional; old trees take the fallback paths):
#   key_items: list[KeyItem-as-dict]   locked: bool   locked_reason: str   aliases: list[str]
#   optimizer: OptimizerStamp-as-dict
```

### New Public Interfaces
```python
from parrot.knowledge.pageindex import OptimizerSettings, OptimizeReport      # new exports

await toolkit.optimize("docs")                                 # dry run → report dict
await toolkit.optimize("docs", node_id="0007", apply=True)     # publishes a generation
await toolkit.update_node("docs", "0007", locked=True)
await bookstore.optimize_book("clean-code", apply=True)
# CLI
#   parrot pageindex optimize TREE --storage-dir .parrot/pageindex [--node ID] [--apply] [--llm provider:model] [--json]
#   bookstore optimize BOOK_ID [--global] [--apply] [--no-llm] [--llm SPEC] [--json]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: deterministic planner | no | models and function names fixed below | the merge/ownership/expansion interplay on real trees needs judgement; validation must be exact |
| M2: LLM passes | no | prompts framed; acceptance rules fixed | prompt wording and the heading-like rule need iteration against real PDFs |
| M3: schema + indexing + OKF aliases | yes | field names, `content_key(extra=)` rule, alias map (toolkit lookup and bundle export) | — |
| M4: toolkit integration | no | hook sites fixed in §6 | transaction/retry semantics and the import-path change to builder options |
| M5: Bookstore + CLIs | yes | method/command names and options fixed below | — |
| M6: evaluation harness | harness: yes; tuning run: no | mirrors `layout_eval.py` shape; `tuned_target` rule fixed below | the tuning run must be executed by the orchestrator or on the host, with every number copied from the written report — in FEAT-845 (TASK-5344) a coder seat invented a metrics table for this corpus |
| M7: documentation + integration tests | yes | pages and test names fixed in §4/§10 | — |

### Module 1: Deterministic planner
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` (new)
- **Responsibility**: settings, report models, scope, repair, normalize, ownership,
  heading expansion, cost model, stamps, candidate validation. Pure functions over tree
  dicts and `DocumentRevision`; no I/O, no LLM.
- **Depends on**: `segments.py` (FEAT-840), `layout_structure.heading_title`, `utils`.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/optimizer.py (new)
  from parrot.knowledge.pageindex.segments import (            # verified: segments.py:33,59,323,340,490
      DocumentRevision, Segment, _heading_text, _subtract, validate_ownership, normalize_title, _titles_match)
  from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title  # verified: layout_structure.py:23,61
  from parrot.knowledge.pageindex.utils import structure_to_list, find_node_by_id          # verified: utils.py:294,353

  OPTIMIZER_VERSION = "v1"
  Revisions = dict[tuple[str, str], DocumentRevision]           # (doc_id, revision) → revision

  class OptimizerSettings(BaseModel): ...                        # §2 Data Models
  class KeyItem(BaseModel): ...
  class PassStamp(BaseModel): ...
  class OptimizerStamp(BaseModel): ...
  class MergeAction(BaseModel): ...
  class ExpandAction(BaseModel): ...
  class OptimizeReport(BaseModel): ...

  class OptimizePlan:
      """A candidate tree (deep copy of the input) plus the report and the per-node LLM cache."""
      candidate: dict[str, Any]
      report: OptimizeReport
      mutable: set[int]                                          # id(node) in this candidate, in scope and effectively unlocked
      touched: set[int]                                          # subset of mutable needing body staging; recomputed on retry
      pending_stamps: dict[int, dict[str, PassStamp]]             # successful pass records; finalize only after validation
      llm_cache: dict[str, Any]                                  # full per-pass cache key → accepted successful output

  def owned_tokens(node: dict, revision: DocumentRevision) -> int:
      """Sum of ``segments[seq].tokens`` over the node's owned ranges."""

  def is_locked(node: dict) -> bool:
      """``node.get("locked") is True``."""

  def optimizable_roots(tree: dict, revisions: Revisions, *, node_id: Optional[str] = None) -> list[dict]:
      """Imported subtree roots in scope: carry ``doc_id``/``revision`` present in ``revisions`` and are not locked;
      with ``node_id`` only that subtree (KeyError when absent). Check ancestors above the selection for effective
      locks. Locked descendants are excluded by all passes, body staging and stamp finalization."""

  def repair_ownership(doc_nodes: list[dict], revision: DocumentRevision, report: OptimizeReport) -> list[str]:
      """Re-own every unowned ``[a, b)`` to the deepest in-scope ancestor whose span covers it; count ``repaired_gaps``.
      Returns the overlap problems (non-empty ⇒ the document is skipped and the problem recorded in ``report.errors``)."""

  def normalize(parent_children: list[dict], revision: DocumentRevision, settings: OptimizerSettings,
                report: OptimizeReport) -> None:
      """Collapse identical spans, drop empty leaves, merge contiguous under-minimum leaves (title → literal key_item,
      concept_id → absorber ``aliases``). Never touches a locked node. Recurses into children."""

  def assign_ownership(node: dict) -> None:
      """Widen ``span`` to cover descendants; ``owned = _subtract(span, child spans)``; recursive, bottom-up."""

  def heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]:
      """Heading segments inside the owned ranges, excluding the node's own title heading when it is the first one."""

  def routing_cost(pieces: list[dict], revision: DocumentRevision, settings: OptimizerSettings) -> int:
      """Tokens of the pieces' titles + summaries when present, else ``routing_tokens_per_child`` each."""

  def should_expand(node_tokens: int, piece_tokens: list[int], cost: int, settings: OptimizerSettings) -> bool:
      """``cost + max(piece_tokens) < node_tokens`` and every piece ≥ ``min_leaf_tokens``."""

  def split_at(node: dict, revision: DocumentRevision, seqs: list[int], *, source: str,
               settings: OptimizerSettings, report: OptimizeReport) -> list[dict]:
      """Create one child per split seq owning ``[seq, next_seq)`` within the node's owned ranges; the text before the
      first seq stays with the node; titles from ``heading_title(segment.text)``; records an ``ExpandAction``.
      Returns the new children (empty when ``should_expand`` said no)."""

  def expand_at_headings(node: dict, revision: DocumentRevision, settings: OptimizerSettings,
                         report: OptimizeReport, *, depth: int) -> None:
      """Recursive layout expansion: shallowest heading level first, down to ``max_depth``."""

  def stamp_input(node: dict) -> str:
      """sha256[:16] of json (doc_id, revision, owned, title, [(child.title, child.span)])."""

  def pass_input(node: dict, pass_name: str) -> str:
      """Hash structural input plus every consumed dependency; summary includes own key_items and ordered
      child titles, summaries, key_items and spans. Called after prerequisite passes finish."""

  def pass_cache_key(pass_name: str, input_hash: str, execution: str, settings: OptimizerSettings) -> str:
      """Hash pass name, OPTIMIZER_VERSION, settings hash, input hash and execution digest."""

  def is_stamped(node: dict, settings: OptimizerSettings, *, pass_name: str,
                 input_hash: str, execution: str) -> bool:
      """Matching completed record for this pass only; missing or legacy blanket stamps are cache misses."""

  def finalize_stamps(plan: OptimizePlan) -> None:
      """After successful candidate validation, persist successful pending pass records for mutable nodes only.
      Discard records invalidated by later structural changes; preserve matching records and timestamps."""

  def plan_deterministic(tree: dict, revisions: Revisions, settings: OptimizerSettings, *,
                         tree_name: str, node_id: Optional[str] = None) -> OptimizePlan:
      """Deep-copy ``tree``; run scope → repair → normalize → ownership → expand; fill counters and mutable/touched
      sets. Preserve prior stamps for per-pass checks; never write completion records in this phase."""

  def validate_candidate(plan: OptimizePlan, revisions: Revisions, *, base_tree: dict) -> list[str]:
      """Per document: ``validate_ownership`` over every node of that doc; key_item anchors inside owned ranges;
      effectively locked and out-of-scope nodes unchanged except ``node_id``, including bodies/body_ref.
      Run before stamp finalization and again after staging/finalization; non-empty ⇒ abort without publish."""

  def leaves_over_target(nodes: list[dict], revisions: Revisions, settings: OptimizerSettings) -> int: ...
  ```

### Module 2: LLM passes
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` (new)
- **Responsibility**: heading proposals, `key_items`, bottom-up summaries and document descriptions; framed prompts;
  acceptance rules; the live-adapter gate.
- **Depends on**: M1, `framing.py`, `builder._limited_gather`, `PageIndexLLMAdapter.ask_structured`.
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/optimizer_llm.py (new)
  from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text  # verified: framing.py:10,33,39
  from parrot.knowledge.pageindex.builder import _LLM_SEMAPHORE, _limited_gather             # verified: builder.py:75,80
  from parrot.knowledge.pageindex.segments import SegmentAddress, SegmentRead                # verified: segments.py:71,97
  from parrot.knowledge.pageindex.optimizer import (KeyItem, OptimizePlan, OptimizerSettings, Revisions,
                                                    is_stamped, pass_input, pass_cache_key, owned_tokens, split_at)
  from parrot.knowledge.pageindex.utils import create_clean_structure_for_description

  class HeadingProposals(BaseModel):
      """Structured output: ``seqs`` of segments the model takes for printed sub-headings."""
      seqs: list[int]

  class KeyItemProposal(BaseModel):
      label: str; kind: Literal["literal", "abstractive"]; seq: int

  class KeyItemProposals(BaseModel):
      items: list[KeyItemProposal]

  class SummaryOut(BaseModel):
      summary: str

  def adapter_is_live(adapter: Any) -> bool:
      """True only for an adapter with a client (Bookstore's ``_NullAdapter`` has ``client = None``)."""  # verified: library.py:167

  def execution_digest(adapter: Optional[Any], *, mode: str, prompt_version: str) -> str:
      """Digest deterministic/live mode and prompt version; live includes provider/client type and effective model,
      never credentials or object identity. Inline summary mode remains deterministic with a live adapter."""

  def reads_for(node: dict, revision: DocumentRevision) -> list[SegmentRead]:
      """One full ``SegmentRead`` per owned segment, so ``frame_segments`` labels each with its address."""

  def heading_like(segment: Segment) -> bool:
      """Single line, ≤ MAX_HEADING_WORDS words, no terminal period, kind not in {table, code, caption}.
      No median-paragraph length check (rejected in §8); the split still has to pass ``should_expand``."""

  def literal_in_anchor(label: str, text: str) -> bool:
      """Casefolded, whitespace-collapsed substring test."""

  async def propose_headings(node: dict, revision: DocumentRevision, adapter: Any,
                             settings: OptimizerSettings) -> list[int]:
      """Framed prompt → ``HeadingProposals``; keep seqs inside owned ranges that pass ``heading_like``."""

  async def propose_key_items(node: dict, revision: DocumentRevision, adapter: Any,
                              settings: OptimizerSettings) -> list[KeyItem]:
      """Framed prompt → ``KeyItemProposals``; validate anchors and literal labels; cap at ``max_key_items``."""

  async def summarize_leaf(node: dict, revision: DocumentRevision, adapter: Optional[Any],
                           settings: OptimizerSettings) -> tuple[str, str]:
      """``(summary, kind)``: ``inline`` when owned tokens ≤ inline_summary_tokens, else ``llm`` (framed, word cap)."""

  async def compose_parent(node: dict, revision: DocumentRevision, adapter: Optional[Any],
                           settings: OptimizerSettings) -> tuple[str, str]:
      """``composed`` from child summaries + own segments + key_items; deterministic fallback without a live adapter."""

  async def describe_document(structure: Any, adapter: Any) -> str:
      """With a live adapter only: serialize create_clean_structure_for_description(structure), wrap the entire
      payload with frame_text(source=\"document structure\"), and call ask with DATA_FRAMING_INSTRUCTION.
      Keep all instructions outside the frame; do not call builder.generate_doc_description."""

  async def run_llm_passes(plan: OptimizePlan, revisions: Revisions, adapter: Optional[Any],
                           settings: OptimizerSettings, *, with_summaries: bool = True) -> None:
      """Headings → key_items → summaries (deepest first, ``_limited_gather``); skip only matching completed passes.
      Run deterministic summary fallbacks without a live adapter. with_summaries=False leaves summaries pending.
      Reuse full-key plan.llm_cache entries, revalidate anchors, collect successful pending stamps; never stamp
      failed/unavailable/unrequested passes. Re-evaluate work invalidated by same-run structural changes.
      Count llm_calls_made/rejected_proposals and set report.llm_passes; toolkit validates and finalizes stamps."""
  ```

### Module 3: Schema, indexing and OKF aliases
- **Path**: `schemas.py`, `hybrid_search.py`, `embedding_store.py`, `okf/tools.py`, `okf/bundle.py`
- **Responsibility**: the new node fields; `key_items` in BM25 text, embedded text, cache key
  and search results; alias resolution in `OKFToolkit`; alias rewriting on OKF bundle export.
- **Depends on**: none (reads dict fields).
- **Interface Skeleton**:
  ```python
  # schemas.py (modifies :133 — after structure_source)
  class PageIndexNode(BaseModel):                                     # verified: schemas.py:118
      key_items: Optional[list[dict]] = None
      locked: Optional[bool] = None
      locked_reason: Optional[str] = None
      aliases: Optional[list[str]] = None
      optimizer: Optional[dict] = None

  # hybrid_search.py (modifies :165-180 and :420-426)
  def key_item_text(node: dict) -> str:
      """``" ".join(label for each key_item)`` or ``""``."""      # module-level helper, also used by embedding_store
  # _flatten_corpus: texts.append(f"{title} {summary} {labels} {body}".strip())           # verified: hybrid_search.py:179
  # search results: entry["key_items"] = node["key_items"] when present                   # verified: hybrid_search.py:420-426

  # embedding_store.py (modifies :96 and :282)
  @staticmethod
  def content_key(model_id: str, title: str, summary: str, extra: str = "") -> str:    # verified: embedding_store.py:96
      """Unchanged digest when ``extra`` is empty, so nodes without key_items keep their vectors."""
  # build_tree_matrix: text = f"{title} {summary} {labels}".strip(); key = content_key(..., extra=labels)  # :276-283

  # okf/tools.py (modifies :82-85)
  # for node in structure_to_list(...): map concept_id AND every entry of node.get("aliases") or [] → node

  # okf/bundle.py (modifies :185, :206, :291, :325)                                        # verified at f426e44f8d
  # export_okf_bundle, after the concept_id → path map (:286-291): for every node, map each entry of
  #   node.get("aliases") or [] to that node's path, and build alias_to_concept = {alias: node concept_id};
  #   a live concept_id always wins over an equal alias. _rewrite_pageindex_uris (:146) then rewrites
  #   pageindex:// links that name an alias to the absorber's file with no change of its own.
  def _export_frontmatter(node: dict, tree_name: str,
                          alias_to_concept: Optional[dict[str, str]] = None) -> str:     # verified: bundle.py:185
      """``relates_to`` targets are exported as ``alias_to_concept.get(concept, concept)`` (:206). No ``aliases`` key
      is written; ``import_okf_bundle`` is unchanged."""
  ```

### Module 4: Toolkit integration
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py`, `__init__.py`,
  `mcp/_toolkit_templates/pageindex.yaml` (comment)
- **Responsibility**: constructor options, the import hook, the `optimize` tool, the lock
  semantics, exports.
- **Depends on**: M1, M2, M3.
- **Interface Skeleton**:
  ```python
  # toolkit.py (modifies)
  class PageIndexToolkit(AbstractToolkit):                                   # verified: toolkit.py:92
      def __init__(self, ..., agentic_timeout_s: float = 120.0,            # verified: toolkit.py:171
                   optimize_on_import: bool = True,
                   optimizer_settings: Optional[OptimizerSettings | dict] = None, *, llm_client=None, ...): ...
      # llm_dependent_tools unchanged: pageindex_optimize works without a model   # verified: toolkit.py:137-145

      def _revisions_for(self, tree_name: str, roots: list[dict]) -> Revisions:
          """Load every (doc_id, revision) named under ``roots`` through SegmentStore; missing files are skipped and reported."""

      async def _optimize_import(self, txn: WriteTransaction, revision: DocumentRevision, roots: list[dict],
                                 *, with_summaries: bool) -> OptimizeReport:
          """Plan and run requested passes on the just-imported subtree; live calls only with a live adapter.
          Stage only mutable touched nodes, validate, finalize successful stamps, then validate the final candidate.
          Any validation failure aborts the enclosing import transaction. Called after _stage_document."""

      async def optimize(self, tree_name: str, node_id: Optional[str] = None, apply: bool = False,
                         llm_passes: bool = True, target_leaf_tokens: Optional[int] = None,
                         min_leaf_tokens: Optional[int] = None) -> dict[str, Any]:
          """Plan (dry run by default) or plan-and-publish the optimization of a tree or subtree.

          The result is quoted document data, not instructions. Returns the ``OptimizeReport`` as a dict; with
          ``apply=True`` publishes only when the final candidate differs; an identical standalone transaction uses
          txn.noop and generation_after equals generation_before. Preserve protected bodies and references during
          staging; validate again after staging/stamp finalization. Validation errors abort without publication.
          Raises KeyError for an unknown tree or node."""

      async def update_node(self, tree_name, node_id, title=None, summary=None,
                            locked: Optional[bool] = None) -> dict[str, Any]:        # verified: toolkit.py:2222
          """``locked`` toggles the optimizer exclusion flag (``locked_reason: "manual"``)."""
      # update_node_content (verified: toolkit.py:2209-2213): when node.get("doc_id") → node["locked"] = True,
      #   node["locked_reason"] = "body_edited"
      # import_pdf (verified: toolkit.py:1856-1861): "if_add_node_summary": "yes" only when with_summaries and NOT
      #   optimize_on_import; describe_document runs after _optimize_import when with_doc_description and a live adapter
      # insert_markdown (verified: toolkit.py:1673-1677): options={"if_add_node_summary": "no"} when optimize_on_import

  # __init__.py (modifies :69): export "OptimizerSettings", "OptimizeReport"
  ```

### Module 5: Bookstore and CLIs
- **Path**: `knowledge/bookstore/library.py`, `knowledge/bookstore/cli.py`,
  `knowledge/pageindex/cli.py` (new), `parrot/cli/__init__.py`
- **Responsibility**: per-book opt-in, card TOC refresh, command surface.
- **Depends on**: M4.
- **Interface Skeleton**:
  ```python
  # bookstore/library.py (modifies — after refresh_card, :1460)
  async def optimize_book(self, book_id: str, *, apply: bool = False, llm_passes: Optional[bool] = None) -> dict[str, Any]:
      """``toolkit.optimize`` on the book's tree; ``llm_passes`` defaults to ``self.has_llm``; when applied, re-derive
      ``toc``/``toc_digest``/``chapter_count``/``page_count`` with ``derive_toc`` and upsert the card."""  # derive_toc verified: carding.py:124

  # bookstore/cli.py (modifies — new command before "remove", :569)
  @bookstore.command("optimize")
  @click.argument("book_id") @click.option("--global", "global_scope", is_flag=True) @click.option("--apply", is_flag=True)
  @click.option("--no-llm", is_flag=True) @click.option("--llm", default=None) @click.option("--json", "as_json", is_flag=True)
  def optimize_cmd(book_id, global_scope, apply, no_llm, llm, as_json) -> None:
      """Dry-run report by default; ``--apply`` publishes a generation and rebuilds the card TOC."""

  # knowledge/pageindex/cli.py (new) — loaded by the lazy registry as attribute ``pageindex``   # verified: cli/__init__.py:98-99
  @click.group() def pageindex() -> None: """PageIndex trees (optimize, inspect)."""
  @pageindex.command("optimize")
  @click.argument("tree") @click.option("--storage-dir", required=True) @click.option("--node", default=None)
  @click.option("--apply", is_flag=True) @click.option("--llm", default=None, help="provider:model; default none")
  @click.option("--target-tokens", type=int, default=None) @click.option("--json", "as_json", is_flag=True)
  def optimize(tree, storage_dir, node, apply, llm, target_tokens, as_json) -> None: ...
  # parrot/cli/__init__.py (modifies :176): "pageindex": "parrot.knowledge.pageindex.cli",
  ```

### Module 6: Evaluation harness
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_eval.py` (new)
- **Responsibility**: a deterministic report of what the settings do on a corpus (leaf token
  distribution, leaves over target, nodes before/after, `key_items`, summary lengths, LLM
  calls, LLM-sourced heading splits) so the defaults can be tuned; no tuning logic beyond a
  suggested target and the fixed `tuned_target` rule. `TreeMetrics` holds numbers and the
  file-stem label only, never a node title, so a report over a non-redistributable PDF
  (AICPA) can be quoted. Plus one tuning run (below).
- **Depends on**: M4 (runs `import_pdf` into a temporary storage dir, then `optimize`).
- **Interface Skeleton**:
  ```python
  # knowledge/pageindex/optimizer_eval.py (new) — mirrors layout_eval.py   # verified: layout_eval.py:25-59
  class EvalSettings(BaseModel): target_leaf_tokens: int; min_leaf_tokens: int; llm: Optional[str] = None
  class TreeMetrics(BaseModel):
      label: str; pages: Optional[int]; nodes_before: int; nodes_after: int; leaves_before: int; leaves_after: int
      leaf_tokens_p50: int; leaf_tokens_p90: int; leaf_tokens_max: int; leaves_over_target_before: int
      leaves_over_target_after: int; key_items: int; summary_words_mean: float; llm_calls: int; seconds: float
      llm_heading_splits: int   # report.expanded entries with source == "llm" (0 in a deterministic run)
  class EvalReport(BaseModel): created_at: str; settings: EvalSettings; results: list[TreeMetrics]; suggested_target_leaf_tokens: Optional[int]
  async def evaluate_pdf(pdf: Path, *, settings: EvalSettings, storage_dir: Path) -> TreeMetrics: ...
  async def evaluate_corpus(pdfs: list[Path], *, settings: EvalSettings, out_dir: Path = DEFAULT_OUT) -> EvalReport:
      """Writes ``optimizer_eval-<ts>.json``; ``suggested_target_leaf_tokens`` is the p75 of post-layout leaf tokens
      rounded to 100, or ``None`` with fewer than three trees."""
  def tuned_target(report: EvalReport, current: OptimizerSettings) -> Optional[int]:
      """``report.suggested_target_leaf_tokens`` when it is not ``None`` and lies in
      ``[2 * current.min_leaf_tokens, 2 * current.target_leaf_tokens]``; else ``None``. The lower bound keeps a split
      possible (both pieces ≥ the floor); the upper bound keeps G1 (expansion first) from being tuned away."""
  def main(argv: Optional[list[str]] = None) -> int: ...   # python -m parrot.knowledge.pageindex.optimizer_eval <pdf|dir>...
      # prints the report path and tuned_target(report, OptimizerSettings())
  ```
- **Tuning run** (the last M6 task; after every M1 and M4 task, before M7). It is not a
  Validation Command and not a test (AC-1: no `real_llm` test); it runs once and can take
  minutes:
  - **Inputs**: the four PDFs in the primary checkout's gitignored
    `corpus/compliance_soc2_hipaa/raw/` (`nist_800_53_r5.pdf`, `nist_csf_2_0.pdf`,
    `hipaa_45cfr164_2022.pdf`, `aicpa_tsc_2017.pdf`) plus the committed
    `tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf`. A feature worktree has no
    copy of the corpus; read it from the primary checkout, which the worker sandbox mounts
    read-only: `MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)`.
  - **Mode**: deterministic (no `--llm`); the worker sandbox has no route to a model
    provider. The report goes to the default `artifacts/logs/optimizer_eval/` (gitignored)
    and is never committed.
  - **Rule**: when `tuned_target` returns a value, it becomes the `target_leaf_tokens`
    default in `OptimizerSettings`; otherwise the default stays 1500. No other default
    changes.
  - **Evidence**: the Completion Note gives the report path and its sha256, the number of
    PDFs evaluated, `suggested_target_leaf_tokens` and the `tuned_target` result, and copies
    every number it quotes from that report. If fewer than three PDFs can be read or the run
    fails, the note says "not run" with the error and no default changes; it never
    estimates a number.
  - **Follow-up**: the task opens one ledger issue (`--kind tech_debt --discovered-from
    spec:FEAT-846`) for an LLM-mode run on the host that measures `llm_heading_splits`,
    `key_items` and summary lengths and settles the LLM-dependent defaults.

### Module 7: Documentation and integration tests
- **Path**: `wiki/knowledge/pageindex-tree-optimizer.md` (new), `wiki/knowledge/pageindex.md`
  (Configuration Options), `wiki/knowledge/pageindex-local-mcp.md` (tool list),
  `tests/knowledge/pageindex/test_optimizer_integration.py`, `test_optimizer_docs.py`
- **Responsibility**: the §10 pages and the end-to-end scenarios of §4.
- **Depends on**: all.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_owned_tokens_and_scope` | M1 | tokens from owned ranges; roots without `doc_id`, with a missing revision, or `locked` are out of scope; `node_id` restricts |
| `test_repair_gaps_and_reject_overlaps` | M1 | a gap left by a deleted child is re-owned by the parent and counted; an overlap aborts the document with an error |
| `test_normalize_duplicates_empty_and_tiny` | M1 | identical spans collapse; empty leaves go; under-minimum contiguous leaves merge with alias + literal key_item; non-contiguous ones stay |
| `test_assign_ownership_residuals` | M1 | leading, interstitial and trailing parent text stays owned by the parent; `render_body` shows gap markers |
| `test_expand_at_headings_and_cost_model` | M1 | shallowest level first; `should_expand` refuses pieces under the floor and splits whose cost beats scanning |
| `test_stamp_idempotence` | M1 | deterministic planning writes no completion stamps; per-pass matching includes version/settings/input/execution; finalization preserves matching records and timestamps; legacy blanket stamps miss |
| `test_stamp_summary_dependencies` | M1 | changing child summary or own/child key_items invalidates parent summary input even when titles/spans/owned ranges stay identical |
| `test_validate_candidate` | M1 | partition check per document, key_item anchors, locked and out-of-scope nodes unchanged |
| `test_heading_like_and_proposals` | M2 | acceptance rule; proposals outside owned ranges or table/code/caption segments are rejected and counted |
| `test_key_items_literal_check` | M2 | literal labels must occur in their anchor; abstractive need a valid anchor; cap |
| `test_summaries_inline_llm_composed` | M2 | inline for short leaves (no call), word cap for LLM leaves, parents composed; deterministic fallback with `_NullAdapter` |
| `test_adapter_is_live` | M2 | `_NullAdapter`-shaped objects are not live |
| `test_first_run_executes_before_stamping` | M2 | fresh unstamped candidates actually call heading/key-item/summary passes where eligible; successful empty proposals complete, failures/unavailable passes do not; stamps finalize only after validation |
| `test_stamp_capability_upgrade` | M2 | same settings: no-model run followed by live-model run performs pending model work and replaces deterministic large-leaf/parent summaries; unchanged third run makes zero calls; changed provider/model invalidates live records |
| `test_summaries_deferred_then_requested` | M2 | with_summaries=False creates no summary completion record; later with_summaries=True computes summaries; inline summaries remain deterministic |
| `test_retry_cache_dependencies` | M2 | unchanged full pass keys reuse outputs; changed execution context or child summary misses the corresponding cache entry; cached anchors are revalidated after retry |
| `test_framed_document_description` | M2 | capture the actual description adapter call: every title/summary is inside frame_text, embedded closing tags are neutralized, instructions outside, system prompt exact; legacy description helper is not called |
| `test_prompts_are_framed` | M2 | every prompt contains `<document_text` and the system prompt is `DATA_FRAMING_INSTRUCTION` |
| `test_schema_fields_roundtrip` | M3 | new optional fields serialize and old trees validate |
| `test_bm25_and_embedding_see_key_items` | M3 | labels in `_flatten_corpus` text and in search results; `content_key` unchanged without `extra` |
| `test_okf_alias_resolution` | M3 | `get_concept`/`cite` resolve an alias to the absorber |
| `test_okf_bundle_rewrites_aliases` | M3 | an exported bundle rewrites a `pageindex://` link and a `relates_to` target naming an absorbed `concept_id` to the absorber's file and id; a live `concept_id` wins over an equal alias; no `aliases` key in any frontmatter |
| `test_optimize_dry_run_and_apply` | M4 | dry run publishes nothing; apply publishes one generation, bodies re-rendered, `node_id`s renumbered, concept ids deduped |
| `test_optimize_on_import_paths` | M4 | pdf (fake builder with `_segments`), markdown and ebook imports stage optimized subtrees; `optimize_on_import=False` is byte-identical to today |
| `test_locked_semantics` | M4 | body edit locks node; optimize a sibling in the same document and then the full tree: edited bytes/body_ref and locked descendants stay identical; selection beneath a locked ancestor is excluded |
| `test_final_staging_validation` | M4 | inject a protected body_ref change during staging or stamp finalization: final validation rejects and no generation publishes; set_body/drop_body never called on protected nodes |
| `test_same_document_subtree_staging` | M4 | optimize one subtree while another subtree of the same document is out of scope: its bodies, body_ref and stamps are byte-identical; complete-document ownership still validates |
| `test_optimize_stale_retry` | M4 | a publish between planning and apply is re-planned; LLM cache reused (call count) |
| `test_optimize_rejects_bad_candidate` | M4 | an injected overlap yields `errors` and no new generation |
| `test_optimize_without_model` | M4 | `pageindex_optimize` listed without `llm`; `llm_passes: "skipped (no model)"` |
| `test_optimize_book_and_cli` | M5 | `optimize_book(apply=True)` rebuilds card TOC fields; `bookstore optimize` and `parrot pageindex optimize` print a report |
| `test_optimizer_eval_report` | M6 | metrics and suggested target over the arxiv fixture with a fake adapter; `llm_heading_splits` counts `ExpandAction(source="llm")`; the JSON report contains no node title |
| `test_tuned_target_bounds` | M6 | `tuned_target` returns the suggestion inside `[2 × min_leaf_tokens, 2 × target_leaf_tokens]` and `None` below, above, or with fewer than three trees |

### Integration Tests
| Test | Description |
|---|---|
| `test_optimizer_integration.py::test_import_then_optimize_is_noop` | real arxiv fixture, fake live adapter: import executes eligible passes and finalizes stamps; identical `optimize(apply=True)` publishes nothing, preserves timestamps/body_ref and reports zero actions/calls |
| `test_optimizer_integration.py::test_deferred_summaries_and_parent_refresh` | import without summaries, then explicitly optimize with live adapter; summaries are produced. Edit one child summary and optimize the full tree: its parent is recomposed while unrelated completed passes remain cached |
| `test_optimizer_integration.py::test_import_description_is_framed` | optimized PDF import with_doc_description=True captures the actual description call and verifies framed payload/system prompt; with no model it makes no description call; opt-out import retains legacy behavior |
| `test_optimizer_integration.py::test_subtree_optimize_preserves_outside_ownership` | two documents in one tree; optimizing one leaves the other's owned ranges and bodies byte-identical while its `node_id`s renumber |
| `test_optimizer_integration.py::test_citations_survive_optimize` | a citation validated before optimize (FEAT-843 validator) still validates after, same revision |
| `test_optimizer_integration.py::test_two_processes_optimize_and_edit` | mp pattern of `test_segment_integration.py`: an edit between planning and publish is not overwritten (stale → re-plan) |
| `test_optimizer_docs.py` | the §10 page exists, has frontmatter, names the settings and the two commands (pattern of `test_layout_docs.py`) |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_eval.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segments.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py
- packages/ai-parrot/tests/knowledge/pageindex/test_read_tools.py
- packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py
- packages/ai-parrot/tests/knowledge/pageindex/test_embedding_store.py
- packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py
- packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py
- packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py
- packages/ai-parrot/tests/knowledge/pageindex/test_citations.py
- packages/ai-parrot/tests/knowledge/pageindex/test_schemas.py
- packages/ai-parrot/tests/knowledge/bookstore/test_library.py
- packages/ai-parrot/tests/knowledge/bookstore/test_cli.py
- packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py
markers: none

### Test Data / Fixtures
```python
# Synthetic revisions (no PDF): a DocumentRevision built from segment_text()/segment_pages() over a markdown string
# with headings at two levels, one long section (> target) and two tiny consecutive sections (< min). Token
# counts come through utils.count_tokens, which tests stub via the module attribute (tiktoken downloads encodings on
# first use — see test_segment_integration.py:40-49):
#   monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda t, model="gpt-4o": max(1, len(t) // 4))
# Fake live adapter: MagicMock with .client set (so adapter_is_live is True), .ask_structured returning the pydantic
# proposal objects, .ask returning a summary string — the _adapter() helper of test_segment_integration.py extended.
# Null adapter: an object with client=None (Bookstore's _NullAdapter shape) to prove the LLM passes are skipped.
# PDF: tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf through the real layout builder (structure_mode="layout").
# Bookstore: tmp library location + the fixture PDF (pattern of tests/knowledge/bookstore/test_library.py).
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-1 Every test file in the Validation Contract passes; no `real_llm` test is added.
- [ ] AC-2 Documentation page `wiki/knowledge/pageindex-tree-optimizer.md` exists and `parrot sdd techwiki check` passes for the §10 pages.
- [ ] AC-3 (G1/G3) A leaf over `target_leaf_tokens` with heading segments inside is split at them when the cost model allows; a split that would leave a piece under `min_leaf_tokens` is not taken; the trigger uses tokens over owned segments, never page counts.
- [ ] AC-4 (G2) No pass creates a node whose title is not a heading segment or an accepted heading-like printed line; concepts become `key_items` with `kind` and a valid anchor; a `literal` label occurs in its anchor text.
- [ ] AC-5 (G4) After `optimize(apply=True)` and after every optimized import, `validate_ownership` over each affected document returns no problems; a candidate that fails validation publishes nothing and reports `errors`.
- [ ] AC-6 (G5) No edit operation (`add_node`, `delete_node`, `update_node`, `update_node_content`, `tag_node`, `rename_tree`) calls the optimizer; `import_pdf`, `insert_markdown`, `insert_ebook` do when `optimize_on_import` is true; `optimize()` defaults to a dry run that opens no transaction.
- [ ] AC-7 (G6) First-run eligible passes execute before completion stamps are finalized. A second `optimize(apply=True)` with the same inputs, settings and execution context publishes no new generation, makes no LLM calls and reports zero merges, expansions, key_items and summaries; matching stamp timestamps and body references are unchanged. Unavailable/failed/unrequested passes are not marked complete. Later model availability or summary enablement runs deferred work; child-summary/key-item changes invalidate dependent parent summaries and retry-cache entries.
- [ ] AC-8 (G7) Nodes without `doc_id`, nodes flagged `locked` and their descendants are never modified; ancestor locks above a selected subtree also apply. A subtree optimize leaves every node outside it unchanged except `node_id`, including same-document bodies, body_ref and stamps. `update_node_content` on a segment-backed node sets `locked`/`locked_reason`. Body staging excludes protected nodes and final validation after staging/stamp finalization rejects any violation without publication.
- [ ] AC-9 (G8) Summaries: a leaf at or below `inline_summary_tokens` makes no LLM call; parents are composed after their children; no summary exceeds `summary_max_words` by more than 20 %; with a `_NullAdapter` or no adapter the deterministic summaries are used and no call is made.
- [ ] AC-10 (G9) `key_items` labels appear in the BM25 corpus text, in the embedded text and cache key (unchanged key when absent), in search results and in `outline`.
- [ ] AC-11 (G10) A `concept_id` removed by a merge resolves through `OKFToolkit.get_concept` and `cite` to the absorbing node, whose `key_items` include the merged title as `literal`. An exported OKF bundle rewrites links and `relates_to` targets naming it to the absorbing node's file and `concept_id`, and writes no `aliases` frontmatter key.
- [ ] AC-12 (G11) Every optimizer/summary prompt, including the document description on optimized imports, wraps document-derived content in `<document_text …>` with `DATA_FRAMING_INSTRUCTION` as system prompt; instructions stay outside the frame and embedded closing tags are neutralized by the framing helpers. The optimized description path never calls the legacy unframed helper; a proposal naming a segment outside what the model was shown is rejected, including cached proposals after a retry.
- [ ] AC-13 (G12) `bookstore add` of a PDF yields an optimized tree and a card TOC derived from it; `bookstore optimize <id> --apply` republishes and rewrites `toc`, `toc_digest`, `chapter_count`, `page_count`; without `--apply` the card and tree are unchanged.
- [ ] AC-14 `pageindex_optimize` is served by `parrot mcp-local pageindex` without `llm:` (not in `llm_dependent_tools`), and the report then says `llm_passes: "skipped (no model)"`.
- [ ] AC-15 A citation validated before `optimize(apply=True)` validates after it (same `doc_id`/`revision`); `optimize` never writes a revision file.
- [ ] AC-16 `optimize_on_import=False` reproduces today's import output byte-for-byte for the three paths (existing import tests unchanged under that flag).
- [ ] AC-17 `python -m parrot.knowledge.pageindex.optimizer_eval <pdf>` writes a JSON report with the §3 M6 metrics (including `llm_heading_splits`; numbers and file-stem labels only, no node title) and prints `tuned_target`.
- [ ] AC-18 No breaking change: every new node field is optional, every new constructor argument has a default, `content_key(model_id, title, summary)` keeps its digest.
- [ ] AC-19 (G13) The M6 tuning run was executed once, deterministically, over the four compliance PDFs and the arXiv fixture. Its Completion Note gives the report path and sha256 and copies every number from that report. `OptimizerSettings().target_leaf_tokens` equals `tuned_target(report, …)` when that returned a value and 1500 otherwise; no other default changed. If fewer than three PDFs could be evaluated, the note says "not run" with the error. The LLM-mode follow-up ledger issue exists.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified at `dev` @ `09d3377826`. Paths are relative to `packages/ai-parrot/src/parrot/` unless stated.

### Verified Imports
```python
from parrot.knowledge.pageindex.segments import (                     # segments.py
    Segment, DocumentRevision, SegmentAddress, SegmentRead, SourceInfo,  # :33, :59, :71, :97, :49
    normalize_title, _titles_match, _subtract, _heading_text,            # :305, :312, :323, :340
    attach_pdf_document, attach_section_document, render_body, validate_ownership,  # :358, :447, :475, :490
    segment_pages, segment_text, revision_id, derive_doc_id,             # :231, :240, :249, :254
)
from parrot.knowledge.pageindex.segment_store import SegmentStore      # segment_store.py:25
from parrot.knowledge.pageindex.generation import (                    # generation.py
    WriteTransaction, StaleGenerationError, generation_of, ensure_concept_ids, BodyRef,  # :116, :67, :81, :93, :37
)
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text  # framing.py:10, :33, :39
from parrot.knowledge.pageindex.builder import (                       # builder.py
    _LLM_SEMAPHORE, _limited_gather, build_page_index,  # :75, :80, :1571; legacy description helper not used here
)
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title, StructureReport  # :23, :61, :38
from parrot.knowledge.pageindex.layout import StructureSource          # layout.py:24
from parrot.knowledge.pageindex.utils import (                         # utils.py
    count_tokens, write_node_id, structure_to_list, find_node_by_id, create_clean_structure_for_description,  # :66, :262, :294, :353, :713
)
from parrot.knowledge.pageindex import utils as _utils                 # count_tokens via the module (segments.py:11 pattern; tests stub it)
from parrot.knowledge.pageindex.tree_ops import reindex_node_ids, splice_subtree  # tree_ops.py:22, :89
from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id, dedup_concept_ids  # okf/concept_id.py:72, :103
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter  # llm_adapter.py:42 (ask :61, ask_structured :99)
from parrot.knowledge.pageindex.locks import tree_lock                 # locks.py:47
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # hybrid_search.py:52
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore   # embedding_store.py:44
from parrot.knowledge.pageindex.okf.tools import OKFToolkit            # okf/tools.py:46
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError, _NullAdapter  # library.py:179, :112, :150
from parrot.knowledge.bookstore.carding import derive_toc              # carding.py:124
from parrot.knowledge.pageindex import (                               # __init__.py — list ends at :69 "EvidenceBundle",
    PageIndexToolkit, SegmentStore, DocumentRevision, Segment, SegmentAddress, ReadResult, Citation, validate_citations)
```

### Existing Class Signatures
```python
# knowledge/pageindex/segments.py
class Segment(BaseModel):                       # :33  seq, kind, page, ordinal, section, level, text, tokens, sha16, flags, injection
class DocumentRevision(BaseModel):              # :59  doc_id, revision, source: SourceInfo, segmenter, scored_by, created_at, segments
class SegmentAddress(BaseModel):                # :71  doc_id, revision, seq, page, ordinal, section; .label :82; .key :92
class SegmentRead(BaseModel):                   # :97  address, seq, kind, text, start, end, truncated, flags
Range = tuple[int, int]                         # :302
def _subtract(span: Range, holes: Sequence[Range]) -> list[Range]                       # :323
def _heading_text(text: str) -> str                                                     # :340
def attach_pdf_document(structure: list[dict], revision: DocumentRevision) -> None      # :358 (sets doc_id/revision/span/owned; pops anchor)
def attach_section_document(structure, revision, by_node: dict[int, tuple[int, int]]) -> None  # :447
def render_body(revision: DocumentRevision, node: dict, children: Sequence[dict]) -> str  # :475 ("<!-- continues in: <title> -->" markers)
def validate_ownership(nodes: Sequence[dict], revision: DocumentRevision) -> list[str]   # :490 (empty ⇒ partition of [0, n))

# knowledge/pageindex/segment_store.py
class SegmentStore:                             # :25  <storage_dir>/<tree>/segments/<doc_id>.<revision>.json
    def load_revision(self, tree_name, doc_id, revision) -> Optional[DocumentRevision]   # :64 (LRU)
    def has_revision(self, tree_name, doc_id, revision) -> bool                          # :80
    @staticmethod live_revisions(tree) -> set[tuple[str, str]]                           # :98

# knowledge/pageindex/generation.py
class WriteTransaction:                         # :116  tree (deep copy), base_generation, noop (:147)
    def set_body(self, node, markdown) -> BodyRef   # :161 (needs concept_id; ensure_concept_ids otherwise)
    def set_revision(self, rev) -> None             # :176
    def drop_body(self, node) -> None               # :184
    async def publish(self) -> PublishReport        # :203 (tree_lock → _publish_locked :221: stale check, ensure_concept_ids :234,
                                                    #        body/revision presence checks, OKF projector :273, save :276, sweeps)
def ensure_concept_ids(tree) -> int             # :93  (derive_concept_id per node; NO sibling dedup)

# knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):        # :92  name/tool_prefix "pageindex" :134-135
    llm_dependent_tools = frozenset({... "pageindex_agentic_retrieve"})                  # :137-145
    def __init__(self, adapter=None, storage_dir=None, ..., agentic_timeout_s=120.0, *, llm_client=None,
                 max_result_chars=None, **kwargs)                                        # :147-176; self._adapter :184; _segment_store :198
    async def _write(self, tree_name) -> AsyncIterator[WriteTransaction]                 # :267 (joins an open txn; publishes on exit)
    def _after_publish(self, tree_name, txn) -> None                                     # :298 (swaps caches, prunes matrices)
    async def _mutate(self, tree_name, apply, *, attempts=3) -> T                        # :322 (retries StaleGenerationError)
    @property has_llm -> bool                                                            # :375 (True for Bookstore's _NullAdapter too)
    def _load_tree(self, tree_name) -> dict                                              # :425
    def _search_for(self, tree_name) -> HybridPageIndexSearch                            # :445 (rebuilt per generation id)
    async def _run_t3_classification(self, tree, original_id_to_node) -> None            # :500
    async def _outline_on(...)                                                           # :902 (key_items pass-through :941-942)
    async def index_segments(self, tree_name, node_id=None) -> dict                      # :1270 (legacy → section revisions)
    async def insert_markdown(self, tree_name, markdown, parent_node_id=None, doc_name=None, doc_id=None) -> dict  # :1651
        # md_to_tree(md_text=markdown, adapter=self._adapter, doc_name=...) :1673 — no options ⇒ summaries "yes"
        # apply :1686; attach_section_document :1703; splice :1704; _stage_document :1706; T3 :1710
    async def insert_ebook(self, tree_name, sections, parent_node_id=None, doc_id=None) -> dict  # :1716 (:1763 stage, :1767 T3)
    async def insert_content(...) -> dict                                                # :1779 (→ insert_markdown :1793)
    async def import_file(...) -> dict                                                   # :1803 (→ insert_content)
    async def import_pdf(self, tree_name, pdf_path, parent_node_id=None, with_summaries=True,
                         with_doc_description=False, doc_id=None, structure_mode="auto") -> dict  # :1822
        # build_page_index(... options={"if_add_node_summary": ..., "if_add_doc_description": ..., "if_add_node_id": "yes",
        #   "structure_mode": ...}, light_adapter=self._light_adapter) :1853-1863; pops _node_markdown/_pages/_segments :1868-1870
        # apply :1887; attach_pdf_document :1901; splice :1904; _stage_document :1906; T3 :1910
    async def _scan(self, segments) -> Optional[ScanReport]                              # :1931
    def _stage_document(self, txn, revision, roots) -> None                              # :1968 (set_revision + render_body per node)
    @staticmethod _new_revision(doc_id, segments, source, report) -> DocumentRevision    # :1983
    async def delete_node(self, tree_name, node_id) -> dict                              # :2098
    async def add_node(self, tree_name, title, body="", parent_node_id=None, ...) -> dict  # :2129
    async def update_node_content(self, tree_name, node_id, body) -> dict               # :2192 (apply :2209-2213: txn.set_body)
    async def update_node(self, tree_name, node_id, title=None, summary=None) -> dict    # :2222
def _capture_node_id_object_map(subtree) -> dict[str, dict]                              # :2351
def _section_segments(roots, texts) -> tuple[list, dict[str, tuple[int, int]]]          # :2307

# knowledge/pageindex/builder.py
_LLM_SEMAPHORE: ContextVar[Optional[asyncio.Semaphore]]                                  # :75
async def _limited_gather(coros, *, return_exceptions=False) -> list                     # :80 (plain gather when the var is unset)
async def generate_node_summary(node, adapter) -> str                                    # :1522 (unframed; legacy)
async def generate_summaries_for_structure(structure, adapter)                           # :1536
async def generate_doc_description(structure, adapter) -> str                            # :1553; unframed legacy path only
async def build_page_index(doc, adapter=None, options=None, light_adapter=None, llm_concurrency=16) -> dict  # :1571
    # sets _LLM_SEMAPHORE :1603; summaries + description only inside `elif opt.if_add_node_summary == "yes"` :1639-1647
    # returns {doc_name, structure, structure_source, structure_report, _node_markdown, _pages, _segments[, doc_description]}

# knowledge/pageindex/md_builder.py   (re-verified at f426e44f8d)
def thin_tree(tree, max_token_threshold=200) -> list[dict]                               # :206 (no longer called by md_to_tree)
async def generate_prefix_summaries(tree, adapter) -> None                               # :249
async def md_to_tree(md_text, adapter=None, options=None, doc_name="document.md") -> dict  # :277
    # default_opts if_add_node_summary "yes" :302; no thinning (comment :327); summaries when adapter :332;
    # text before the first heading becomes an "Introduction" section (parse_markdown_structure)

# knowledge/pageindex/hybrid_search.py
_BM25_TEXT_LIMIT = 4000                                                                  # :49
class HybridPageIndexSearch:                                                             # :52 (__init__ :74; generation_id :113)
    def _flatten_corpus(self) -> tuple[list[str], list[str]]                             # :165 (texts.append(f"{title} {summary} {body}") :179)
    async def search(...) -> list[dict]                                                  # results dict :420-426 (node_id, title, summary, score, source)

# knowledge/pageindex/embedding_store.py
class NodeEmbeddingStore:                                                                # :44
    @staticmethod content_key(model_id, title, summary) -> str                           # :96  sha1(model_id\x00title\x00summary)
    def get_or_embed(self, tree_name, node_id, title, summary) -> Optional[np.ndarray]   # :210 (key :232)
    def build_tree_matrix(self, tree_name, nodes, embed_fn, *, generation_id=0)          # :243 (loop :276-283; text = f"{title} {summary}" :282)

# knowledge/pageindex/okf/tools.py
class OKFToolkit:                                                                        # :46 (NOT an AbstractToolkit)
    def __init__(self, tree, graph, content_store, tree_name, store=None)                # :66; _by_concept_id built :81-85
    def get_concept(self, concept_id) -> dict                                            # :174 (KeyError when unknown)
    def cite(self, concept_id) -> dict                                                   # :255

# knowledge/pageindex/okf/bundle.py   (verified at f426e44f8d)
def _rewrite_pageindex_uris(text, src_rel_path, concept_file_map) -> tuple[str, int]    # :146 (only ids in the map are rewritten)
def _export_frontmatter(node: dict, tree_name: str) -> str                              # :185 (relates_to concept ids exported as-is :206)
def export_okf_bundle(tree, tree_name, content_store, output_dir) -> ExportReport         # :252 (concept_file_map :286-291; frontmatter call :325)

# knowledge/pageindex/okf/concept_id.py
def derive_concept_id(title, parent_path="") -> str                                      # :72
def dedup_concept_ids(nodes: list[dict]) -> None                                         # :103 (-2, -3 suffixes in list order)

# knowledge/pageindex/tree_ops.py
def reindex_node_ids(tree) -> None                                                       # :22 (concept_id untouched)
def splice_subtree(target, subtree, parent_node_id=None) -> list[str]                    # :89 (reindex + _assign_okf_concept_ids :126-127)

# knowledge/pageindex/layout_structure.py / layout.py
MAX_HEADING_WORDS = 20                                                                   # layout_structure.py:23
def heading_title(text: str) -> str                                                      # :61
StructureSource = Literal["bookmarks", "layout", "hybrid", "llm", "pages"]               # layout.py:24

# knowledge/pageindex/schemas.py
class PageIndexNode(BaseModel):                                                          # :118  ... doc_id :129, revision :130, span :131, owned :132,
    structure_source: Optional[str] = None                                               # :133; model_config extra="allow" :136

# knowledge/pageindex/utils.py
def count_tokens(text, model="gpt-4o") -> int                                            # :66 (tiktoken; char estimate offline)
class ConfigLoader: _DEFAULTS = {..., "max_page_num_each_node": 10, "max_token_num_each_node": 20000, "structure_mode": "auto",
                                 "structure_min_confidence": 0.6}                        # :761-775 (unknown keys raise :788-791)
def create_clean_structure_for_description(structure) -> Any                             # :713

# knowledge/bookstore/library.py
class _NullAdapter: model = None; client = None; async def ask(...) -> ""; ask_structured raises RuntimeError  # :150-176
class Bookstore:                                                                         # :179  has_llm :216 (adapter is not None)
    def _toolkit(self, scope) -> PageIndexToolkit                                        # :234 (adapter or _NullAdapter(), generation_grace_s=_STAGING_MAX_AGE_S)
    def get_toc(self, book_id) -> dict                                                   # :355 (from card.toc)
    async def add_book(...) -> tuple[BookCard, str]                                      # :1061 (import_pdf :1132 with_summaries=self.has_llm,
                                                                                         #   structure_mode "auto"|"layout" :1137; get_tree :1171; derive_toc :1172; rename_tree :1229)
    async def refresh_card(self, book_id) -> BookCard                                    # :1460 (derive_toc :1464; upsert :1500)
# knowledge/bookstore/carding.py
def derive_toc(tree, max_depth=2) -> tuple[list[TocEntry], str]                          # :124
# knowledge/bookstore/cli.py — click group ``bookstore`` :98; ``add`` :102-155 (--no-llm, --llm); ``remove`` :569; ``main`` :609
# cli/__init__.py — lazy registry :170-; get_command → getattr(mod, cmd_name.replace("-", "_")) :98-99
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_optimize_import` | `_stage_document` call sites | call right after, same `txn` | `toolkit.py:1706, 1763, 1906` |
| `optimize(apply=True)` | `_mutate` | apply closure re-plans on `txn.tree` | `toolkit.py:322-350` |
| body re-staging | `WriteTransaction.set_body` / `drop_body` | `render_body` output per node | `generation.py:161, 184`; `segments.py:475` |
| partition check | `validate_ownership` | per document, all nodes of that `doc_id` | `segments.py:490` |
| revisions in scope | `SegmentStore.load_revision` | `self._segment_store` | `toolkit.py:198`; `segment_store.py:64` |
| LLM fan-out | `_limited_gather` / `_LLM_SEMAPHORE` | set the var when unset, like `build_page_index` | `builder.py:80, 1603` |
| prompts | `frame_segments` + `DATA_FRAMING_INSTRUCTION` | user prompt / system prompt | `framing.py:33, 10` |
| structured outputs | `PageIndexLLMAdapter.ask_structured` | `output_type=` pydantic | `llm_adapter.py:99` |
| import summaries off | `build_page_index` options | `"if_add_node_summary": "no"` | `toolkit.py:1856-1861`; `builder.py:1639` |
| description after summaries | new `optimizer_llm.describe_document` + `create_clean_structure_for_description` + `frame_text` | toolkit optimized-import call; legacy helper bypassed | `utils.py:709`; `framing.py:39`; legacy `builder.py:1553-1566` |
| markdown summaries off | `md_to_tree(options=…)` | `{"if_add_node_summary": "no"}` | `toolkit.py:1675`; `md_builder.py:300-336` (f426e44f8d) |
| new node ids | `derive_concept_id` + `dedup_concept_ids` | per sibling list before publish | `concept_id.py:72, 103` |
| BM25 text | `_flatten_corpus` | labels joined into the text | `hybrid_search.py:179` |
| embedding text/key | `build_tree_matrix` / `content_key(extra=)` | labels | `embedding_store.py:276-283, 96` |
| alias lookup | `OKFToolkit._by_concept_id` | map aliases too | `okf/tools.py:82-85` |
| alias export | `export_okf_bundle` / `_export_frontmatter` | alias → absorber path in `concept_file_map`; `relates_to` through `alias_to_concept` | `okf/bundle.py:286-291, 206, 325` (f426e44f8d) |
| card TOC after optimize | `derive_toc` + `catalog.upsert` | `optimize_book` | `library.py:1464, 1500` |
| CLI group | lazy registry | `"pageindex"` entry, attribute `pageindex` | `cli/__init__.py:176, 98-99` |

### Does NOT Exist (Anti-Hallucination)
Checked with `grep -rn` over `knowledge/pageindex/` and `knowledge/bookstore/` at `09d3377826`:
- ~~`optimizer.py`, `optimizer_llm.py`, `optimizer_eval.py`, `knowledge/pageindex/cli.py`~~ — created by this spec
- ~~`OptimizerSettings`, `OptimizeReport`, `PassStamp`, `OptimizerStamp`, `KeyItem`, `OptimizePlan`~~ — new here
- ~~`optimizer_llm.describe_document`~~ — new framed helper here; existing `builder.generate_doc_description` remains unframed and is not reused
- ~~any writer of `key_items`~~ — only `_outline_on` reads it (`toolkit.py:941`)
- ~~`locked`, `locked_reason`, `aliases`, `optimizer` node fields~~ — nothing reads or writes them
- ~~`PageIndexToolkit.optimize`, `_optimize_import`, `_revisions_for`~~; ~~`Bookstore.optimize_book`~~; ~~`bookstore optimize`~~; ~~`parrot pageindex`~~
- ~~sibling dedup in `ensure_concept_ids` or `_assign_okf_concept_ids`~~ — both call `derive_concept_id` only (`generation.py:105`, `tree_ops.py:80`); `dedup_concept_ids` exists but is not called by them
- ~~a `summary_max_words` / word cap in any summary prompt~~ — none (`builder.py:1527`, `md_builder.py:216`)
- ~~framing in `generate_node_summary` / `generate_prefix_summaries`~~ — both unframed
- ~~an `extra` parameter on `content_key`~~ — three positional parameters today
- ~~alias handling in `OKFToolkit`, `project_frontmatter` or the OKF bundle~~ — none
- ~~`ToolkitSection.exclude` entry for `pageindex_optimize`~~ — the template excludes only `pageindex_agentic_retrieve`
- ~~`has_llm` distinguishing a `_NullAdapter`~~ — `toolkit.has_llm` is `self._adapter is not None` (`toolkit.py:377`), True for the null adapter
- ~~`structure_source` values beyond `bookmarks|layout|hybrid|llm|pages`~~ — the optimizer does not add one (its provenance goes in the stamp / `ExpandAction.source`)

### Edit Sites (Blueprint Anchors)

Verified against: `09d3377826`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_eval.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/cli.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py` | MODIFY | `    structure_source: Optional[str] = None` | `schemas.py:133` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `        agentic_timeout_s: float = 120.0,` (constructor kwargs) | `toolkit.py:171` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def vacuum_tree(self, tree_name: str, max_age_s: Optional[int] = None) -> dict[str, Any]:` (insert `optimize` before it) | `toolkit.py:1355` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def insert_markdown(` | `toolkit.py:1651` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def insert_ebook(` | `toolkit.py:1716` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def import_pdf(` | `toolkit.py:1822` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `                self._stage_document(txn, revision, fresh["structure"])` — ambiguous; context: preceded by `if revision is not None:` and followed by `imported.update(doc_id=revision.doc_id, revision=revision.revision)`; the three sites are insert_markdown (:1706), insert_ebook (:1763), import_pdf (:1906) | `toolkit.py:1706, 1763, 1906` | 3 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def update_node_content(` | `toolkit.py:2192` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    async def update_node(` | `toolkit.py:2222` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` | MODIFY | `    "EvidenceBundle",` | `__init__.py:69` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | `            texts.append(f"{title} {summary} {body}".strip())` | `hybrid_search.py:179` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | `                "summary": node.get("summary") or node.get("prefix_summary") or "",` (inside `results.append({` after `"title": node.get("title", ""),`) | `hybrid_search.py:423` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py` | MODIFY | `    def content_key(model_id: str, title: str, summary: str) -> str:` | `embedding_store.py:96` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py` | MODIFY | `            text = f"{title} {summary}".strip() if (title or summary) else ""` | `embedding_store.py:282` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py` | MODIFY | `                self._by_concept_id[cid] = node` | `okf/tools.py:85` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` | MODIFY | `def _export_frontmatter(node: dict, tree_name: str) -> str:` | `okf/bundle.py:185` (f426e44f8d) | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` | MODIFY | `            concept_file_map[cid] = _build_export_path(cid, concept_type_val)` | `okf/bundle.py:291` (f426e44f8d) | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` | MODIFY | `        frontmatter = _export_frontmatter(node, tree_name)` | `okf/bundle.py:325` (f426e44f8d) | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    async def refresh_card(self, book_id: str) -> BookCard:` (insert `optimize_book` before it) | `library.py:1460` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `@bookstore.command("remove")` (insert `optimize` before it) | `cli.py:569` | 1 |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | `    "bookstore": "parrot.knowledge.bookstore.cli",` | `cli/__init__.py:176` | 1 |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml` | MODIFY | `    exclude: [pageindex_agentic_retrieve]` (comment above it gains `pageindex_optimize`) | `pageindex.yaml:17` | 1 |
| `wiki/knowledge/pageindex-tree-optimizer.md` | CREATE | — | — | — |
| `wiki/knowledge/pageindex.md` | MODIFY | `## Configuration Options` | `pageindex.md:457` | 1 |
| `wiki/knowledge/pageindex-local-mcp.md` | MODIFY | `` - `pageindex_agentic_retrieve` `` | `pageindex-local-mcp.md:68` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Pure planner, thin toolkit.** `optimizer.py` and `optimizer_llm.py` never touch disk;
  the toolkit loads revisions, opens the transaction and stages bodies. Tests of M1/M2 need
  no storage dir.
- **Token counting via the module attribute** (`_utils.count_tokens`, as `segments.py:11`
  does) so tests can stub tiktoken.
- **Framing** exactly as FEAT-840/845: `frame_segments(reads, source=<doc name>)` in the
  user prompt, `DATA_FRAMING_INSTRUCTION` as the system prompt, instructions outside the
  frame. Proposals are keyed by `seq`, never by text the model echoes back.
- **Deepest first.** Summaries run level by level from the deepest leaves; each level's
  calls go through `_limited_gather`. Set `_LLM_SEMAPHORE` only when `.get()` is `None`
  and reset it in `finally` (the import path already runs inside `build_page_index`'s
  context for PDFs, outside it for markdown/ebook).
- **Live adapter gate** everywhere an LLM call could happen: `adapter_is_live(adapter)`.
- **Ownership helpers from FEAT-840**: `_subtract` for residual ranges, `render_body` for
  bodies, `validate_ownership` for the gate; do not reimplement them.
- **Transactions**: the apply closure must be re-runnable (it is retried on
  `StaleGenerationError`); use the complete per-pass cache key from §2, including execution
  context and consumed dependencies, and revalidate cached anchors on retry. Recompute
  candidate-local mutable/touched sets; never carry object identities between candidates.
  Stage mutable touched nodes only, validate, finalize successful stamps, validate again,
  then publish if changed. Validation errors abort the transaction; an unchanged standalone
  apply sets `txn.noop`. Joined mutators must not suppress the owning import's publication.
- **Completion stamps**: deterministic planning never stamps work as complete. Record only
  successful requested passes after validation, preserving matching timestamps. No-model
  heading/key-item passes stay pending; deterministic summary provenance cannot satisfy a
  later live summary request. Recompute parent input hashes after child summaries finish.
- **Descriptions**: use `optimizer_llm.describe_document` with `frame_text` and
  `DATA_FRAMING_INSTRUCTION` for optimized imports; leave the legacy builder helper and
  opt-out path unchanged. Use a fixed framing source label, not a document-controlled attribute.
- **Concept ids for new nodes**: `derive_concept_id(title, parent_concept_id)` for each new
  sibling list, then `dedup_concept_ids(siblings)`; never leave it to `ensure_concept_ids`
  at publish (no dedup there).
- **No edit triggers the optimizer** — `_optimize_import` is called only from the three
  import `apply` closures; `optimize` only from the tool/CLI.
- **Reports are quoted data**: the tool docstring says so (MCP hosts read it), like the
  read tools.

### Known Risks / Gotchas
- **Expansion needs heading segments.** Layout-built PDFs and markdown have them; a legacy
  tree indexed through `index_segments` or an LLM-structured PDF whose per-page markdown
  carries no `#` lines may have none, so expansion relies on the heading-like LLM proposals
  or does nothing; `key_items` still work. The report shows `leaves_over_target_after` so
  the user sees it.
- **Short markdown sections now reach revisions.** Since `f426e44f8d`, `md_to_tree` keeps
  sub-50-token sections and the text before the first heading (an "Introduction" section),
  so markdown imports produce more tiny leaves. The normalize merge rule absorbs contiguous
  ones with an alias and a literal `key_item`; nothing is dropped.
- **LLM proposals cost on retry.** A concurrent publish between planning and `publish`
  re-plans inside `_mutate`; only complete matching pass keys permit reuse. A structural edit,
  changed child summary or execution context repeats the affected calls.
- **Locked-by-edit nodes stop being views.** After `update_node_content` on a segment-backed
  node the body is the edited text, the owned ranges still describe the source; `optimize`
  skips it, `read_segments` still reads the revision. Documented in §10.
- **Embedding cache key change** only for nodes with `key_items`; vectors of unchanged nodes
  are reused (G9 without a global recompute).
- **BM25 corpus size** grows by the labels only; `_BM25_TEXT_LIMIT` still truncates the
  body — the point of smaller leaves is that less of the body falls past that limit.
- **Null adapter in Bookstore**: with `--no-llm`, `_NullAdapter.ask()` returns `""` and
  `ask_structured` raises; the live gate prevents both from being reached.
- **Cost of `validate_ownership`** is O(segments) per document per apply; fine for books,
  measured by the eval harness.
- **Evaluation corpus**: the Bookstore library is empty on this machine. The four compliance
  PDFs are gitignored and exist only in the primary checkout, so the M6 tuning run reads them
  from there (the worker sandbox mounts it read-only). In FEAT-845 (TASK-5344) the same
  corpus run was never executed and a coder seat invented a metrics table; M6 therefore
  keeps the tuning run away from coder seats, copies every number from the written report
  and records its sha256.
- **False-positive headings.** The heading-like rule can promote a short sentence to a
  node title. A split still has to pass `should_expand` (every piece ≥ `min_leaf_tokens`,
  token cost pays off) and no text is lost; `llm_heading_splits` makes the rate visible
  in the LLM-mode follow-up run.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| none new | — | `pydantic`, `tiktoken` (optional, via `count_tokens`), `bm25s` (extra) already pinned |

---

## Decisions

```yaml
schema_version: 1
document_id: pageindex-tree-optimizer
entries:
  - id: optimizer-never-runs-after-an-edit
    statement: The PageIndex optimizer runs only inside the import paths (import_pdf, insert_markdown, insert_ebook) and through the explicit optimize operation; no edit operation (add_node, delete_node, update_node, update_node_content, tag_node, rename_tree) invokes it.
    relation: forbids
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py]
    contradicts: []
    supersedes: []
    rationale: "Brainstorm resolved: the optimizer runs at import plus an explicit command; implicit restructuring after an edit would surprise curators and spend LLM calls without consent."
    rejected_alternatives: ["re-partition after every edit", "a background optimize job"]
  - id: expansion-only-at-printed-headings
    statement: Expansion creates nodes only at heading segments or accepted heading-like printed lines of the document revision; concepts found in prose are stored as key_items anchored to a segment, never as nodes.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py, file:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py]
    contradicts: []
    supersedes: []
    rationale: "Brainstorm resolved: no synthetic nodes; a tree node must correspond to something printed so page/section addresses stay meaningful."
    rejected_alternatives: ["synthetic concept nodes", "size-based splits at arbitrary paragraphs"]
  - id: optimize-publishes-a-generation-never-a-revision
    statement: Optimizing a tree publishes a new generation through WriteTransaction and never creates, rewrites or deletes a DocumentRevision; segment addresses and citations stay valid across optimization.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py, file:packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py]
    contradicts: []
    supersedes: []
    rationale: "Revision = immutable content (only a re-import changes it); generation = published shape. Keeping them apart is what lets a citation survive an optimize."
    rejected_alternatives: ["re-segmenting on optimize"]
  - id: body-edit-locks-a-segment-backed-node
    statement: update_node_content on a node that carries doc_id sets locked=true (locked_reason body_edited); locked nodes and their descendants are excluded from every optimizer pass and their bodies are never re-rendered.
    relation: requires
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py]
    contradicts: []
    supersedes: []
    rationale: "Resolves FEAT-840 §8: a hand-edited body must not be overwritten by a re-render; the node keeps its addresses but stops being a view."
    rejected_alternatives: ["re-render on the next optimize (loses the edit)", "refuse body edits on imported nodes"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:8ed1ff34933e033998fdf974d55bce38057547d8191c18075b2e4dcdd2075846 evaluation_digest=sha256:f6c7286f746e864f936b00a3867806b7d1890728df856287f0a9ad821c067704 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `possible-supersession` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-tree-optimizer#body-edit-locks-a-segment-backed-node@1, adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit@1; scope: file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py; message: adr:spec:pageindex-tree-optimizer#body-edit-locks-a-segment-backed-node and adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit share targets and about without an explicit link
- `potential-conflict` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-tree-optimizer#body-edit-locks-a-segment-backed-node@1, adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit@1; scope: file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py; message: adr:spec:pageindex-tree-optimizer#body-edit-locks-a-segment-backed-node (requires) and adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit (forbids) govern overlapping scope
- `potential-conflict` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-tree-optimizer#expansion-only-at-printed-headings@1, adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit@1; scope: file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py; message: adr:spec:pageindex-tree-optimizer#expansion-only-at-printed-headings (constrains) and adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit (forbids) govern overlapping scope
- `potential-conflict` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-tree-optimizer#optimize-publishes-a-generation-never-a-revision@1, adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit@1; scope: file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py; message: adr:spec:pageindex-tree-optimizer#optimize-publishes-a-generation-never-a-revision (constrains) and adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit (forbids) govern overlapping scope

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: prompt-injection, tree-optimizer
- Targets resolved: 3/3
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
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 3,
    "targets_total": 3,
    "unmapped_tags": [
      "prompt-injection",
      "tree-optimizer"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:f6c7286f746e864f936b00a3867806b7d1890728df856287f0a9ad821c067704",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:e211fcf9cc4d4dbaa91d88592cb5b7ee7924ca78748ee99685686eafa346c345",
      "kind": "possible-supersession",
      "message": "adr:spec:pageindex-tree-optimizer#body-edit-locks-a-segment-backed-node and adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit share targets and about without an explicit link",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-tree-optimizer#body-edit-locks-a-segment-backed-node",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:8c6de26b083d8a73c1ead4b15e8e7ff4159243719b707376ae33f835f96a9f9c",
      "kind": "potential-conflict",
      "message": "adr:spec:pageindex-tree-optimizer#body-edit-locks-a-segment-backed-node (requires) and adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit (forbids) govern overlapping scope",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-tree-optimizer#body-edit-locks-a-segment-backed-node",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:a8fcb5d509009adbfee94b6f81caca083d8e45ec56b558eb558ac18693a75d4b",
      "kind": "potential-conflict",
      "message": "adr:spec:pageindex-tree-optimizer#expansion-only-at-printed-headings (constrains) and adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit (forbids) govern overlapping scope",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-tree-optimizer#expansion-only-at-printed-headings",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:c1f93c1b3ebee631fb73530fc861a36ad16339a93278cad0e1b9e00909dff35c",
      "kind": "potential-conflict",
      "message": "adr:spec:pageindex-tree-optimizer#optimize-publishes-a-generation-never-a-revision (constrains) and adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit (forbids) govern overlapping scope",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-tree-optimizer#optimize-publishes-a-generation-never-a-revision",
          "revision": 1
        },
        {
          "decision_id": "adr:spec:pageindex-tree-optimizer#optimizer-never-runs-after-an-edit",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "file:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:8ed1ff34933e033998fdf974d55bce38057547d8191c18075b2e4dcdd2075846",
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
    "structural_revision": "sha256:cfc45addd689bbe708007ca56d165f966aca717f10de6ca93185c4a459a06b29",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

Resolved in the brainstorm (rev 4) and reflected in §2:

- [x] What the optimizer optimizes — *Resolved in brainstorm*: per-node ranking quality and agentic navigation cost, biased toward expansion: finer retrieval, more concepts covered, shorter summaries.
- [x] How far expansion goes — *Resolved in brainstorm*: nodes only for printed headings; concepts become `key_items` anchored to a paragraph; no synthetic nodes.
- [x] When the optimizer runs — *Resolved in brainstorm*: at import, plus an explicit command for existing trees that migrates sidecars and reports.
- [x] Legacy trees with no source file — *Resolved in brainstorm*: segments are derived from the stored node markdown (`index_segments`); a re-import is suggested for more.
- [x] What the optimizer may touch — *Resolved in brainstorm*: imported subtrees only, plus an explicit `locked` flag.
- [x] OKF identity when nodes are removed — *Resolved in brainstorm*: an alias record; the removed `concept_id` resolves to the node that absorbed it.
- [x] Default sizes and the evaluation corpus — *Resolved in brainstorm*: provisional configurable defaults in the spec, tuned by an evaluation task over a set of Bookstore books.
- [x] May `key_items` labels be abstractive — *Resolved in brainstorm*: both, each tagged `literal` or `abstractive`; literal ones are validated.
- [x] Bookstore: re-optimize on upgrade or opt in — *Resolved in brainstorm*: opt in per book; new books are optimized at import.
- [x] "No change on a second optimization" with LLM passes — *Resolved in brainstorm*: a per-node stamp (input hash and settings) so finished nodes are skipped.
- [x] What triggers a merge; is "minimum leaf" still a setting — *Resolved in brainstorm*: duplicate spans, empty leaves, and contiguous sibling leaves under the minimum when ownership and anchors are preserved. Minimum leaf is also the floor for expansion.
- [x] How a parent's disjoint own ranges are rendered — *Resolved in brainstorm*: document order, with a marker naming the child that fills each gap (FEAT-840 `render_body`, unchanged).
- [x] Generation publication for optimize — *Resolved in brainstorm*: through `pageindex-generation-publication` (FEAT-831 `WriteTransaction`).

Resolved in this spec:

- [x] FEAT-840 §8: does `update_node_content` on a segment-backed node detach it (`locked`) or re-render on the next optimize? — *Resolved here*: it locks the node (`locked_reason: "body_edited"`); see Decisions.
- [x] Ownership gaps left by `delete_node`/`add_node` under an imported parent — *Resolved here*: repaired by the next explicit optimize (re-owned by the covering ancestor, counted as `repaired_gaps`); overlaps are an error.
- [x] LLM-pass gate — *Resolved here*: a live adapter (`client is not None`), because Bookstore's `_NullAdapter` makes `has_llm` true.

Resolved by Jesus Lara on 2026-11-08:

- [x] Provisional defaults: which corpus, and who runs `optimizer_eval`? — *Resolved*: a task inside this feature, the last M6 task. It runs the harness once, deterministically (the worker sandbox reaches no model provider), over the four gitignored compliance PDFs, read from the primary checkout, plus the committed arXiv fixture. `target_leaf_tokens` takes `tuned_target(report)` when that returns a value; every other default stays provisional. The Completion Note copies its numbers from the written report and gives its sha256, or says "not run". An LLM-mode run that settles `summary_max_words`, `max_key_items` and `routing_tokens_per_child` is a ledger follow-up the task opens. The run is not delegated to a coder seat (FEAT-845 TASK-5344 precedent). See §3 M6 and AC-19.
- [x] Should `md_to_tree` stop thinning sub-50-token sections? — *Resolved by `f426e44f8d`* (on `dev` before this resolution): `md_to_tree` no longer calls `thin_tree`; short sections and the text before the first heading are kept (`test_review_regressions.py::test_markdown_keeps_short_text`). `thin_tree` remains for explicit callers. Markdown imports now hand the optimizer tiny sections, which the normalize merge rule absorbs without losing text.
- [x] Should `aliases` reach exported OKF knowledge bases? — *Resolved*: links only, in the PageIndex-owned bundle exporter. `export_okf_bundle` maps each alias to its absorber, so `pageindex://` links and `relates_to` targets naming a merged concept are rewritten to the absorber's file and `concept_id`. No `aliases` frontmatter key, and the shared `parrot.knowledge.okf.frontmatter` is unchanged. An `aliases` field with import round-trip stays a non-goal. See §3 M3 and AC-11.
- [x] Heading-like acceptance strictness — *Resolved*: the rule as written (single line, ≤ `MAX_HEADING_WORDS` words, no terminal period, not table/code/caption), and every split still passes `should_expand`. The median-paragraph check is rejected: in documents with short paragraphs (clauses, manuals, where missed headings are most common) it would reject real headings, and in ordinary prose the median paragraph is already over 20 words, so it never triggers. `TreeMetrics.llm_heading_splits` makes the false-positive rate measurable in the LLM-mode follow-up.

Open: none.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: skipped (the exploration
> document `sdd/proposals/pageindex-tree-optimizer.brainstorm.md` is `**Status**: exploration`,
> not `accepted`; `codex` is installed) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

### Specification review resolutions (2026-11-08)

The four design findings below are resolved in this draft; implementation acceptance
criteria remain unchecked. Existing source contracts were rechecked in the working tree
at HEAD `c9e2b3e92ed390c276dbd589d87601b5264a1f8f`: `generation.set_body` and `drop_body`
do not enforce optimizer locks; `toolkit._write` honors standalone `txn.noop`;
`builder.generate_doc_description` is unframed; `framing.frame_text` neutralizes framing tags.
This supplements, rather than replaces, the original §6 base-commit verification.

| Ledger finding | Resolution | Required regression evidence |
|---|---|---|
| `issue:799850fae51a` — premature completion stamps | M1 prepares inputs; M2 records successful per-pass work; toolkit validates before finalizing; matching timestamps remain unchanged | `test_first_run_executes_before_stamping`, `test_stamp_idempotence`, import/no-op integration; AC-7 |
| `issue:e0f615b28773` — protected bodies re-rendered | Mutable in-scope staging only, effective ancestor locks, complete-document ownership check and final protected-node/body_ref validation | `test_locked_semantics`, `test_same_document_subtree_staging`, `test_final_staging_validation`; AC-8 |
| `issue:0365d1296ae9` — incomplete stamp/cache dependencies | Completed passes identify execution context and consumed dependencies; missing model/disabled summaries leave work pending; parent summaries hash child outputs | `test_stamp_capability_upgrade`, `test_summaries_deferred_then_requested`, `test_stamp_summary_dependencies`, `test_retry_cache_dependencies`; AC-7 |
| `issue:8fa23e962b2d` — unframed description call | New optimizer-owned framed helper; legacy helper preserved only for opt-out/bypass callers | `test_framed_document_description`, optimized import description integration; AC-12 and AC-16 |

A fresh read-only reviewer checked the revised diff for consistency across these four fixes,
their interfaces, tests and acceptance criteria: no additional contradictions found within
that scope. This is design evidence, not runtime validation or approval of the full feature.
The earlier interrupted cross-check produced no evidence and is not counted as a pass.

Specification validation: path check, Validation Contract parsing/cache round-trip,
document consistency checks and `git diff --check` passed. The connected wiki decision
audit returned `status: pass`, complete coverage and `check: current` after its generated
sections were refreshed. The shell audit stalled on a local wiki-store read; the connected
service supplied the audit evidence instead. Logs are under
`artifacts/logs/pageindex_optimizer_spec_*` (local artifacts, not implementation test results).

The audit's four non-blocking overlap advisories do not require supersession: setting a
body-edit lock does not execute the optimizer; printed-heading and generation-publication
rules constrain an explicitly/import-triggered run without introducing an edit trigger.
These decisions are complementary. No waiver or decision-plane approval is claimed.

---

## 10. Documentation

Policy: `required`. Pages this feature delivers (frontmatter `docs.pages`):

- `wiki/knowledge/pageindex-tree-optimizer.md` (new): what the optimizer does and does not
  do; the passes in order; `OptimizerSettings` with the provisional defaults and how to
  override them (`optimizer_settings`, `optimize(target_leaf_tokens=…)`, CLI flags);
  `key_items` (`literal`/`abstractive`, anchors, where they are indexed); per-pass completion
  stamps, deferred work, dependency invalidation and idempotence; effective ancestor locks,
  scoped body staging and the body-edit rule; framed optimized-import descriptions; `aliases`
  (toolkit lookup and bundle export); the report fields;
  `optimize_on_import`; `parrot pageindex optimize` and `bookstore optimize`; the
  `optimizer_eval` harness, `tuned_target`, how the shipped `target_leaf_tokens` was set
  (report date and sha256, or "provisional" when the run did not happen; no metrics table
  that is not copied from the report) and the LLM-mode follow-up; what legacy trees get.
- `wiki/knowledge/pageindex.md`: Configuration Options gains `optimize_on_import` /
  `optimizer_settings`; API Reference links the new page.
- `wiki/knowledge/pageindex-local-mcp.md`: `pageindex_optimize` in the tool list, marked as
  working without `llm:` (deterministic passes + deterministic summaries).

`api_modules`: `parrot.knowledge.pageindex.optimizer`, `parrot.knowledge.pageindex.optimizer_llm`,
`parrot.knowledge.pageindex.optimizer_eval`.

---

## Worktree Strategy

- **Isolation**: one feature worktree for the spec (`feat-FEAT-846-pageindex-tree-optimizer`,
  from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (imports `OptimizePlan`, `KeyItem`, `split_at`, `pass_input`, `pass_cache_key`, `is_stamped`).
  - M3 has no edge to M1/M2 (reads dict fields only); it can run concurrently with them.
  - M4 → M1, M2, M3 (calls the planner and the passes; relies on the schema fields and the
    live-adapter gate).
  - M5 → M4 (`optimize_book` and both CLIs call `PageIndexToolkit.optimize`).
  - M6 → M4 (the harness imports PDFs through the toolkit and calls `optimize`). The M6
    tuning task edits the `target_leaf_tokens` default in `optimizer.py`, so it runs after
    every M1 task and is executed by the orchestrator or on the host, never by a coder seat.
  - M7 → all (after the tuning task, so the page states the shipped defaults).
- **Shared files**: `toolkit.py` is modified only by M4, but M4 will be several tasks
  (constructor + import hook; `optimize` tool; lock semantics) — serialize them.
  `hybrid_search.py`, `embedding_store.py` and `okf/bundle.py` belong to M3 only.
  `library.py`/`cli.py` to M5.
- **Exclusive resources**: none (no native build, no lockfile, no migration). The tuning run
  reads the primary checkout's `corpus/compliance_soc2_hipaa/raw/` read-only.
- **Cross-feature dependencies**: none pending — FEAT-831, 840, 842, 843 and 845 are all on
  `dev` at `09d3377826`.
