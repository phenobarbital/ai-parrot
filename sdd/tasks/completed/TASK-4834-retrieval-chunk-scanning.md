# TASK-4834: Scan retrieved vector chunks through the TOOL_OUTPUT pipeline (per chunk, before join)

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4833
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (second half), design-research S4 (verified): retrieved vector
content is folded into the system prompt as `<documents>` (`bots/abstract.py:1492-1493`)
without passing through any guardrail pipeline, so `scan_tool_output=True` alone does
not cover RAG poisoning.

**Per-chunk, not per-context — this matters**: the classifier truncates at 512 tokens,
so scanning the already-joined context would silently skip any poisoned chunk past the
first ~512 tokens. Chunks are joined at exactly two sites (verified):
- `get_vector_context` legacy path: `context = "\n\n".join(context_parts)` (`abstract.py:3408`)
- router path in `_build_vector_context`: `context_str = "\n\n".join(filter(None, context_parts))` (`abstract.py:4117`)

Scan each element of `context_parts` right before those joins. Gate: only when the
bot's TOOL_OUTPUT pipeline contains a guardrail with `scan_tool_output == True`
(TASK-4833) — otherwise zero overhead and bit-identical behavior. Note: when gated
on, every TOOL_OUTPUT guardrail runs on chunks (e.g. `SecretsGuardrail` also scrubs
secrets in retrieved docs) — that is intended.

---

## Scope

- Add `async def _scan_retrieved_chunks(self, chunks: list[str]) -> list[str]` to `AbstractBot`.
- Call it before both joins.
- A chunk that a (custom) guardrail BLOCKs is replaced by
  `"[content removed by guardrail: <reason>]"` (same placeholder as the tool seam).
- Tests.

**NOT in scope**: `_run_output_pipeline` (TASK-4837, same file, later); changing
retrieval/reranking; source metadata.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | helper + 2 call sites |
| `packages/ai-parrot/tests/unit/test_guardrails_retrieval_scan.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in bots/abstract.py:
from .guardrails.base import Guardrail, GuardrailContext, GuardrailStage  # abstract.py:116
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
self._guardrail_pipelines: Dict[GuardrailStage, GuardrailPipeline]   # :693 (built in __init__)
async def get_vector_context(...)                                       # :3236
    context_parts = []                                                  # :3397
    context = "\n\n".join(context_parts)                                # :3408  <- scan before
async def _build_vector_context(...) -> Tuple[str, Dict[str, Any]]     # :3931
    context_str = "\n\n".join(filter(None, context_parts))              # :4117  <- scan before
# GuardrailPipeline.guardrails -> tuple[Guardrail, ...]  (pipeline.py:127)
# GuardrailPipeline.run(content, ctx) -> PipelineOutcome(content, blocked, reason, flag_reports)
# Tool-seam placeholder precedent: tools/abstract.py — f"[content removed by guardrail: {outcome.reason}]"
```

