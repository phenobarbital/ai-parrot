---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — core only: parrot.knowledge.pageindex (optimizer, optimizer_llm)
tags: [pageindex, tree-optimizer, ledger-fix, bookstore]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-tree-optimizer.md]
  api_modules: [parrot.knowledge.pageindex.optimizer, parrot.knowledge.pageindex.optimizer_llm]
---

# Feature Specification: PageIndex Optimizer Fixes

**Feature ID**: FEAT-853
**Date**: 2026-11-09
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> Ledger-driven follow-up to FEAT-846 (`pageindex-tree-optimizer`, closed 2026-11-09). Drains the
> `/sdd-fix` group `fixgroup:9b38cab45056` — four issues found by the 2026-11-09 host evaluation
> runs (`optimizer_eval`, `bookstore optimize`, `make index-books`). No brainstorm or proposal:
> the issue bodies are the requirements, re-verified against `dev` at `8e1882833c`.

---

## 1. Motivation & Business Requirements

### Problem Statement

The FEAT-846 optimizer works on the test fixtures but fails, or does nothing, on four common
real-document shapes. Three of the four failures reject the whole candidate, so nothing is
published and every LLM result is thrown away:

1. **Empty leaf removed without identity** (`issue:33ad15e686e9`, major). `normalize` drops an
   empty leaf (`optimizer.py:323`, no children and no owned ranges) without recording its
   `concept_id` anywhere. `validate_candidate` then reports `protected node <id> was removed`
   (`optimizer.py:678`). A published tree with a blank "Preface"/title-page node — *Las
   Meditaciones* — can never be re-optimized. The import succeeds only because nothing is
   protected inside the import transaction.
2. **One stale key-item anchor rejects the candidate** (`issue:66f376157327`, major). Anchors are
   validated when they are proposed (`optimizer_llm.py:190`), but ownership changes afterwards:
   `split_at` (`optimizer.py:432`) turns a leaf into a parent whose `owned` ranges shrink to the
   text before its first heading, while the leaf's existing `key_items` stay on it. `_absorb`
   (`optimizer.py:277`) merges `owned` ranges but never widens the absorber's `span`, so the next
   `assign_ownership` (`optimizer.py:369`) rebuilds the leaf's `owned` from its `span` and hands
   the absorbed range, with its title key item, to the parent. `validate_candidate`
   (`optimizer.py:660`) fails on the first such anchor. On NIST 800-53 this discarded 209 LLM
   calls, 180 key items and 117 summaries. The offending node's title, a sentence fragment
   ending in `; and`, was accepted by `heading_like` (`optimizer_llm.py:108`).
3. **Unbounded LLM prompts** (`issue:ab5235978ad7`, major). `propose_headings`,
   `propose_key_items`, `summarize_leaf` and `compose_parent` frame every owned segment of a node
   in one prompt (`reads_for`, `optimizer_llm.py:77`). The Kant PDF imports as one 157k-token
   leaf. The heading request (~299k tokens) is rejected 3/3, so the optimizer can never split the
   books the LLM pass exists for. Any pass error lands in `report.errors`, which fails the apply
   (`toolkit.py:1587`), so the summary pass on the same leaf fails it too.
4. **Ebooks never expand** (`issue:0a693a57b138`, minor). Ebook and markdown imports carry
   chapter titles as bold or upper-case paragraphs (`**P****ROLOGO**`, `SEGUNDA PARTE`), not `#`
   headings. `split_blocks` (`segments.py:150`) types them `paragraph`, and `expand_at_headings`
   (`optimizer.py:487`) splits only at `kind == "heading"`. *Don Quijote* stays one 282k-token
   leaf.

### Goals
- An explicit `optimize(apply=True)` on a published tree with empty leaves validates and
  publishes; the empty leaf's `concept_id` survives as an alias.
- No ownership change (split, merge, ownership recomputation) can leave a key item anchored
  outside its node at validation time. A misplaced anchor is moved to the node that owns it, or
  dropped and counted, never fatal. `validate_candidate` stays fail-closed as the backstop.
- `heading_like` rejects sentence fragments and list items.
- Every optimizer LLM call frames a bounded amount of document text
  (`LLM_INPUT_BUDGET_TOKENS`), so a leaf of any size can be processed by a 200k-context model.
- An oversized leaf with no heading segments, but standalone bold or upper-case title lines,
  is expanded deterministically at those lines, with no LLM and no re-import.

### Non-Goals (explicitly out of scope)
- Changing segmentation: `split_blocks`, `segment_pages`, segment kinds and revision ids stay
  as they are (see Decisions `pseudo-headings-in-optimizer`). PDF page segmentation must not
  change.
- Emitting `#` headings from the ebook loaders (`parrot_loaders` epub/mobi → markdown). That
  would need a re-import of every ebook. It is an alternative the issue offered, rejected in §7.
- Changing `PROMPT_VERSION` or `OptimizerSettings` fields. Either one changes the execution or
  settings digest and invalidates every persisted completion stamp (see §7).
- Tuning runs (`issue:7111d74a3066`, `issue:336eef8010a1`) and the toolkit's
  `_restore_merged_ownership` (`toolkit.py:112`). The toolkit is not modified.
- `OptimizeReport.nodes_after` / `leaves_over_target_after` accuracy (separate deferred
  finding of TASK-5375).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:a66c440b731d031fc35828435c8db8adbfb774acf751c1d3f45788ceebd5c38f evaluation_digest=sha256:f4f7314911fa5838fe2f25f55c7ff08c6b66b108e18087018dc892809316e999 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Four independent repairs inside the two optimizer modules. No new module, no new dependency,
and no change to the toolkit, the segment store or the segmenter.

