---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — core only: parrot.knowledge.pageindex
tags: [pageindex, tech-debt, agentic-retrieval, idempotency, ledger-fix]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-agentic-retrieval.md]
  api_modules: [parrot.knowledge.pageindex.agentic, parrot.knowledge.pageindex.toolkit]
---

# Feature Specification: PageIndex Toolkit Tech Debt

**Feature ID**: FEAT-849
**Date**: 2026-11-09
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> Ledger-driven fix lane (`/sdd-fix`), group `fixgroup:fae1efc1b03f`. This spec drains two
> open ledger issues left behind by FEAT-843 (`pageindex-agentic-retrieval`) and FEAT-844
> (`pageindex-toolkit-fixes`), both of which are merged and closed:
>
> - `issue:d34c567792ef` — same-source re-import splices a second subtree with the same
>   `doc_id@revision` (replace vs skip undecided). Split out of `issue:b42f99778d5f` item (1).
> - `issue:2e4dfac0d686` — agentic retrieval robustness: `max_chars=None` TypeError, sync
>   `deepcopy` before the deadline, provider exception drops partial reads, plus two
>   documentation-only items.
>
> Code references were verified at `dev` @ `ccac13acb5`.

---

## 1. Motivation & Business Requirements

### Problem Statement

Five verified defects sit in two files of `parrot.knowledge.pageindex`:

1. **Duplicate documents on re-import.** `derive_doc_id` (`segments.py:254`) returns the
   *same* slug when `taken[slug]` already holds the *same* `source_sha256`. Every import
   path (`insert_markdown`, `insert_ebook`, `import_pdf`; `insert_content`, `import_file` and
   `import_folder` inherit the behaviour by delegation) then mints a fresh revision for that slug and splices a second
   subtree owning the same `doc_id`. `_documents_of` (`toolkit.py:847`) resolves
   first-wins, so `list_documents` / `outline` hide the duplicate, but BM25 ranks both
   copies and `read_*` bodies are stored twice. Re-importing the same PDF three times
   triples the index without any visible signal.
2. **`max_chars=None` crashes a read.** `agentic.py:197` charges
   `ledger.charge(kwargs.get("max_chars", 12000))`. The default only applies when the key
   is *absent*; a model that passes `max_chars: null` — well-formed against the tool
   schema — yields `None` and `ReadLedger.charge` raises `TypeError`, aborting the whole
   agentic request instead of degrading.
3. **Blocking `deepcopy` outside the deadline.** `toolkit.agentic_retrieve`
   (`toolkit.py:1295`) runs `copy.deepcopy(self._load_tree(tree_name))` synchronously on
   the event loop, after the lock is acquired and *outside* every `wait_for`. A large tree
   therefore blocks the loop and can overrun the caller's timeout before the first
   deadline check downstream of it.
4. **A provider exception discards paid-for reads.** `agentic.py:319`
   (`response = await provider_task`) lets a provider failure propagate out of
   `AgenticRetriever.run`. The read ledger has already charged the budget and collected
   `reads`/citations, and all of it is lost: the caller gets an exception rather than a
   partial `EvidenceBundle`.
5. **Two unstated semantics.** (a) cap-fill ends the loop immediately, so a model using
   exactly `max_tool_calls` always gets `stopped="max_tool_calls"` with no answer, and a
   same-tick provider-done/stop tie discards a completed answer; (b) the single
   `_agentic_lock` serialises every concurrent agentic request per toolkit instance.
   Neither is written down, so callers size their concurrency by guesswork.

### Business Requirements

- **BR-1**: Importing byte-identical content twice into the same tree MUST NOT grow the
  index, and MUST tell the caller the document was reused.
- **BR-2**: A malformed-but-schema-valid tool argument MUST NOT abort an agentic request.
- **BR-3**: An agentic request MUST stay inside its caller-provided deadline regardless of
  tree size.
- **BR-4**: Work already charged against the read budget MUST reach the caller even when
  the provider fails.
- **BR-5**: The loop's termination semantics and its per-toolkit concurrency limit MUST be
  documented where an integrator will find them.

### Non-Goals

- No change to `derive_doc_id`'s suffixing rule for a *different* source hash — a changed
  document still gets a `-<6 hex>` doc_id, exactly as today.