### Does NOT Exist
- ~~`AbstractBot._scan_retrieved_chunks`~~ — created here.
- ~~any guardrail run on vector context today~~.
- ~~`GuardrailStage.RETRIEVAL`~~ — no new stage; reuse TOOL_OUTPUT with `tool_name="vector_retrieval"`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_guardrails_retrieval_scan.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.get_vector_context",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._build_vector_context"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the helper next to `_build_vector_context` — *why*: one gate, two call sites.
2. Insert the call before each join — *why*: per-chunk scanning defeats 512-token truncation.
3. Tests with a stub bot (construct via `__new__` and set `_guardrail_pipelines`, as other AbstractBot unit tests do).

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _build_vector_context(' abstract.py)
# BEFORE — insert above `    async def _build_vector_context(` (verified: abstract.py:3931)
    async def _scan_retrieved_chunks(self, chunks: List[str]) -> List[str]:
        """Run each retrieved chunk through the TOOL_OUTPUT guardrail pipeline (FEAT-761).

        Gated on a TOOL_OUTPUT guardrail with ``scan_tool_output`` enabled —
        otherwise returns ``chunks`` unchanged (zero overhead). Per chunk on
        purpose: the injection classifier truncates at 512 tokens, so scanning
        the joined context would miss poisoned chunks past the first window.

        Args:
            chunks: Retrieved chunk texts, in retrieval order.

        Returns:
            The (possibly wrapped/redacted) chunks, same order and length.
        """
        pipeline = self._guardrail_pipelines.get(GuardrailStage.TOOL_OUTPUT)
        if pipeline is None or not any(
            getattr(g, "scan_tool_output", False) for g in pipeline.guardrails
        ):
            return chunks
        # FILL IN: for each non-empty str chunk run pipeline.run(chunk, GuardrailContext(stage=TOOL_OUTPUT,
        # agent_name=self.name, tool_name="vector_retrieval", extras={"chatbot_id": str(self.chatbot_id)}));
        # blocked -> placeholder; else outcome.content or chunk; log count of transformed chunks at DEBUG
        # (never the content) — bounded by "same order and length"
```
```python
# occurrences: 1 (verified: grep -c '            context = "\\n\\n".join(context_parts)' abstract.py)
# BEFORE — insert above `            context = "\n\n".join(context_parts)` (verified: abstract.py:3408)
            context_parts = await self._scan_retrieved_chunks(context_parts)
```
```python
# occurrences: 1 (verified: grep -c '        context_str = "\\n\\n".join(filter(None, context_parts))' abstract.py)
# BEFORE — insert above `        context_str = "\n\n".join(filter(None, context_parts))` (verified: abstract.py:4117)
        context_parts = await self._scan_retrieved_chunks(context_parts)
```
**Why**: `context_parts` items are already `str` at both sites (`result.content` /
`str(r.content)`); the helper preserves length so source bookkeeping is unaffected.

### `packages/ai-parrot/tests/unit/test_guardrails_retrieval_scan.py` (CREATE)
```python
"""FEAT-761 TASK-4834 — per-chunk retrieval scanning."""
import pytest

from parrot.bots.abstract import AbstractBot
from parrot.bots.guardrails.base import GuardrailStage
from parrot.bots.guardrails.pipeline import GuardrailPipeline

# FILL IN: stub bot via AbstractBot.__new__ + minimal attrs (name, chatbot_id, logger, _guardrail_pipelines);
# tests: no scanner -> identity (same list object or equal) and pipeline.run never called;
# scanner present -> only the poisoned chunk changes; order/length preserved; a chunk late in a long list
# is still scanned; BLOCKing custom guardrail -> placeholder; empty chunks skipped
```

### FILL IN checklist
- [ ] helper loop
- [ ] tests

---

## Acceptance Criteria

- [ ] With no `scan_tool_output` guardrail, retrieval output is bit-identical and the pipeline is never invoked.
- [ ] With it, each chunk is scanned individually before the join (both sites).
- [ ] Order and count of chunks preserved; no content in logs.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_retrieval_scan.py -q`

---

## Test Specification

See CREATE block.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Confirm TASK-4833 is `done`; re-verify anchors.
3. Mark `in-progress`; implement; complete `# FILL IN:`. `bots/abstract.py` is hot: never mutate `_llm_kwargs` (rebind), touch only the three listed spots.
4. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only listed files; `scripts/sdd/close_task.sh TASK-4834 agent-security-guardrails verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Seat: opus · Backend: native · Attempts: 1)
**Date**: 2026-10-27
**Notes**: AbstractBot._scan_retrieved_chunks added; 5 tests; merge-tier validation green. Test uses a concrete _StubBot subclass because AbstractBot has abstract methods. Closed via close_task.sh (no durable review-evidence artifact writable).

**Deviations from spec**: test builds a concrete subclass instead of AbstractBot.__new__ (abstract methods).