**A. Identity-preserving normalization** (`optimizer.py`).
- `normalize` gains a keyword `parent`. An empty leaf is absorbed into its **parent** through
  `_absorb(..., reason="empty")`; the `"empty"` reason already exists in `MergeAction`
  (`optimizer.py:81`) and was never used. The leaf's `concept_id` becomes a parent alias, so
  `validate_candidate`'s alias rule (`optimizer.py:668`) accepts the removal.
- The parent, not a sibling, is the absorber because its span already covers the child's.
  The toolkit's `_restore_merged_ownership` widens a node's span by its aliases' original spans,
  so for the parent that is a no-op. A sibling absorber could be widened across a neighbour and
  create an ownership overlap.
- A published empty leaf (`node_id` set) without a `concept_id` is kept, because its removal
  could never validate. With no `parent` (direct callers, unpublished input) the legacy
  behaviour stays: removed, unrecorded.
- `plan_deterministic` passes `parent=root`; the recursion passes `parent=child`.

**B. Anchor integrity** (`optimizer.py`, wired in `optimizer_llm.py`).
- *Root causes.* `_absorb` widens the absorber's `span` to the extent of the absorbed `owned`
  ranges, so `assign_ownership` keeps them with the absorber. `split_at` moves each of the split
  node's key items whose anchor now lies in a piece onto that piece.
- *Safety net.* A new `reconcile_key_items(root, revision, mutable, report)` scans one document
  subtree. A mutable node's key item whose `seq` is outside that node's `owned` moves to the
  mutable node of the same document revision that owns `seq`, counted in a new
  `OptimizeReport.key_items_rehomed`. If no mutable node owns it, the item is dropped and counted
  in `rejected_proposals`. Nodes outside `mutable` are never read-modified (neither source nor
  target), so `restore_protected` and the protected-node check stay valid.
- It runs at the end of `plan_deterministic` (after `mark_mutable`) and in `run_llm_passes`
  after the headings and key-items passes, before summaries. Summary input digests include
  `key_items` (`optimizer.py:541`), so moving items after a summary would orphan its stamp.
- `validate_candidate` is unchanged.

**C. Heading-text rule** (`optimizer.py`, used by `optimizer_llm.py`). A new pure predicate
`is_heading_text(title)` encodes the "reads like a printed heading" check:
- at most `MAX_HEADING_WORDS` words;
- no trailing `.`, `;`, `:` or `,`;
- the last word is not a conjunction (`and`, `or`, `nor`, `y`, `e`, `o`, `u`, `ni`, casefolded);
- no list-marker prefix (`(a) `, `a) `, `(iv) `, `- `, `• `, `* `). Numbered headings such as
  `1. Introduction` stay valid.

`heading_like` keeps its structural checks (single line, not a table/code/caption) and delegates
the text test to `is_heading_text(heading_title(text))`.

**D. Bounded LLM inputs** (`optimizer_llm.py`). A module constant
`LLM_INPUT_BUDGET_TOKENS = 20_000` caps the framed segment tokens per call.
`window_reads(reads, revision, budget=...)` splits reads, in order, into consecutive windows
under the budget. Cost is the segment's stored `tokens` plus a per-segment frame allowance. A
single read over the budget is clipped proportionally until it fits (`truncated=True`, `end`
adjusted).
- `propose_headings` frames **only** the `heading_like` candidates, windowed. With no candidate
  it returns `[]` without calling the model. Proposals are validated exactly as today.
- `propose_key_items` makes one call per window, asking each for up to
  `ceil(max_key_items / windows)`, and accepts at most `max_key_items` in total. With one window
  the prompt is unchanged.
- `summarize_leaf` makes one call when the leaf fits. Otherwise it summarizes each window, then
  one reduce call combines the framed partial summaries (`frame_text`).
- `compose_parent` clips the joined child summaries and key items to half the budget, then
  frames the first window of the node's own text within what remains.
- `llm_calls_made` counts adapter calls actually issued: each pass function increments it per
  call when given `report`, and `run_llm_passes` drops its own `+= 1` lines. A retry-cache hit is
  therefore no longer counted. `_estimate_llm_calls` counts windows.

**E. Pseudo-heading fallback** (`optimizer.py`). When an oversized leaf owns no usable heading
segment, `expand_at_headings` falls back to `pseudo_heading_segments(node, revision)`:
- *Candidates:* `paragraph` segments that are a single line and either fully wrapped in emphasis
  (`**…**` / `__…__`, split runs included) or whose cased letters (at least two) are all upper
  case, and whose `heading_title` passes `is_heading_text`.
- *Exclusions:* a title repeated more than `PSEUDO_HEADING_MAX_REPEATS` (= 2) times in the leaf
  is a running header/footer and is dropped. A first candidate matching the node title is
  excluded, mirroring `heading_segments`.
- *Coalescing:* `_coalesce_split_points` removes split points that would leave a piece under
  `min_leaf_tokens`, so one stray short line cannot veto the whole split through
  `should_expand`. The real-heading path is unchanged.
- Piece titles come from `heading_title` (which strips the emphasis), and the `ExpandAction`
  source stays `"layout"`.

### Component Diagram
```
toolkit.optimize / _optimize_imported           (unchanged)
   │
   ├─→ plan_deterministic ─→ normalize(parent=…) ─→ _absorb (widens span; "empty" → parent alias)
   │                       ─→ expand_at_headings ─→ heading_segments │ pseudo_heading_segments
   │                                             └→ _coalesce_split_points ─→ split_at (moves key items)
   │                       ─→ reconcile_key_items                      (NEW safety net)
   ├─→ _restore_merged_ownership                 (unchanged)
   ├─→ run_llm_passes ─→ propose_headings   ─→ heading_like → is_heading_text
   │                  │                      └→ window_reads(candidates)        (NEW)
   │                  ─→ propose_key_items  ─→ window_reads(leaf)               (NEW)
   │                  ─→ reconcile_key_items                                    (NEW call site)
   │                  ─→ summarize_leaf / compose_parent ─→ window_reads + reduce (NEW)
   └─→ validate_candidate                        (unchanged, fail-closed)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PageIndexToolkit.optimize` / `_optimize_imported` (`toolkit.py:1489`, `:2365`) | uses (unchanged) | Call order plan → restore → passes → validate is what B relies on |
