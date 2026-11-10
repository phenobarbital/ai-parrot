# TASK-5367: LLM passes: bottom-up summaries, document description and run_llm_passes

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5366
**Assigned-to**: unassigned

---

## Context

Second half of spec Module 2: *bottom-up summaries*, `describe_document`, and the `run_llm_passes` driver that applies the
normative stamp lifecycle (§2 "Stamp lifecycle and retry cache"). This is where first-run work actually executes before
any stamp is finalized (ledger findings `issue:799850fae51a`, `issue:0365d1296ae9`, `issue:8fa23e962b2d` in spec §9).

## Scope

- Add `summarize_leaf`, `compose_parent`, `describe_document`, `run_llm_passes`.
- Tests: `test_summaries_inline_llm_composed`, `test_first_run_executes_before_stamping`, `test_stamp_capability_upgrade`,
  `test_summaries_deferred_then_requested`, `test_retry_cache_dependencies`, `test_framed_document_description`.

**NOT in scope**: finalizing stamps or validating (toolkit, TASK-5370/5371 call `validate_candidate`/`finalize_stamps`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | MODIFY | summarize_leaf, compose_parent, describe_document, run_llm_passes |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py` | MODIFY | M2 unit tests (second half) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already at the top of optimizer_llm.py (TASK-5366):
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text  # verified: framing.py:10,33,39
from parrot.knowledge.pageindex.builder import _LLM_SEMAPHORE, _limited_gather  # verified: builder.py:75,80
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, SegmentAddress, SegmentRead  # verified: segments.py:33,59,71,97
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS  # verified: layout_structure.py:23
from parrot.knowledge.pageindex.utils import create_clean_structure_for_description  # verified: utils.py:713
from parrot.knowledge.pageindex.optimizer import (  # TASK-5364/5365
    KeyItem, OptimizePlan, OptimizerSettings, Revisions, is_stamped, owned_tokens, pass_cache_key, pass_input, split_at,
)
```

### Existing Signatures to Use
```python
# framing.py
DATA_FRAMING_INSTRUCTION: str                                  # :10 — use verbatim as the system prompt
def frame_segments(reads, *, source=...) -> str                # :33 — check exact kwargs before use
def frame_text(text, *, source=...) -> str                     # :39 — neutralizes embedded closing tags
# builder.py
_LLM_SEMAPHORE: ContextVar[Optional[asyncio.Semaphore]]       # :75
async def _limited_gather(coros, *, return_exceptions=False) -> list  # :80 (plain gather when the var is unset)
# llm_adapter.py
class PageIndexLLMAdapter:                                     # :42
    async def ask(...)                                         # :61
    async def ask_structured(..., output_type=<pydantic model>) # :99 — check the exact parameter names
# bookstore/library.py
class _NullAdapter: model = None; client = None; ask() -> ""; ask_structured raises RuntimeError  # :150-176
# segments.py
class SegmentRead(BaseModel): address, seq, kind, text, start, end, truncated, flags   # :97
class SegmentAddress(BaseModel): doc_id, revision, seq, page, ordinal, section          # :71
# builder.py: build_page_index sets _LLM_SEMAPHORE at :1603 — mirror it: set only when .get() is None, reset in finally
```

### Does NOT Exist
- ~~`toolkit.has_llm` as the live gate~~ — True for Bookstore's `_NullAdapter` (`toolkit.py:377`); use `adapter_is_live`
- ~~framing in `generate_node_summary` / `generate_prefix_summaries` / `generate_doc_description`~~ — all unframed legacy; never call them here
- ~~a word cap in any existing summary prompt~~ — none exists; `summary_max_words` is new
- ~~proposals keyed by echoed text~~ — proposals are keyed by `seq` only (spec §7)
- ~~`builder.generate_doc_description` on this path~~ — legacy, unframed; `describe_document` replaces it for optimized imports

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_limited_gather",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/framing.py#frame_text",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#create_clean_structure_for_description"
  ]
}
```

---

## Implementation Notes

- Summaries deepest first, one `_limited_gather` per level. Inline when `owned_tokens <= inline_summary_tokens`
  (`kind="inline"`, no call, deterministic even with a live adapter). Larger leaf: framed call with the word cap
  (`"llm"`). Parent: composed from child summaries + own segments + key_items (`"composed"`); without a live adapter
  `"<own text>. Subsections cover: <child titles>"` (deterministic mode).
- Effective live mode = `settings.llm_passes and adapter_is_live(adapter)`. `report.llm_passes`:
  `"ran"` | `"skipped (no model)"` | `"skipped (disabled)"`.
- Pending stamps: put a `PassStamp` into `plan.pending_stamps[id(node)][pass]` only after the pass succeeded; never for
  failed/unavailable/unrequested passes. `with_summaries=False` leaves summaries pending. Successful empty proposals count.
- Retry cache: key = `pass_cache_key(...)`; cache only accepted outputs; revalidate anchors against the current candidate.
- `describe_document`: `frame_text(json.dumps(create_clean_structure_for_description(structure)), source="document structure")`,
  instructions outside the frame, `DATA_FRAMING_INSTRUCTION` as system prompt; returns `""` without a live adapter.

---

## Implementation Blueprint

**Steps (in order)**
1. Append the block after `propose_key_items` in `optimizer_llm.py`. 2. Fill bodies. 3. Add the six tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` (MODIFY)
```python
# AFTER — append below `async def propose_key_items(` and its body
# occurrences: 1 (verified after TASK-5366: grep -c 'async def propose_key_items' optimizer_llm.py)

async def summarize_leaf(node: dict, revision: DocumentRevision, adapter: Optional[Any],
                         settings: OptimizerSettings) -> tuple[str, str]:
    """``(summary, kind)``: ``inline`` when owned tokens <= inline_summary_tokens, else ``llm`` (framed, word cap)."""
    # FILL IN — bounded by AC-9 (<= summary_max_words * 1.2 words; trim if longer)


async def compose_parent(node: dict, revision: DocumentRevision, adapter: Optional[Any],
                         settings: OptimizerSettings) -> tuple[str, str]:
    """``composed`` from child summaries + own segments + key_items; deterministic fallback without a live adapter."""
    # FILL IN


async def describe_document(structure: Any, adapter: Any) -> str:
    """Framed document description (live adapter only); never calls builder.generate_doc_description."""
    if not adapter_is_live(adapter):
        return ""
    payload = json.dumps(create_clean_structure_for_description(structure), ensure_ascii=False)
    framed = frame_text(payload, source="document structure")
    # FILL IN: prompt = <instruction text> + "\n\n" + framed; await adapter.ask(..., system_prompt=DATA_FRAMING_INSTRUCTION)
    #          (check PageIndexLLMAdapter.ask parameter names at llm_adapter.py:61)


async def run_llm_passes(plan: OptimizePlan, revisions: Revisions, adapter: Optional[Any],
                         settings: OptimizerSettings, *, with_summaries: bool = True) -> None:
    """Headings -> key_items -> summaries (deepest first); collect pending stamps; never finalize them."""
    token = None
    if _LLM_SEMAPHORE.get() is None:
        token = _LLM_SEMAPHORE.set(asyncio.Semaphore(16))
    try:
        ...  # FILL IN: spec §3 M2 run_llm_passes docstring + Implementation Notes above
    finally:
        if token is not None:
            _LLM_SEMAPHORE.reset(token)
```
Add `import asyncio` and `from datetime import datetime, timezone` (for `PassStamp.at`) to the module imports.
**Why**: the ContextVar dance must mirror `build_page_index` so PDF imports (already inside its context) share the gate.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py` (MODIFY)
```python
# AFTER — append at end of file
def test_summaries_inline_llm_composed(): ...        # FILL IN
def test_first_run_executes_before_stamping(): ...   # FILL IN
def test_stamp_capability_upgrade(): ...             # FILL IN
def test_summaries_deferred_then_requested(): ...    # FILL IN
def test_retry_cache_dependencies(): ...             # FILL IN
def test_framed_document_description(): ...          # FILL IN: patch builder.generate_doc_description and assert not called
```

**FILL IN checklist**
- [ ] four function bodies  - [ ] six tests (async ones marked `@pytest.mark.asyncio`)

---

## Acceptance Criteria

- [ ] AC-7 (pass part): first-run eligible passes execute; unavailable/failed/unrequested passes produce no pending stamp;
      changed child summary/key_items or execution context miss the cache.
- [ ] AC-9: inline leaves make no call; parents after children; word cap within 20 %; deterministic with `_NullAdapter`.
- [ ] AC-12: summary and description prompts framed; legacy description helper never called.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py -q`

---

## Test Specification

Spec §4 rows `test_summaries_inline_llm_composed`, `test_first_run_executes_before_stamping`,
`test_stamp_capability_upgrade`, `test_summaries_deferred_then_requested`, `test_retry_cache_dependencies`,
`test_framed_document_description`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5367 — LLM passes: bottom-up summaries, document description and run_llm_passes`.

---

## Completion Note

**Completed**: 2026-11-09 | **Implementation commit**: 6ed793caed

Delivered via sdd-coder pool (merged). Scope: optimizer LLM summaries and run passes.
Validation: merge-tier — 10 passed, exit 0.
Deviations: none noted.