- No `replace` semantics. Deleting a previous subtree was considered and **rejected**
  (§3 Decision D-1): it changes node ids and drops any `node_markdown` /
  T3 classification attached to the old subtree.
- No lock-granularity change. `_agentic_lock` stays one lock per toolkit instance; this
  spec only documents the consequence.
- No new public tool, no MCP template change, no schema migration.

---

## 2. Scope

### In Scope

| File | Change |
|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | Same-source re-import short-circuit on all import paths; off-loop, deadline-bound tree snapshot in `agentic_retrieve`; docstring for the `_agentic_lock` throughput limit |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` | `max_chars` coercion; `provider_error` stop reason; docstring for the cap-fill / tie semantics |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` | Tests for `max_chars=None` and `provider_error` |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py` | Test for the deadline-bound snapshot |
| `packages/ai-parrot/tests/knowledge/pageindex/` (new or existing import test module) | Tests for the idempotent re-import on each import path |
| `wiki/knowledge/pageindex-agentic-retrieval.md` | Stop-reason table gains `provider_error`; new sections for cap-fill/tie semantics, the per-toolkit serialisation limit, and same-source re-import |

### NOT in Scope

- `segments.py` (`derive_doc_id` keeps its current contract).
- `generation.py`, `store.py`, `search.py`, the MCP toolkit templates.
- Any other open ledger issue; this feature closes exactly
  `issue:d34c567792ef` and `issue:2e4dfac0d686`.

---

## 3. Design Decisions

**D-1 — Same-source re-import is an idempotent skip, not a replace.**
When the caller passes no explicit `doc_id` and the derived slug is already taken by a
document whose `source.sha256` equals the incoming one, the import path splices nothing,
mints no revision, marks the transaction `txn.noop = True`, and returns the *existing*
`doc_id` / `revision` with `reused: True` and `new_node_ids: []`. The tree, its generation
and its segment store are untouched. Rejected alternative: deleting the previous subtree
inside the same transaction ("replace") — destructive, renumbers node ids, and loses
body/classification state attached to the old subtree.

Note on what is and is not already idempotent: `_new_revision` sets
`revision = revision_id(segments)` (`toolkit.py:2351`), so byte-identical content already
yields the *same* `doc_id@revision` pair — `test_insert_markdown_section_addresses`
(`test_segment_import.py`) asserts exactly that. What duplicates today is the spliced
**structure**: a second set of node ids pointing at the same revision. FR-1 therefore
changes node/tree state only; the returned `doc_id`/`revision` are unchanged from today.

Rationale for `txn.noop = True`: this is the toolkit's established "nothing changed: do not
mint an empty generation" pattern (`toolkit.py:1423`, `1589`, `1893`, `2480`). Note
`_mutate` deliberately forces `txn.noop = False` for a *joined* transaction
(`toolkit.py:414`), so a joined import step must not rely on `noop` to suppress a publish —
it simply splices nothing.

**D-2 — A provider failure gets its own stop reason.**
`StopReason` (`agentic.py:42`) gains `"provider_error"`. `run()` catches the exception from
`await provider_task`, logs it at `warning`, and falls through to the normal
`EvidenceBundle` build with `answer=None`, `grounded=False`, and the `reads` the ledger
already recorded. Rejected alternative: reusing `"parse_error"` — it conflates "the model
answered unparseably" with "the provider call blew up" and makes triage impossible.
`"provider_error"` is added to both existing guard sets so the answer-parse and
citation-validation branches are skipped exactly as they are for `"timeout"`.

**D-3 — `max_chars` is coerced, not validated.**
`int(kwargs.get("max_chars") or 12000)` — a single expression that absorbs `None`, `0` and
`""` into the documented default. A schema-level `Optional[int]` rejection would surface as
a tool-call error the model cannot recover from mid-loop.

**D-4 — The snapshot moves off-loop and under the deadline.**
`copy.deepcopy(self._load_tree(tree_name))` becomes
`await asyncio.wait_for(asyncio.to_thread(...), timeout=remaining)` with the existing
`timeout_bundle()` as the `TimeoutError` fallback, matching the four deadline checks that
already bracket search, outline and the retriever.

---

## 4. Functional Requirements

### FR-1 — Idempotent same-source re-import (`issue:d34c567792ef`)

- **FR-1.1** `PageIndexToolkit` gains one private helper that, given the open transaction's
  tree and an incoming `SourceInfo`, answers "is this exact source already imported under
  the slug it would derive?" and returns that document's `doc_id`, `revision` and root node
  ids. It reuses `_doc_ids_in` (which already maps `doc_id -> source sha256`) and the same
  slug derivation as `derive_doc_id`, so the two can never disagree.
- **FR-1.2** `insert_markdown`, `insert_ebook` and `import_pdf` — the three sites that call
  `derive_doc_id` (`toolkit.py:1948`, `2007`, `2153`) — call the helper inside
  their `apply(txn)` body, before `splice_subtree`. On a hit they set
  `txn.noop = True`, splice nothing, stage nothing, skip T3 classification, and return an
  empty `new_node_ids` list.
- **FR-1.3** The returned dict carries `reused: True` plus the pre-existing `doc_id` and
  `revision`. Every non-reused import return keeps `reused: False`, so the key is always
  present and callers need no `.get` default.
- **FR-1.4** An explicit `doc_id=` argument disables the short-circuit: the caller has
  asked for a specific identity and keeps today's behaviour.
- **FR-1.5** `insert_content` (and therefore `import_file` and `import_folder`) propagates
  whatever `insert_markdown` returns, including `reused`, without re-deriving it.
- **FR-1.6** A re-import with *different* bytes under the same name is unaffected: it still
  gets the `-<6 hex>`-suffixed doc_id and a new subtree.

### FR-2 — `max_chars=None` (`issue:2e4dfac0d686` item 1)

- **FR-2.1** The read wrapper in `AgenticRetriever._wrap` charges
  `int(kwargs.get("max_chars") or 12000)`; `None`, `0` and a non-numeric falsy value all
  resolve to `12000`.
- **FR-2.2** A `max_chars` the model *did* supply as a positive int is still honoured
  exactly, and `BudgetExhausted` still returns `BUDGET_MESSAGE` rather than raising.

### FR-3 — Deadline-bound snapshot (`issue:2e4dfac0d686` item 2)

- **FR-3.1** `PageIndexToolkit.agentic_retrieve` performs the tree load + deepcopy in a
  worker thread, wrapped in `asyncio.wait_for` against the remaining deadline.
- **FR-3.2** Exhausting the deadline there returns `timeout_bundle()` with
  `generation=None` (the generation is not yet known at that point), consistent with the
  lock-acquisition timeout above it.

### FR-4 — `provider_error` (`issue:2e4dfac0d686` item 3)

- **FR-4.1** `StopReason` gains `"provider_error"`.
- **FR-4.2** An exception raised by the provider task is caught, logged at `warning` with
  the exception, and converted to `stopped = "provider_error"`; `run()` does not re-raise.
  `asyncio.CancelledError` is NOT swallowed.
- **FR-4.3** The resulting `EvidenceBundle` carries `answer=None`, `grounded=False`,
  `citations=[]`, and the `reads`, `chars_read` and `tool_calls` already accumulated.
- **FR-4.4** `"provider_error"` joins `{"timeout", "max_tool_calls"}` in the guard that
  skips answer parsing and `{"timeout", "max_tool_calls", "parse_error"}` in the guard that
  skips citation validation.

### FR-5 — Documented semantics (`issue:2e4dfac0d686` items 4 and 5)

- **FR-5.1** `AgenticRetriever.run`'s docstring and
  `wiki/knowledge/pageindex-agentic-retrieval.md` state that cap-fill terminates the loop
  immediately: a model that uses exactly `max_tool_calls` reads returns
  `stopped="max_tool_calls"` with no answer, and a provider-done/stop tie in the same tick
  resolves to `max_tool_calls`, discarding a completed answer. The documented remedy is to
  size `max_tool_calls` one above the expected read count.
- **FR-5.2** `PageIndexToolkit.agentic_retrieve`'s docstring and the same wiki page state
  that `_agentic_lock` serialises agentic requests per toolkit instance: concurrency is
  one in flight per instance, and a second caller waits (and may time out against its own
  deadline). Horizontal concurrency means separate toolkit instances.
- **FR-5.3** The wiki page's stop-reason table lists `provider_error`, and gains a
  short "same-source re-import" note pointing at FR-1.


---

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py
- packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py
- packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py
- packages/ai-parrot/tests/knowledge/pageindex/test_agentic_docs.py
- packages/ai-parrot/tests/knowledge/pageindex/test_read_tools.py
- packages/ai-parrot/tests/knowledge/pageindex/test_read_ledger.py
- packages/ai-parrot/tests/knowledge/pageindex/test_citations.py
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py
- packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py
- packages/ai-parrot/tests/knowledge/pageindex/test_segment_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py
- packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py
- packages/ai-parrot/tests/knowledge/pageindex/test_generation.py
- packages/ai-parrot/tests/knowledge/pageindex/test_locks.py
markers: none

## 5. Acceptance Criteria

- **AC-1** Importing the same markdown twice into one tree (no explicit `doc_id`) leaves
  `list_documents` with exactly one entry, the second call returns `reused: True` with the
  first call's `doc_id` and `revision`, and `new_node_ids == []`.
- **AC-2** After that second import the tree's generation is unchanged (no empty
  generation minted) and the structure node count is unchanged.
- **AC-3** The same holds for `import_pdf` (same PDF bytes twice) and `insert_ebook` (same
  sections twice).
- **AC-4** Importing *changed* content under the same name still produces a second document
  with a `-<6 hex>`-suffixed `doc_id` and `reused: False`.
- **AC-5** An explicit `doc_id=` on a same-source re-import still splices (no
  short-circuit).
- **AC-6** A read tool invoked with `max_chars=None` charges the 12000 default and returns
  a clipped `ReadResult` instead of raising `TypeError`.
- **AC-7** `agentic_retrieve` against a tree whose load+deepcopy cannot finish inside the
  remaining deadline returns a `stopped="timeout"` bundle rather than overrunning.
- **AC-8** When the provider task raises, `AgenticRetriever.run` returns an
  `EvidenceBundle` with `stopped == "provider_error"`, `answer is None`,
  `grounded is False`, and `reads` containing the entries charged before the failure.
- **AC-9** `ruff check` and `black --check` pass on every changed file.
- **AC-10** `wiki/knowledge/pageindex-agentic-retrieval.md` documents `provider_error`,
  the cap-fill/tie semantics, the per-instance serialisation limit and same-source
  re-import; the repository's docs gate passes for the declared `api_modules`.

---

## 6. Test Specification

| Test | Asserts |
|---|---|
| `test_reimport_same_markdown_is_reused` | AC-1, AC-2 |
| `test_reimport_same_pdf_is_reused` | AC-3 (`import_pdf`) |
| `test_reimport_same_ebook_is_reused` | AC-3 |
| `test_reimport_changed_content_gets_new_doc_id` | AC-4 |
| `test_explicit_doc_id_skips_reuse_shortcircuit` | AC-5 |
| `test_read_tool_accepts_null_max_chars` | AC-6 |
| `test_agentic_retrieve_times_out_on_snapshot` | AC-7 |
| `test_provider_exception_returns_partial_bundle` | AC-8 |

Existing `test_reimport_does_not_change_snapshot`
(`packages/ai-parrot/tests/knowledge/pageindex/test_agentic_snapshot.py`) must keep
passing — it already encodes the expectation this feature makes true for the tree itself.

---

## 7. Validation Commands

```bash
# from the feature worktree, with PYTHONPATH pinned to the worktree's source
PYTHONPATH=<wt>/packages/ai-parrot/src \
  python -m pytest packages/ai-parrot/tests/knowledge/pageindex -q
ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py \
           packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py
black --check packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py \
              packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py
```

---

## 8. Ledger Linkage

Every task filed for this feature carries the issue it drains:

| Issue | Items | Closed by |
|---|---|---|
| `issue:d34c567792ef` | FR-1 | the task implementing the idempotent re-import |
| `issue:2e4dfac0d686` | FR-2, FR-3, FR-4, FR-5 | the last of its tasks to be verified |

`/sdd-done FEAT-849` closes both by `--resolved-by task:TASK-<NNN>`.