| `_restore_merged_ownership` (`toolkit.py:112`) | interacts (unchanged) | Widening by alias spans is a no-op for a parent absorber (A) and for an absorber whose span `_absorb` already widened (B) |
| `validate_candidate` (`optimizer.py:653`) | unchanged | Remains the fail-closed backstop |
| `framing.frame_segments` / `frame_text` (`framing.py:33`, `:39`) | uses | Windows and partial summaries are framed with the same helpers |
| `layout_structure.heading_title` / `MAX_HEADING_WORDS` (`layout_structure.py:61`, `:23`) | uses | Title cleanup and word cap shared with the layout path |
| `optimizer_eval` (`optimizer_eval.py:193`) | consumes | `llm_calls` now reflects issued calls |

### Data Models
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py — OptimizeReport gains one counter
class OptimizeReport(BaseModel):          # verified: optimizer.py:93
    rejected_proposals: int = 0           # verified: optimizer.py:113 (also counts dropped key items, B)
    key_items_rehomed: int = 0            # NEW — key items moved to the node that now owns their anchor
```

### New Public Interfaces
See §3 Interface Skeletons: `is_heading_text`, `pseudo_heading_segments`, `reconcile_key_items`
(`optimizer.py`); `LLM_INPUT_BUDGET_TOKENS`, `window_reads` (`optimizer_llm.py`); new keyword
`parent` on `normalize`; new keyword `report` on `summarize_leaf` / `compose_parent`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: normalization identity + anchor integrity | yes | Skeletons below; absorber = parent; span widening = owned extent; reconcile semantics fixed in §2 B | — |
| M2: heading-text rule + pseudo-heading fallback | yes | Predicate rules, repeat threshold 2, coalescing rule fixed in §2 C/E | — |
| M3: bounded LLM inputs | yes | Budget 20 000, frame allowance 24 tokens/segment, quota and reduce rules fixed in §2 D | — |
| M4: documentation | yes | Pages and assertions listed in §10 | — |

### Module 1: Normalization identity and anchor integrity
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py`
- **Responsibility**: issue 33ad (empty-leaf alias) and issue 66f items 1–2 (anchors follow
  ownership; reconcile safety net; `key_items_rehomed`).
- **Depends on**: existing optimizer only.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py  (modifies)
  class OptimizeReport(BaseModel):  # verified: optimizer.py:93
      key_items_rehomed: int = 0  # NEW, placed after rejected_proposals (verified: optimizer.py:113)

  def _absorb(  # verified: optimizer.py:277
      absorber: dict,
      absorbed: dict,
      reason: Literal["duplicate_span", "empty", "under_minimum"],
      report: OptimizeReport,
      revision: DocumentRevision,
  ) -> None:
      """Merge a leaf into another node, retaining the absorbed title and alias.

      When ``absorbed`` owns ranges, ``absorber["span"]`` is widened to cover their extent so that a later
      ``assign_ownership`` (which rebuilds a leaf's ``owned`` from its ``span``) keeps them with the absorber.
      An absorbed node without owned ranges adds no key item and leaves the span unchanged.
      """

  def normalize(  # verified: optimizer.py:309
      parent_children: list[dict],
      revision: DocumentRevision,
      settings: OptimizerSettings,
      report: OptimizeReport,
      *,
      parent: Optional[dict] = None,
  ) -> None:
      """Collapse duplicate/empty leaves and contiguous undersized sibling leaves.

      An empty leaf (no children, no owned ranges) is absorbed into ``parent`` with reason ``"empty"`` (its
      ``concept_id`` becomes a parent alias) and removed. A published empty leaf (``node_id`` set) without a
      ``concept_id`` is kept. Without ``parent`` an empty leaf is removed unrecorded (legacy behaviour).
      Recursion passes each child as the ``parent`` of its own children.
      """

  def split_at(...) -> list[dict]:  # verified: optimizer.py:432 — signature unchanged
      """... After the split, every key item of ``node`` whose anchor lies in a piece's owned ranges is moved
      to that piece (counted in ``report.key_items_rehomed``)."""

  def reconcile_key_items(
      root: dict, revision: DocumentRevision, mutable: set[int], report: OptimizeReport
  ) -> None:
      """Re-home or drop key items whose anchor is outside their node's owned ranges.

      Scans the nodes of ``root``'s document revision. For each node whose ``id()`` is in ``mutable``, a key
      item (dict or ``KeyItem``) whose ``seq`` is not inside the node's ``owned`` ranges moves to the node of
      the same document revision whose ``owned`` ranges contain ``seq`` when that node is in ``mutable``,
      skipping a duplicate ``(label, seq)`` already there (``report.key_items_rehomed += 1``). Otherwise the
      item is dropped (``report.rejected_proposals += 1``). Nodes outside ``mutable`` are never modified.
      """
  ```
  `plan_deterministic` (`optimizer.py:600`) passes `parent=root` to `normalize` and calls
  `reconcile_key_items` for each root after `plan.optimizable_roots = roots` (`optimizer.py:635`).

### Module 2: Heading-text rule and pseudo-heading fallback
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py`
- **Responsibility**: issue 0a69 (deterministic expansion of ebooks and markdown without `#`
  headings) and the shared predicate behind issue 66f item 3.
