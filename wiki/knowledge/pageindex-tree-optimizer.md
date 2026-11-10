---
title: PageIndex Tree Optimizer
summary: How PageIndex reshapes an imported tree so leaves fit a token target (merge tiny sections, split oversized leaves at printed headings, add anchored key_items and capped summaries), with dry runs by default, per-pass completion stamps, lock protection and the optimizer_eval harness.
---

# PageIndex Tree Optimizer

## Purpose

A tree built from a PDF or a markdown file often has the wrong shape for retrieval: one leaf holds a whole chapter
while its siblings hold a single short paragraph each. The optimizer reshapes the nodes of **imported documents**
(nodes that carry a `doc_id` and a `revision` in the [segment store](pageindex-segment-store.md)) so that the tree is
cheaper to route and to read:

- it merges duplicate and undersized leaves into a neighbour, and folds empty leaves into their parent;
- it splits leaves over `target_leaf_tokens` at the printed headings they contain — or, when a leaf has none, at
  standalone bold or upper-case title lines;
- with a model, it can split at heading-like printed lines the layout missed and attach `key_items` to leaves that
  stay large;
- it writes capped summaries bottom-up (deterministic without a model).

What it does **not** do:

- It never invents a node title. A new node is titled from a heading segment of the revision, or from a printed line
  the model proposed and that passes the heading-like check. Concepts that are not headings become `key_items`.
- It never changes the source text. Revision files are read-only to it; `optimize` never writes a revision, so every
  citation validated before an optimization (same `doc_id`/`revision`) still validates after it.