- **Depends on**: Module 1 (same file, so the tasks are serialized; no symbol dependency).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py  (modifies)
  import re  # NEW import (stdlib)

  PSEUDO_HEADING_MAX_REPEATS = 2  # NEW — a title seen more often in one leaf is a running line

  def is_heading_text(title: str) -> bool:
      """Return whether a cleaned, single-line title reads as a printed heading.

      False for empty text, more than ``MAX_HEADING_WORDS`` words (verified: layout_structure.py:23), a
      trailing ``.``, ``;``, ``:`` or ``,``, a casefolded last word in {and, or, nor, y, e, o, u, ni}, or a
      list-marker prefix (``(a) ``, ``a) ``, ``(iv) ``, ``- ``, ``• ``, ``* ``). ``1. Introduction`` is valid.
      """

  def pseudo_heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]:
      """Return owned single-line paragraph segments that read as headings.

      A candidate is a ``paragraph`` segment whose stripped text is one line, either fully wrapped in emphasis
      (starts and ends with ``**`` or ``__``; split runs such as ``**P****ROLOGO**`` included) or whose cased
      letters (at least two) are all upper case, and whose ``heading_title`` passes ``is_heading_text``. Titles
      occurring more than ``PSEUDO_HEADING_MAX_REPEATS`` times among the node's owned segments are dropped, as
      is a first candidate whose title matches the node title (same rule as ``heading_segments``,
      verified: optimizer.py:389).
      """

  def _coalesce_split_points(
      node: dict, revision: DocumentRevision, seqs: list[int], settings: OptimizerSettings
  ) -> list[int]:
      """Return the split points that leave no piece under ``settings.min_leaf_tokens``.

      Walks the sorted points: a point whose piece since the last kept point is under the minimum is
      dropped (merged forward); if the final piece is under the minimum and more than one point is kept,
      the last kept point is dropped (merged backward). Token counts use ``owned_tokens`` over the owned
      ranges between points.
      """

  def expand_at_headings(...) -> None:  # verified: optimizer.py:487 — signature unchanged
      """... When the leaf owns no usable heading segment, falls back to ``pseudo_heading_segments`` and
      ``_coalesce_split_points`` before ``split_at(..., source="layout")``. The real-heading path is
      unchanged."""
  ```

### Module 3: Bounded LLM inputs and pass wiring
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py`
- **Responsibility**: issue ab52 (bounded prompts, windowing, reduce) and issue 66f items 1 and 3
  (`reconcile_key_items` call site, `heading_like` tightening).
- **Depends on**: Module 1 (`reconcile_key_items`) and Module 2 (`is_heading_text`), both
  imported from `parrot.knowledge.pageindex.optimizer` (`optimizer_llm.py:17`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py  (modifies)
  LLM_INPUT_BUDGET_TOKENS = 20_000  # NEW — per-call cap on framed document tokens
  _FRAME_OVERHEAD_TOKENS = 24       # NEW — per-segment allowance for the <segment …> wrapper

  def window_reads(
      reads: list[SegmentRead], revision: DocumentRevision, *, budget: int = LLM_INPUT_BUDGET_TOKENS
  ) -> list[list[SegmentRead]]:
      """Split reads, in order, into consecutive windows whose cost stays within ``budget``.

      Cost of a read = its segment's stored ``tokens`` (``Segment.tokens``, verified: segments.py:43) plus
      ``_FRAME_OVERHEAD_TOKENS``. A single read over the budget forms its own window, its ``text`` clipped
      proportionally until ``count_tokens`` fits the budget (``truncated=True``, ``end`` adjusted).
      ``[]`` for no reads.
      """

  def heading_like(segment: Segment) -> bool:  # verified: optimizer_llm.py:108
      """... Single line, not table/code/caption, and ``is_heading_text(heading_title(text))``."""

  async def propose_headings(node, revision, adapter, settings, *, report=None) -> list[int]:
      # verified: optimizer_llm.py:134 — signature unchanged
      """Frames only ``heading_like`` candidates, one call per window; no candidate → ``[]``, no call."""

  async def propose_key_items(node, revision, adapter, settings, *, report=None) -> list[KeyItem]:
      # verified: optimizer_llm.py:167 — signature unchanged
      """One call per window asking for up to ceil(max_key_items / windows); at most max_key_items total."""

  async def summarize_leaf(
      node: dict, revision: DocumentRevision, adapter: Optional[Any], settings: OptimizerSettings,
      *, report: Optional[Any] = None,
  ) -> tuple[str, str]:  # verified: optimizer_llm.py:224
      """... A live leaf over the budget: one call per window, then one framed reduce call."""

  async def compose_parent(
      node: dict, revision: DocumentRevision, adapter: Optional[Any], settings: OptimizerSettings,
      *, report: Optional[Any] = None,
  ) -> tuple[str, str]:  # verified: optimizer_llm.py:245
      """... Child summaries + key items clipped to half the budget; own text = first window of the rest."""
  ```
  Each pass function adds 1 to `report.llm_calls_made` per adapter call when `report` is given.
  `run_llm_passes` (`optimizer_llm.py:360`) passes `report=plan.report` to all four, removes its
  three `plan.report.llm_calls_made += 1` lines (`optimizer_llm.py:414`, `:453`, `:490`), and
  calls `reconcile_key_items(root, revision, plan.mutable, plan.report)` before
  `if not with_summaries:` (`optimizer_llm.py:458`), outside the `if live:` block.
  `_estimate_llm_calls` (`optimizer_llm.py:331`) counts windows: candidate windows for headings,
  leaf windows for key items, windows (+1 reduce when >1) for leaf summaries, 1 for a parent.

### Module 4: Documentation
- **Path**: `wiki/knowledge/pageindex-tree-optimizer.md`,
  `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py`
- **Responsibility**: document A–E (see §10) and assert the new names in the docs test.
- **Depends on**: Modules 1–3 (documents their final names).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_normalize_absorbs_empty_leaf_into_parent` | M1 | With `parent`, an empty leaf with a `concept_id` is removed, its id is in `parent["aliases"]`, `report.merged` has a `reason="empty"` action into the parent |
| `test_normalize_keeps_published_empty_leaf_without_concept_id` | M1 | `node_id` set, no `concept_id` → kept |
| `test_validate_accepts_preface_shaped_tree` | M1 | Published tree: document root with an empty first leaf (`owned: []`, `node_id`, `concept_id`) beside the real section. `plan_deterministic` + `run_llm_passes(adapter=None)` + `validate_candidate(base_tree=published)` → no error |
| `test_absorb_widens_span_and_keeps_title_anchor` | M1 | After an `under_minimum` merge and `assign_ownership`, the absorbed title key item is inside the absorber's `owned` |
| `test_split_moves_key_items_to_pieces` | M1 | A leaf carrying key items split by `split_at` (and by `expand_at_headings`): each item sits on the piece owning its `seq`; `validate_candidate` reports no anchor error |
| `test_reconcile_rehomes_or_drops` | M1 | Out-of-range anchor → moved to the mutable owner (`key_items_rehomed == 1`); owner not mutable → dropped (`rejected_proposals == 1`); a non-mutable node is untouched |
| `test_is_heading_text_rules` | M2 | Rejects `"…; and"`, `"Scope:"`, `"(a) Policy"`, `"- item"`, `"Ends with y"`; accepts `"1. Introduction"`, `"Chapter 3"`, `"SEGUNDA PARTE"`, `"Topic heading"` |
| `test_pseudo_headings_expand_bold_and_caps_lines` | M2 | Markdown with no `#` headings: `**P****ROLOGO**`, `SEGUNDA PARTE`, `**Capítulo I**` lines → `plan_deterministic` expands the oversized leaf, piece titles `PROLOGO`, `SEGUNDA PARTE`, `Capítulo I` |
| `test_pseudo_headings_ignore_running_lines_and_real_headings` | M2 | A caps line repeated 3× is not a split point; a leaf owning `#` headings ignores pseudo-headings |
| `test_coalesce_split_points_merges_tiny_pieces` | M2 | A short line near the next title no longer vetoes the split; every piece ≥ `min_leaf_tokens` |
| `test_window_reads_respects_budget` | M3 | Windows are in order, each ≤ budget; an oversized single read is clipped (`truncated=True`) |
| `test_propose_headings_frames_only_candidates` | M3 | Prompt contains candidate segments only; no candidate → no adapter call, `[]` |
| `test_heading_like_rejects_fragments` | M3 | NIST-shaped fragment ending in `; and` and `(a) …` lines rejected |
| `test_propose_key_items_windows_and_caps` | M3 | Small budget patch → one call per window, total ≤ `max_key_items` |
| `test_summarize_leaf_map_reduce` | M3 | Leaf over budget → N window calls + 1 reduce; no prompt over the budget |
| `test_compose_parent_bounded` | M3 | Own text framed from the first window only; child summaries clipped |
| `test_llm_calls_made_counts_issued_calls` | M3 | `llm_calls_made` == adapter `await_count`; a second run served from `llm_cache` adds 0 |
| `test_run_llm_passes_reconciles_before_summaries` | M3 | A split leaf with pre-existing key items validates after `run_llm_passes` |

Existing tests must keep passing unchanged, in particular `test_normalize_duplicates_empty_and_tiny`
(legacy no-`parent` path), `test_heading_like_and_proposals`, `test_prompts_are_framed` and
`test_first_run_executes_before_stamping` (one window → same call counts).

### Integration Tests
| Test | Description |
|---|---|
| `test_optimize_apply_with_empty_leaf` (`test_optimizer_toolkit.py`) | `_tree_with_document`, then insert an empty first leaf (`owned: []`, unique `node_id`, `concept_id`, root `doc_id`/`revision`) through `toolkit._store.load` / `_store.save`; `optimize(apply=True, llm_passes=False)` returns `errors == []` and the published root carries the alias |
| `test_optimize_apply_reconciles_key_items` (`test_optimizer_toolkit.py`) | A published leaf with persisted key items is split by the apply; it publishes with `errors == []` |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_eval.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py
markers: none

### Test Data / Fixtures
```python
# Synthetic revisions only — no corpus PDFs, no network, no real LLM.
segment_text("**P****ROLOGO**\n\n<prose>\n\nSEGUNDA PARTE\n\n<prose>", ["Document"])  # verified: segments.py:240
# Live passes use MagicMock(client=MagicMock()) with AsyncMock ask_structured (test_optimizer_llm.py:44).
# Small budgets: monkeypatch optimizer_llm.LLM_INPUT_BUDGET_TOKENS or pass budget= to window_reads.
```

---

## 5. Acceptance Criteria

- [ ] **AC-1** (33ad) `optimize(apply=True)` on a published tree whose document root has an empty
  leaf with `node_id` and `concept_id` publishes with `errors == []`. The leaf's `concept_id` is
  in the parent's `aliases`, and the report has a `MergeAction` with `reason == "empty"`.
- [ ] **AC-2** `normalize` without `parent` behaves as before (existing test unchanged); a
  published empty leaf without a `concept_id` is kept.
- [ ] **AC-3** (66f) After any split (`expand_at_headings` or the LLM `split_at`) of a node that
  carries key items, every key item lies inside its node's `owned` ranges, and
  `validate_candidate` reports no `key_item anchor` error.
- [ ] **AC-4** (66f) An `under_minimum` merge followed by `assign_ownership` keeps the absorbed
  range and its title key item with the absorber.
- [ ] **AC-5** (66f) `reconcile_key_items` moves an out-of-range anchor to the mutable node
  owning it (`key_items_rehomed`), drops it otherwise (`rejected_proposals`), and never modifies a
  node outside `mutable`.
- [ ] **AC-6** (66f) `heading_like` / `is_heading_text` reject trailing `.`, `;`, `:`, `,`,
  trailing conjunctions and list-marker prefixes, and accept numbered and upper-case headings.
- [ ] **AC-7** (ab52) No optimizer LLM call frames more than `LLM_INPUT_BUDGET_TOKENS` of segment
  tokens. `propose_headings` frames only `heading_like` candidates and makes no call when there
  is none.
- [ ] **AC-8** (ab52) `propose_key_items` and `summarize_leaf` window an oversized leaf (with a
  reduce call for summaries); `compose_parent` bounds its own text and child summaries.
- [ ] **AC-9** `llm_calls_made` equals the number of adapter calls issued (cache hits excluded);
  `llm_calls_estimated` counts windows.
- [ ] **AC-10** (0a69) A markdown/ebook revision with no `#` headings but standalone bold or
  upper-case title lines is expanded by `plan_deterministic` at those lines, with no LLM.
  Running lines (more than 2 repeats) are ignored, and no piece is under `min_leaf_tokens`.
- [ ] **AC-11** `split_blocks`, `segment_pages`, segment kinds and `revision_id` are unchanged
  (`segments.py` is not modified). Leaves owning real heading segments expand exactly as before.
- [ ] **AC-12** All Validation Contract suites pass; `ruff check` and `black --check` are clean
  on every changed file.
- [ ] **AC-13** `wiki/knowledge/pageindex-tree-optimizer.md` documents A–E (§10), and
  `test_optimizer_docs.py` asserts the new names.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.pageindex.optimizer import (  # verified: optimizer.py:29-121 (definitions)
    KeyItem, MergeAction, OptimizePlan, OptimizeReport, OptimizerSettings,
    assign_ownership, expand_at_headings, normalize, owned_tokens, plan_deterministic,
    split_at, validate_candidate,
)
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title  # verified: optimizer.py:13
from parrot.knowledge.pageindex.segments import (  # verified: optimizer.py:14-22, optimizer_llm.py:30
    DocumentRevision, Segment, SegmentAddress, SegmentRead, _heading_text, _subtract, _titles_match,
    normalize_title, revision_id, segment_text, validate_ownership,
)
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text  # verified: optimizer_llm.py:15
from parrot.knowledge.pageindex import utils as _utils  # verified: optimizer.py:12 (_utils.count_tokens, utils.py:66)
from parrot.knowledge.pageindex.utils import structure_to_list  # verified: optimizer.py:23
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel):            # line 33 — seq, kind, page, ordinal, section, level: Optional[int],
                                     #   text, tokens: int (line 43, required), sha16, flags, injection