- It never touches nodes without a `doc_id`, locked nodes or their descendants (see [Locks](#locks-and-the-body-edit-rule)).
- No edit tool calls it: `add_node`, `delete_node`, `update_node`, `update_node_content`, `tag_node` and
  `rename_tree` leave the tree shape alone.

Tokens are always counted over the segments a node **owns** (its `owned` ranges), never estimated from page counts.

## Public API

- `OptimizerSettings` — the tuning knobs
- `OptimizeReport` — what `optimize` returns (as a dict)
- `KeyItem` — an anchored label on a node
- `plan_deterministic` — the model-free planner
- `validate_candidate` — ownership, anchor and protected-node checks
- `reconcile_key_items` — re-homes or drops key items whose anchor left their node
- `is_heading_text` — the "reads like a printed heading" rule
- `pseudo_heading_segments` — bold/upper-case title lines used when a leaf has no heading segment
- `window_reads` — splits a node's segments into windows under `LLM_INPUT_BUDGET_TOKENS`
- `run_llm_passes` — heading, key-item and summary passes
- `describe_document` — framed document description on optimized imports
- `evaluate_corpus` — the evaluation harness
- `tuned_target` — clamps the harness suggestion to a safe range
- [`PageIndexToolkit`](ref:parrot.knowledge.pageindex.toolkit) — `optimize()`, `optimize_on_import`, `optimizer_settings`

## The passes, in order

`PageIndexToolkit.optimize()` plans on a deep copy of the tree. For every imported document root in scope:

1. **Repair ownership.** `validate_ownership` runs over the document's nodes. An **overlap** aborts that document and
   is reported in `errors`. A **gap** (segments no node owns, for example after a deleted child) is re-owned by the
   deepest, narrowest unlocked node whose span covers it, and counted in `repaired_gaps`.
2. **Normalize.** Bottom-up, per sibling list: an empty leaf (no children, no owned ranges) is folded into its
   **parent** (`empty`) — its `concept_id` becomes a parent alias, so a published tree with a blank "Preface" or
   title-page node still validates; a published empty leaf without a `concept_id` is kept, because removing it could
   never validate. A leaf whose `span` equals a later sibling's absorbs it (`duplicate_span`); a leaf under
   `min_leaf_tokens` is merged into the previous or next sibling leaf when their owned ranges are contiguous
   (`under_minimum`). A non-contiguous small leaf stays. The absorbing node keeps the absorbed `concept_id` in
   `aliases` and gains a `literal` key item labelled with the absorbed title, anchored at its first owned segment; its
   `span` widens over the absorbed owned ranges, so step 3 keeps them (and that key item) with it. Nothing is dropped
   from the text.
3. **Assign ownership.** Parent spans widen to cover their children; a parent owns the residual text before, between
   and after its children (`render_body` shows `<!-- continues in: <title> -->` markers where a child takes over).
4. **Expand at headings.** A leaf over `target_leaf_tokens` with heading segments inside (excluding a first heading
   that repeats its own title) is split at its **shallowest** heading level, recursively, up to `max_depth`. A split
   is taken only when the cost model allows it: every piece has at least `min_leaf_tokens`, and the routing cost of
   the new children (title tokens plus summary tokens, or `routing_tokens_per_child` when a piece has no summary yet)
   plus the largest piece is smaller than the leaf it replaces.
   A leaf with **no** usable heading segment falls back to pseudo-headings (`pseudo_heading_segments`): single-line
   paragraphs fully wrapped in `**…**` / `__…__` (split runs such as `**P****ROLOGO**` included) or written in upper
   case, whose cleaned title passes `is_heading_text`. A title repeated more than `PSEUDO_HEADING_MAX_REPEATS` (2)
   times in the leaf is a running header or footer and is ignored, and split points that would leave a piece under
   `min_leaf_tokens` are dropped first, so one stray short line cannot veto the split. This is how ebook and markdown
   imports, whose chapter titles arrive as bold paragraphs rather than `#` headings, are expanded without a model;
   segment kinds are not changed (the segmenter still types those lines `paragraph`).
   Repeat counts are keyed by `running_key` (casefold, digit runs collapsed to `#`), so a running footer that differs
   only by its page number (`CHAPTER THREE PAGE 19`, `APPENDIX C PAGE 428`) counts as one repeated title and is
   ignored once it occurs more than `PSEUDO_HEADING_MAX_REPEATS` times.
   That count only sees one leaf, and a two- or three-page piece holds its footer once or twice, so a paged revision
   also has **document running lines** (FEAT-859, `issue:5a605ae51f61`): `document_running_keys(revision)` returns
   the `running_key` of every paragraph title that sits on more than `PSEUDO_HEADING_MAX_REPEATS` distinct pages,
   never twice on one page, and covers at least `RUNNING_LINE_MIN_DENSITY` (0.8) of the page range it spans.
   `pseudo_heading_segments` drops those titles in any leaf. `plan_deterministic` computes the set once per document
   (a document has one root per top-level section) and passes it to `expand_at_headings`, which hands it down the
   recursion (`running_keys`; called without it, each function computes it itself). A page footer covers its whole range once per page; a real
   heading repeated through a book does not (Kant's `PRIMERA SECCIÓN` covers 0.03 of its range, numbered chapters
   0.30), and reference labels such as `[SP 800-39]` stack on one page, so both stay with the per-leaf rule. An
   unpaged revision has no document running lines. Pieces created from a paged revision (a PDF)
   carry `start_index` (page of the first owned segment) and `end_index` (page of the last owned segment); pieces
   of an unpaged revision (ebook, markdown) carry neither key. Every split — layout or LLM —
   moves the split leaf's key items onto the piece that now owns their anchor.
   A leaf with neither a heading nor a pseudo-heading split point can still be one long table (FEAT-861,
   `issue:f31b01d845b0`): table rows are `table` segments, and the only repeated line inside, the page footer, is
   ignored. When `table` segments hold at least `TABLE_SPLIT_MIN_SHARE` (0.5) of the leaf's owned tokens and sit on at
   least two pages, `table_page_splits` splits the leaf at page boundaries: the first `table` segment, then the first
   owned segment of each later page. Pages are packed **from the last page backward** up to `target_leaf_tokens`, so a
   short trailing page (often just the next page's running header) joins the piece before it instead of pushing a
   piece over the target or vetoing the split, and the points then go through the same `min_leaf_tokens` coalescing.
   The text before the table (its title, a lead-in paragraph) stays with the parent. Each piece is titled after the
   leaf plus its page range — `TABLE C-17: SYSTEM AND SERVICES ACQUISITION FAMILY (page 481)`, `… (pages 484-485)`,
   PDF page indexes like `start_index` / `end_index` — passed to `split_at(..., titles=…)`; the expand action's source
   stays `"layout"`. A table on a single page and a single `table` segment larger than the target are not split.
5. **LLM heading pass** (live model and `llm_passes` only). Only the leaf's heading-like segments are sent, framed
   and windowed under `LLM_INPUT_BUDGET_TOKENS` (see [Framing](#framing)); a leaf without any makes no call. The model
   returns segment numbers of printed sub-headings. A proposal is accepted only when it names a segment the leaf owns
   and that segment is heading-like: one line, not a table/code/caption segment, and its cleaned text passes
   `is_heading_text` — at most `MAX_HEADING_WORDS` words, no trailing `.`, `;`, `:` or `,`, no trailing lower-case
   conjunction (`and`, `or`, `nor`, `y`, `e`, `o`, `u`, `ni`), no list-marker prefix (`(a) `, `a) `, `(iv) `, `- `,
   `• `, `* `). `1. Introduction` and `Appendix E` stay valid; a sentence fragment ending in `; and` does not.
   Accepted seqs go through the same cost model (`source: "llm"`). Rejections count in `rejected_proposals`.
6. **Key-items pass** (live model only). Leaves still over `target_leaf_tokens` get up to `max_key_items` key items.
   An oversized leaf is windowed: each window is asked for its share (`ceil(max_key_items / windows)`) and at most
   `max_key_items` are accepted in total.
7. **Re-home key items.** `reconcile_key_items` moves any key item whose anchor left its node's owned ranges (after a
   split, or after the toolkit restores the ranges a merge absorbed) to the node that now owns the anchor, counted in
   `key_items_rehomed`. When that node is outside the optimizer's scope the item is dropped and counted in
   `rejected_proposals`. It runs at the end of deterministic planning and again before the summary pass, so summary
   digests see the final key items. One stale anchor therefore no longer discards the whole candidate.
8. **Summary pass.** Depth by depth, deepest first, so a parent is composed after its children (see
   [Summaries](#summaries)).
9. **Validate.** `validate_candidate` checks that the owned ranges of every document form a partition of the revision,
   that every key item's anchor is inside its node's owned ranges, and that no protected node was removed or changed.
   A candidate with errors publishes nothing; the report carries `errors`.

## Configuration & Parameters

### `OptimizerSettings`

| Field | Default | Meaning |
|---|---|---|
| `target_leaf_tokens` | `1500` | A leaf above this many owned tokens is a split candidate (and a key-item candidate). |
| `min_leaf_tokens` | `200` | A leaf below this merges into a contiguous sibling leaf; no split may leave a piece below it. |
| `inline_summary_tokens` | `120` | A leaf at or below this uses its own text as summary, with no LLM call. |
| `summary_max_words` | `60` | Summary cap; output is trimmed to 1.2 × this many words. |
| `max_key_items` | `8` | Cap on key items accepted per node from one proposal. |
| `routing_tokens_per_child` | `48` | Routing cost assumed for a new child that has no summary yet. |
| `max_depth` | `8` | Depth limit for recursive heading expansion. |
| `llm_passes` | `True` | Run the model-backed passes when a live adapter exists. |

The defaults were **confirmed on 2026-11-09** by the host evaluation run (deterministic and LLM mode, see
[Evaluation](#evaluation-optimizer_eval)): `target_leaf_tokens` stays at 1500 because the harness suggestion moves
with the corpus composition (1100 on the compliance corpus alone, 2100 with three Spanish books added, 2200 in LLM
mode), so no single number is better supported than the shipped one. Ledger issues `issue:7111d74a3066` and
`issue:336eef8010a1` were closed by that run.

`settings_hash()` returns a 16-character digest of the settings; it is part of every completion stamp.

### Overriding the settings

- **Per toolkit**: `PageIndexToolkit(..., optimizer_settings=OptimizerSettings(...))` or a plain dict
  (`optimizer_settings={"target_leaf_tokens": 1200}`); missing keys keep their defaults.
- **Per call**: `await toolkit.optimize(tree, target_leaf_tokens=1200, min_leaf_tokens=150, llm_passes=False)`
  overrides those fields for that call only.
- **CLI**: `parrot pageindex optimize --target-tokens 1200`.

### `optimize_on_import`

`PageIndexToolkit(optimize_on_import=True)` is the default. With it, `import_pdf`, `insert_markdown` and
`insert_ebook` run the optimizer inside the import transaction, after the document's revision is attached:

- The builder is told not to write per-node summaries (and, for `import_pdf`, not to write the document description);
  the optimizer's summary pass writes them instead. `import_pdf` passes its `with_summaries` flag through;
  `insert_markdown` and `insert_ebook` always run the summary pass, which is deterministic without a model.
- Sections under `min_leaf_tokens` (200 by default) that are contiguous with a sibling leaf merge into it, so a
  markdown import with many short sections yields fewer, larger leaves; each merged title survives as a `literal`
  key item and its `concept_id` as an alias.
- The import fails (nothing is published) if the optimized candidate does not validate.

`optimize_on_import=False` reproduces the pre-optimizer import output byte-for-byte.

### `optimize()`

```python
await toolkit.optimize(
    tree_name,
    node_id=None,              # restrict to the subtree under this node
    apply=False,               # dry run by default
    llm_passes=True,
    target_leaf_tokens=None,
    min_leaf_tokens=None,
) -> dict                      # OptimizeReport.model_dump()
```

- **Dry run** (`apply=False`): plans on a copy, opens no transaction, publishes nothing. The report shows what an
  apply would do.
- **Apply** (`apply=True`): runs inside the toolkit's write transaction. If another writer published in the
  meantime the plan is rebuilt from the fresh snapshot (cached LLM answers are reused only for identical pass keys).
  Node ids are reindexed, missing `concept_id`s derived, bodies re-rendered for the touched nodes, and a new
  generation is published **only when the candidate differs** from the current tree; otherwise the transaction is a
  no-op and `generation_after == generation_before`.
- Unknown tree or node raises `KeyError`.
- `pageindex_optimize` is the same method exposed as a tool. It is not in `llm_dependent_tools`, so a local MCP
  server without `llm:` serves it (see [PageIndex Local MCP Toolkit](pageindex-local-mcp.md)).

### The report

`OptimizeReport` fields: `tree_name`, `node_id`, `dry_run`, `generation_before`, `generation_after`, `documents`
(doc ids in scope), `nodes_before`, `nodes_after`, `leaves_over_target_before`, `leaves_over_target_after`, `merged`
(list of `MergeAction`: absorbed/into concept id and title, `reason` one of `duplicate_span`, `empty`,
`under_minimum`), `expanded` (list of `ExpandAction`: parent title and concept id, piece titles, `source` `layout` or
`llm`), `key_items_added`, `summaries_written`, `repaired_gaps`, `skipped_locked`, `skipped_stamped`,
`rejected_proposals` (rejected model proposals and dropped key items), `key_items_rehomed`, `llm_passes` (`"ran"`,
`"skipped (no model)"` or `"skipped (disabled)"`), `llm_calls_estimated`, `llm_calls_made`, `errors`, and the
effective `settings`.

`llm_calls_made` counts adapter calls actually issued: every window is one call, and results served from the retry
cache (for example an apply that reuses its dry run) are not counted. `llm_calls_estimated` counts the windows each
pass is expected to send on the current candidate.

## `key_items`

A key item is `{label, kind, seq, page, ordinal}`:

- `kind: "literal"` — the label must occur in the anchor segment's text (case- and whitespace-normalized). Merge
  key items (the absorbed title) are literal.
- `kind: "abstractive"` — a model-written label; it still needs a valid anchor (`seq` inside the node's owned
  ranges).

Proposals naming a segment the node does not own, or literal labels absent from their anchor, are rejected and
counted. Labels are indexed everywhere a node is matched:

- the BM25 corpus text (`title summary labels body`);
- the embedded text **and** the embedding cache key (`content_key(..., extra=labels)`) — the key is unchanged for a
  node without key items, so only nodes that gained labels are re-embedded;
- search results (`key_items` on each hit) and `outline` entries.

## Completion stamps, deferred work and idempotence

Each node keeps an `optimizer` record: `passes` maps `headings`, `key_items` and `summary` to a `PassStamp`
(`version`, `input`, `settings`, `execution`, `at`), and `summary` records the summary origin (`inline`, `llm`,
`composed`, `none`).

- A pass is skipped when a stamp matches on **all four** of optimizer version, settings hash, input digest and
  execution digest. The execution digest covers the mode (`live` or `deterministic`), the prompt version and, for a
  live adapter, the client class and model name — never credentials.
- Deterministic planning writes no stamps. Stamps are recorded only for passes that actually ran and succeeded, and
  are finalized after the passes; a record whose input changed meanwhile is dropped, and an already-matching record
  keeps its original timestamp.
- **Deferred work**: a pass that was unavailable (no model), disabled (`llm_passes=False`), failed, or not requested
  (`with_summaries=False`) is not marked complete, so a later run with a model or with summaries enabled does it.
  A summary written without a model carries a `deterministic` execution digest; once a model is configured the
  summary pass runs again live for every node above `inline_summary_tokens` (inline leaf summaries stay as they are).
- **Dependency invalidation**: the summary input of a node includes its own `key_items` and each child's title,
  summary, key items and span. A changed child summary or key item therefore invalidates the parent summary (and its
  retry-cache key) even when titles, spans and owned ranges are identical.
- **Idempotence**: a second `optimize(apply=True)` with the same inputs, settings and execution context publishes no
  new generation, makes no LLM calls and reports zero merges, expansions, key items and summaries.
- Older `optimizer` records that are not in this per-pass form never match, so their passes run once.

## Locks and the body-edit rule

- A node with `locked: true` and **all its descendants** are out of scope. A `node_id` under a locked ancestor
  selects nothing — ancestor locks above a selected subtree apply too. Skipped nodes count in `skipped_locked`.
- `update_node(..., locked=True)` sets `locked` with `locked_reason: "manual"`; `locked=False` removes both.
- `update_node_content` on a segment-backed node (one with a `doc_id`) sets `locked: true` and
  `locked_reason: "body_edited"`. Its body is now the edited text; its owned ranges still describe the source, so
  `read_segments` still reads the revision, but `optimize` will not reshape it.
- A subtree optimize (`node_id=...`) leaves every node outside the subtree unchanged except `node_id`
  renumbering — same bodies, `body_ref` and stamps. Body staging only re-renders nodes the optimizer owns in this
  run; protected nodes are restored from the base tree, and the final validation after staging and stamp
  finalization rejects any change to them without publishing.

## Summaries

- A leaf at or below `inline_summary_tokens` uses its own owned text (trimmed) — no LLM call (`summary: "inline"`).
- A larger leaf: with a live model, one framed call capped at `summary_max_words` (`"llm"`) — or, when the leaf
  exceeds `LLM_INPUT_BUDGET_TOKENS`, one call per window followed by one reduce call over the framed partial
  summaries; without a model, its own text trimmed to the cap.
- A parent is composed after its children: with a model, from the child summaries and its key items (each clipped
  to a quarter of `LLM_INPUT_BUDGET_TOKENS`) and the first window of its own framed text that fits the remaining
  budget; without one, its own text plus `Subsections cover: <child titles>` (`"composed"`).
- Every summary is trimmed to 1.2 × `summary_max_words` words.
- With no adapter, or an adapter without a client (Bookstore's `_NullAdapter`), no call is made and the deterministic
  summaries are used.

## Framing

Every optimizer prompt — headings, key items, leaf summaries, parent composition — wraps document-derived text in
`<document_text …>` frames (`frame_segments`) and passes `DATA_FRAMING_INSTRUCTION` as the system prompt;
instructions stay outside the frame and the framing helpers neutralize embedded closing tags.

**Bounded prompts.** No optimizer call frames more than `LLM_INPUT_BUDGET_TOKENS` (20 000) tokens of document text.
`window_reads` splits a node's segments, in order, into windows under that budget (each segment costs its stored
token count plus a small frame allowance); a single segment over the budget forms its own window, clipped and marked
`truncated`. The heading pass frames only heading-like candidates, the key-items pass and leaf summaries make one call
per window (summaries add a reduce call whose partial summaries are framed too), and parent composition clips its
inputs. A 157k-token leaf therefore fits a 200k-context model instead of producing a ~300k-token request that every
attempt rejects. The budget is a module constant in `optimizer_llm`, deliberately not an `OptimizerSettings` field and
not tied to the prompt version, so changing it does not invalidate completion stamps.

On an optimized `import_pdf`, the document description (`with_doc_description=True` and a live adapter) comes from
`describe_document`, which frames the cleaned structure with `frame_text`; the legacy unframed description helper is
not used on that path. A model proposal that names a segment it was not shown is rejected, including a cached
proposal replayed after a retry.

## Aliases

When normalization merges node B into node A, B's `concept_id` is added to A's `aliases`. An empty leaf folded into
its parent leaves its `concept_id` on the parent the same way.

- **Toolkit lookup**: `OKFToolkit.get_concept` and `cite` resolve an alias to the absorbing node. A live
  `concept_id` always wins over an equal alias.
- **Bundle export**: links and `relates_to` targets naming an alias are rewritten to the absorbing node's file and
  `concept_id`. No `aliases` key is written to the exported frontmatter.

## CLIs

### `parrot pageindex optimize`

```bash
parrot pageindex optimize <tree> --storage-dir <dir> [--node <node_id>] [--apply] \
    [--llm provider:model] [--target-tokens N] [--json]
```

Dry run unless `--apply`. Without `--llm` no model is configured, so the report says
`llm: skipped (no model)` and only the deterministic passes and summaries run. `--target-tokens` overrides
`target_leaf_tokens`; `--json` prints the full report.

### `bookstore optimize`

```bash
bookstore optimize <book_id> [--global] [--apply] [--no-llm] [--llm provider:model] [--json]
```

Calls `Bookstore.optimize_book`. Without `--apply` the card and the tree are unchanged. With `--apply` and no errors
it republishes the tree and rewrites the card's `toc`, `toc_digest`, `chapter_count` and `page_count` from the
optimized tree. `--no-llm` skips the model-backed passes; otherwise they follow whether the bookstore has an LLM.
`bookstore add` of a PDF already yields an optimized tree, because the Bookstore's toolkit keeps
`optimize_on_import=True`, and its card TOC is derived from that tree.

## Evaluation (`optimizer_eval`)

```bash
python -m parrot.knowledge.pageindex.optimizer_eval <pdf|dir>... \
    [--target-leaf-tokens N] [--min-leaf-tokens N] [--llm provider:model] [--out DIR]
```

Each PDF is imported into a temporary storage directory with `optimize_on_import=False` and
`structure_mode="layout"`, then optimized with `optimize(apply=True)` (LLM passes only when `--llm` is given). The JSON
report (`<out>/optimizer_eval-<timestamp>.json`, default `artifacts/logs/optimizer_eval/`) holds, per PDF, the file
stem and numbers only — never a node title: `pages`, `nodes_before/after`, `leaves_before/after`,
`leaf_tokens_p50/p90/max`, `leaves_over_target_before/after`, `key_items`, `summary_words_mean`, `llm_calls`,
`seconds`, `llm_heading_splits`.

`suggested_target_leaf_tokens` is the 75th percentile of the owned tokens of all **layout-built** (pre-optimizer)
leaves, rounded to 100, and is `None` with fewer than three PDFs. The command prints `tuned_target`, which returns the
suggestion only when it lies in `[2 × min_leaf_tokens, 2 × target_leaf_tokens]` of the current defaults, else `None`.

**How the shipped `target_leaf_tokens` was set.** Host run of 2026-11-09 on `dev @ 09c95b1646`, settings
`target_leaf_tokens=1500`, `min_leaf_tokens=200`. Inputs: the four compliance PDFs of `corpus/compliance_soc2_hipaa/raw/`,
the arXiv fixture, and three public-domain Spanish PDFs from the local Bookstore library (Analectas, Kant's *Crítica*,
Marco Aurelio's *Meditaciones*). Reports live under `artifacts/logs/optimizer_eval/` (git-ignored); their sha256:

| Report | sha256 |
|---|---|
| `deterministic/optimizer_eval-20261109T121801073795Z.json` (8 PDFs) | `fe02a470e2101f067a99475a6ff5851e587f1b737a70266df82666193a5890e2` |
| `deterministic_corpus_only/optimizer_eval-20261109T122507348707Z.json` (corpus + arXiv) | `b7affece84d877fe28cfbe3d8ce1a428d6d5c4e296de09b47a77484b4b824e43` |
| `llm_small/optimizer_eval-20261109T122255854142Z.json` (`google:gemini-3.5-flash-lite`) | `680cdf81a824923dd7efccbfa2061434eef880068b12572388a7435a75ade3d9` |
| `llm_800_53/optimizer_eval-20261109T122706159755Z.json` (`google:gemini-3.5-flash-lite`) | `7651c039e41d02c793fb80f4f9aff8050d576c4ecb9790663639c8520a777660` |

Deterministic run (no model):

| PDF | Pages | Nodes before → after | Leaves after | Leaf tokens p50 / p90 / max | Leaves over target after | Key items | Seconds |
|---|---:|---|---:|---|---:|---:|---:|
| aicpa_tsc_2017 | 75 | 12 → 12 | 8 | 1560 / 11245 / 27651 | 4 | 0 | 20.8 |
| hipaa_45cfr164_2022 | 61 | 129 → 129 | 68 | 896 / 968 / 1126 | 0 | 0 | 14.5 |
| nist_800_53_r5 | 492 | 118 → 106 | 69 | 1214 / 8271 / 28862 | 28 | 12 | 149.4 |
| nist_csf_2_0 | 32 | 23 → 23 | 20 | 577 / 1396 / 4338 | 2 | 0 | 4.2 |
| arxiv_2408_09869 | 9 | 18 → 14 | 11 | 382 / 1730 / 5398 | 2 | 4 | 9.9 |
| Analectas (Confucio) | 150 | 45 → 45 | 39 | 2086 / 3179 / 9744 | 30 | 0 | 15.5 |
| Crítica de la razón pura (Kant) | 206 | 5 → 5 | 3 | 6 / 123592 / 154488 | 1 | 0 | 27.6 |
| Meditaciones (Marco Aurelio) | 105 | 18 → 17 | 12 | 5622 / 6002 / 6022 | 10 | 0 | 9.4 |

`suggested_target_leaf_tokens`: **2100** over the eight PDFs, **1100** over the corpus plus arXiv only. The suggestion
is a pooled p75, so a dozen long leaves from one book double it; that instability (ledger `issue:adae36a70919`) is
why the default was kept at 1500. Two documents expose optimizer bugs rather than tuning signals: Kant has no
typographic headings and stays one 154k-token leaf (`issue:ab5235978ad7`), and the Marco Aurelio `apply` is rejected
with `protected node … was removed` (`issue:33ad15e686e9`).

LLM mode (`--llm google:gemini-3.5-flash-lite`):

| PDF | Nodes before → after | Leaves after | Leaf tokens p50 / p90 / max | Over target after | Key items | Summary words (mean) | LLM calls | Heading splits | Seconds |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| nist_csf_2_0 | 23 → 23 | 20 | 577 / 1396 / 4338 | 2 | 11 | 49.7 | 39 | 0 | 34.0 |
| arxiv_2408_09869 | 18 → 15 | 11 | 382 / 1730 / 2361 | 2 | 19 | 45.4 | 26 | 1 | 32.5 |
| Analectas (Confucio) | 45 → 53 | 46 | 1960 / 2908 / 4300 | 31 | 211 | 52.4 | 122 | 1 | 87.1 |
| nist_800_53_r5 | 118 → 132 | 81 | 991 / 7661 / 28862 | 28 | 0 | 0.0 | 221 | 8 | 246.9 |

`suggested_target_leaf_tokens` in LLM mode: 2200. Summaries land under the 60-word cap (45–52 words mean) and the
heading pass splits only at printed headings (Analectas: the 14-page introduction became 8 titled sections). The
800-53 row is a rejected candidate: two `key_items` whose anchors left their node's owned ranges failed
`validate_candidate`, so none of the 221 calls was published (`issue:66f376157327`). The LLM-dependent defaults
(`inline_summary_tokens`, `summary_max_words`, `max_key_items`) were kept.

## Usage Examples

```python
from parrot.knowledge.pageindex import PageIndexToolkit
from parrot.knowledge.pageindex.optimizer import OptimizerSettings

toolkit = PageIndexToolkit(
    storage_dir="/data/pageindex",
    optimizer_settings=OptimizerSettings(target_leaf_tokens=1200),
)

# Preview: nothing is published.
report = await toolkit.optimize("handbook")
print(report["leaves_over_target_before"], report["leaves_over_target_after"], len(report["merged"]))

# Publish, deterministic passes only.
report = await toolkit.optimize("handbook", apply=True, llm_passes=False)
assert not report["errors"]

# Optimize one chapter.
await toolkit.optimize("handbook", node_id="0007", apply=True)

# Keep the old import shape.
legacy = PageIndexToolkit(storage_dir="/data/pageindex", optimize_on_import=False)
```

## Gotchas

- **Legacy trees**: nodes without `doc_id`/`revision` (hand-added nodes, imports from before the segment store) and
  nodes whose revision file is missing are out of scope. `optimize` leaves them untouched and reports no documents
  for them; re-import the source to make it optimizable.
- A leaf with no heading segments inside cannot be split deterministically; without a model it stays over target and
  shows in `leaves_over_target_after`.
- The key-items pass only runs with a live model, and only on leaves that are still over `target_leaf_tokens`.
- `parrot pageindex optimize` has no `--min-leaf-tokens` flag; use `optimizer_settings` or `optimize(min_leaf_tokens=…)`.
- Editing a segment-backed node's body locks it. Unlocking it with `update_node(..., locked=False)` puts it back in
  the optimizer's scope, where its body is treated as a view of its owned segments again.
- An overlap in the existing ownership aborts that document; the report lists it in `errors` and nothing is published.

## Related

- [PageIndex](pageindex.md) — trees, builders and configuration options
- [PageIndex Segment Store](pageindex-segment-store.md) — revisions, owned ranges, `read_segments`, citations
- [PageIndex Generation Publication](pageindex-generation-publication.md) — transactions and generations `optimize` publishes into
- [PageIndex Layout Structure Builder](pageindex-layout-structure.md) — where the heading segments come from
- [PageIndex Local MCP Toolkit](pageindex-local-mcp.md) — `pageindex_optimize` without `llm:`
- [Bookstore Codex](bookstore-codex.md) — `bookstore add` / `bookstore optimize`