class SegmentRead(BaseModel):        # line 97 — address, seq, kind, text, start, end, truncated=False, flags
def split_blocks(markdown: str) -> list[tuple[SegmentKind, str, Optional[int]]]:  # line 150 — NOT modified
def segment_pages(pages) -> list[Segment]:   # line 231 — feeds PDFs through split_blocks (why §7 rejects (b))
def revision_id(segments) -> str:            # line 249 — hashes texts only

# packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py
MAX_HEADING_WORDS = 20               # line 23
def heading_title(text: str) -> str: # line 61 — strips ATX + emphasis (`**`, `__`, `~~`, backtick)

# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py
class MergeAction(BaseModel):  reason: Literal["duplicate_span", "empty", "under_minimum"]  # line 81
class OptimizeReport(BaseModel):                                   # line 93; rejected_proposals line 113
def _absorb(absorber, absorbed, reason, report, revision) -> None: # line 277
def normalize(parent_children, revision, settings, report) -> None:  # line 309; empty-leaf rule line 323
def assign_ownership(node: dict) -> None:                          # line 369 — leaf owned := [span]
def heading_segments(node, revision) -> list[Segment]:             # line 389
def should_expand(node_tokens, piece_tokens, cost, settings) -> bool:  # line 416
def _owned_in_span(owned, start, end) -> list[list[int]]:          # line 423
def split_at(node, revision, seqs, *, source, settings, report) -> list[dict]:  # line 432; node["nodes"] = pieces line 474
def expand_at_headings(node, revision, settings, report, *, depth) -> None:     # line 487
def pass_input(node, pass_name) -> str:   # line 531 — summary digest includes key_items (line 541)
def _document_nodes(root, doc_id, revision) -> list[dict]:         # line 593
def plan_deterministic(tree, revisions, settings, *, tree_name, node_id=None) -> OptimizePlan:  # line 600
def validate_candidate(plan, revisions, *, base_tree) -> list[str]:  # line 653

# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py
PROMPT_VERSION = "v1"                                  # line 33 — NOT changed
def reads_for(node, revision) -> list[SegmentRead]:    # line 77
def heading_like(segment: Segment) -> bool:            # line 108
async def propose_headings(...) -> list[int]:          # line 134
async def propose_key_items(...) -> list[KeyItem]:     # line 167
async def summarize_leaf(...) -> tuple[str, str]:      # line 224
async def compose_parent(...) -> tuple[str, str]:      # line 245
def _estimate_llm_calls(...) -> int:                   # line 331
async def run_llm_passes(plan, revisions, adapter, settings, *, with_summaries=True) -> None:  # line 360
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `normalize(parent=…)` | `_absorb(…, "empty", …)` | call | `optimizer.py:277`, `:323` |
| `reconcile_key_items` | `plan_deterministic` / `run_llm_passes` | call | `optimizer.py:635`, `optimizer_llm.py:458` |
| `is_heading_text` | `heading_like`, `pseudo_heading_segments` | call | `optimizer_llm.py:108` |
| `window_reads` | four pass functions | call | `optimizer_llm.py:134`, `:167`, `:224`, `:245` |
| `report.llm_calls_made` | pass functions (moved from `run_llm_passes`) | counter | `optimizer_llm.py:414`, `:453`, `:490` |

### Does NOT Exist (Anti-Hallucination)
- ~~`OptimizerSettings.llm_input_tokens`~~ / any new settings field — deliberately not added
  (settings digest, §7).
- ~~`parrot.knowledge.pageindex.optimizer.reconcile_key_items`~~ /
  ~~`is_heading_text`~~ / ~~`pseudo_heading_segments`~~ — created by this feature.
- ~~`OptimizeReport.key_items_rehomed`~~ — created by this feature.
- ~~`SegmentKind` value `"pseudo_heading"`~~ — kinds are unchanged; pseudo-headings stay
  `paragraph` segments.
- ~~`toolkit._restore_merged_ownership` changes~~ — the toolkit is not modified.
- `normalize` is never handed the parent node today (`optimizer.py:315`, `:618`) — the
  `parent` keyword is new.

### Edit Sites (Blueprint Anchors)

Verified against: `8e1882833c`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `    rejected_proposals: int = 0` | `optimizer.py:113` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `    _record_merge(absorbed, absorber, reason, report)` | `optimizer.py:306` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `def normalize(` | `optimizer.py:309` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `            normalize(child.get("nodes") or [], revision, settings, report)` | `optimizer.py:315` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `        if not node.get("nodes") and not (node.get("owned") or []):` | `optimizer.py:323` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `def heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]:` | `optimizer.py:389` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `    node["nodes"] = pieces` | `optimizer.py:474` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `    if not headings:` | `optimizer.py:506` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `        normalize(root.get("nodes") or [], revision, settings, report)` | `optimizer.py:618` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | `    plan.optimizable_roots = roots` | `optimizer.py:635` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `from parrot.knowledge.pageindex.optimizer import (` | `optimizer_llm.py:17` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `PROMPT_VERSION = "v1"` | `optimizer_llm.py:33` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `def heading_like(segment: Segment) -> bool:` | `optimizer_llm.py:108` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `async def propose_headings(` | `optimizer_llm.py:134` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `async def propose_key_items(` | `optimizer_llm.py:167` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `async def summarize_leaf(` | `optimizer_llm.py:224` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `async def compose_parent(` | `optimizer_llm.py:245` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `def _estimate_llm_calls(` | `optimizer_llm.py:331` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `plan.report.llm_calls_made += 1` (three sites: headings, key items, summary) | `optimizer_llm.py:414`, `:453`, `:490` | 3 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | `            if not with_summaries:` | `optimizer_llm.py:458` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | MODIFY | `def test_validate_candidate(revision: DocumentRevision) -> None:` | `test_optimizer.py:209` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py` | MODIFY | `def test_adapter_is_live() -> None:` | `test_optimizer_llm.py:84` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` | MODIFY | `async def _tree_with_document(tmp_path: Path, name: str = "guide") -> PageIndexToolkit:` | `test_optimizer_toolkit.py:117` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` | MODIFY | `def test_pages_link_optimizer_page() -> None:` | `test_optimizer_docs.py:35` | 1 |
| `wiki/knowledge/pageindex-tree-optimizer.md` | MODIFY | `## The passes, in order` | `pageindex-tree-optimizer.md:46` | 1 |
| `wiki/knowledge/pageindex-tree-optimizer.md` | MODIFY | `## Framing` | `pageindex-tree-optimizer.md:220` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Pure, synchronous helpers in `optimizer.py` (no I/O); the async pass functions stay in
  `optimizer_llm.py`. Key items may be `dict` or `KeyItem` everywhere: keep the existing
  `item.get("seq") if isinstance(item, dict) else item.seq` idiom.
- Every prompt keeps `DATA_FRAMING_INSTRUCTION` as the system prompt, and every piece of
  document-derived text, partial summaries included, goes through `frame_segments` / `frame_text`.
- Proposal validation stays against the **node's** owned segments, not the window's.

### Known Risks / Gotchas
- **Stamp invalidation.** `PROMPT_VERSION` and `OptimizerSettings` feed the execution and
  settings digests (`optimizer_llm.py:68`, `optimizer.py:41`); changing either re-runs every LLM
  pass on every published tree. That is why the budget is a module constant and the prompt
  version is kept. Results produced by the old whole-leaf prompts stay valid.
- **Single-window equivalence.** With one window, prompts and call counts must equal today's.
  The existing call-count tests (`test_first_run_executes_before_stamping`: 3 calls) are the
  guard.
- **Counting change.** `llm_calls_made` used to count retry-cache hits. `optimizer_eval`
  (`optimizer_eval.py:193`) and `test_optimizer_eval.py:142` read it; its `> 0` assertion
  still holds with a fake model.
- **Caps false positives.** Upper-case lines such as `ISBN 978…` can be candidates.
  `_coalesce_split_points` and `should_expand` limit the damage, and the repeat filter removes
  running headers. Real-heading leaves never use the fallback.
- **Parent absorber and spans.** The base tree's parent span covers its children, so the
  toolkit's alias-span widening is a no-op for it. Never absorb an empty leaf into a sibling.
- **Clipping CJK text.** Clip by `count_tokens`, not by a characters-per-token ratio.
- Rejected alternatives for issue 0a69 (recorded, not adopted):
  - (a) Loaders emit `#` headings: every ebook would need a re-import.
  - (b) `split_blocks` types bold/caps lines as headings: it also segments PDF pages
    (`segment_pages`, `segments.py:231`), so layout structure detection and existing PDF trees
    would change.

### Ledger Linkage
Every task carries `**Discovered-from**: issue:<id>` for the issues it resolves; `/sdd-done
FEAT-853` closes them by `--resolved-by task:TASK-<NNN>`.

| Issue | Severity | Resolved by |
|---|---|---|
| `issue:33ad15e686e9` | major | M1 |
| `issue:66f376157327` | major | M1 (items 1–2), M3 (item 3 + wiring) — closes with the M3 task |
| `issue:ab5235978ad7` | major | M3 |
| `issue:0a693a57b138` | minor | M2 |

### External Dependencies
None.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-853-pageindex-optimizer-fixes`, off
  `origin/dev`. The `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1: same file, so the tasks are serialized; no symbol dependency.
  - M3 → M1: imports `reconcile_key_items`.
  - M3 → M2: imports `is_heading_text`.
  - M4 → M1, M2, M3: documents their final names.
- **Shared files**: `optimizer.py` (M1, M2); `test_optimizer.py` (M1, M2).
- **Exclusive resources**: none (no lockfile, migration or native rebuild).
- **Cross-feature dependencies**: none. FEAT-849 and FEAT-852 touch other pageindex files
  (`toolkit.py`, `agentic.py`, `segment_store.py`), not the optimizer.

---

## Decisions

```yaml
schema_version: 1
document_id: pageindex-optimizer-fixes
entries:
  - id: optimizer-llm-input-bounded
    statement: Every optimizer LLM call frames at most LLM_INPUT_BUDGET_TOKENS of document text; an oversized node is windowed (with a reduce call for summaries), never sent whole.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_headings, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_key_items, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#summarize_leaf, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#compose_parent]
    contradicts: []
    supersedes: []
    rationale: A 157k-token leaf produced a 299k-token request that every 200k-context model rejects, and any pass error fails the whole apply.
    rejected_alternatives: ["send only a truncated prefix of the leaf (loses the rest of the leaf for key items and summaries)", "a new OptimizerSettings field (changes settings_hash and invalidates every stamp)"]
  - id: pseudo-headings-in-optimizer
    statement: Headings inferred from standalone bold or upper-case lines are an optimizer fallback for leaves without heading segments; the segmenter keeps typing those lines as paragraphs.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py, file:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py]
    contradicts: []
    supersedes: []
    rationale: split_blocks also segments PDF pages, so typing those lines as headings there would change layout structure detection for every PDF; the optimizer fallback also works on already-imported books.
    rejected_alternatives: ["type bold/caps lines as heading in split_blocks", "emit # headings in the ebook loaders"]
  - id: key-item-anchors-follow-ownership
    statement: Before candidate validation, a key item whose anchor left its node's owned ranges is moved to the mutable node that owns the anchor or dropped and counted; validate_candidate stays fail-closed.
    relation: requires
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py]
    contradicts: []
    supersedes: []
    rationale: One stale anchor discarded 209 LLM calls and the whole NIST 800-53 candidate; anchors are validated at proposal time but ownership changes afterwards.
    rejected_alternatives: ["relax validate_candidate to ignore anchor errors (hides real ownership bugs)"]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:a66c440b731d031fc35828435c8db8adbfb774acf751c1d3f45788ceebd5c38f evaluation_digest=sha256:f4f7314911fa5838fe2f25f55c7ff08c6b66b108e18087018dc892809316e999 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-optimizer-fixes#optimizer-llm-input-bounded@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_key_items; message: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_key_items impacts 1 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#run_llm_passes
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-optimizer-fixes#optimizer-llm-input-bounded@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_headings; message: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_headings impacts 1 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#run_llm_passes

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: ledger-fix, tree-optimizer
- Targets resolved: 6/6
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
    "targets_resolved": 6,
    "targets_total": 6,
    "unmapped_tags": [
      "ledger-fix",
      "tree-optimizer"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:f4f7314911fa5838fe2f25f55c7ff08c6b66b108e18087018dc892809316e999",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:0b623175f076e2aa83840591291216f50c0398c96837b06b2f3c84f4acb8d764",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_key_items impacts 1 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#run_llm_passes",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-optimizer-fixes#optimizer-llm-input-bounded",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_key_items"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:4bc223b092fe53e23126a9d607b18d99b415cbb46c9ca98b3086588991830040",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_headings impacts 1 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#run_llm_passes",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-optimizer-fixes#optimizer-llm-input-bounded",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py#propose_headings"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:a66c440b731d031fc35828435c8db8adbfb774acf751c1d3f45788ceebd5c38f",
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
    "structural_revision": "sha256:8883a2ab903ee6342a954ea0c667b41e17af8c205b5044b768e050756b35bd73",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Which absorber for an empty leaf: parent or following sibling? — *Resolved at spec time
  (Claude, from the issue's own suggestion)*: the parent. Its span already covers the child, so
  the toolkit's alias-span restore is a no-op. A sibling can be widened across a neighbour.
- [x] Fix issue 0a69 in the segmenter, the loaders, or the optimizer? — *Resolved at spec time*:
  in the optimizer (Decisions `pseudo-headings-in-optimizer`). Both options the issue offered
  have the blast radius recorded in §7.
- [ ] Is 20 000 tokens the right per-call budget? It is the issue's suggestion. The LLM-mode
  tuning run (`issue:336eef8010a1`) should confirm it. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document — spec seeded from ledger group
> `fixgroup:9b38cab45056` in a non-interactive `/sdd-fix` run)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/knowledge/pageindex-tree-optimizer.md` — update:
    - normalize: empty leaves become a parent alias with reason `empty`;
    - key-item re-homing, `key_items_rehomed`, dropped items in `rejected_proposals`;
    - the `is_heading_text` rule behind `heading_like`;
    - the pseudo-heading fallback (bold/caps lines, repeat filter, coalescing);
    - `LLM_INPUT_BUDGET_TOKENS`, windowing and the summary reduce call (Framing section);
    - `llm_calls_made` semantics (issued calls only).
- **API modules**: `parrot.knowledge.pageindex.optimizer`, `parrot.knowledge.pageindex.optimizer_llm`

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara (with Claude) | Initial spec from `/sdd-fix issue:66f376157327` (group `fixgroup:9b38cab45056`) |
