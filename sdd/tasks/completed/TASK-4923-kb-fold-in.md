# TASK-4923: KB fold-in — `_build_kb_context` delegates to the resolver (U5)

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4919, TASK-4922
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7, U5, AC11, AC24. This is the highest-blast-radius edit of the feature: `AbstractBot` is the base
of every bot, `bots/abstract.py` is ~5 400 lines and `_build_kb_context` has had no tests for 180 days. Rule:
**pin first, then change**. The pinned fixture test is written and passing *before* the new branch is added.

Design (task-time, chosen to keep the legacy body byte-for-byte): add a keyword-only private flag
`_bypass_resolver: bool = False` to `_build_kb_context`. When the flag is false and the bot carries a
`knowledge_resolver` with a `kb` handle, return `await resolver.search_kb(self, question, …)`. Add
`_legacy_build_kb_context(...)`, a one-line wrapper that calls `_build_kb_context(..., _bypass_resolver=True)` —
this is what `KnowledgeResolver.search_kb` (TASK-4919) calls, so there is no recursion. Verified: no subclass
overrides `_build_kb_context`; its six callers (`bots/base.py:414,1323,2047`, `bots/data.py:1490`,
`bots/voice.py:606,829`) pass positional/keyword args that stay valid.

`register_kb` additionally calls `knowledge_resolver.invalidate()` when present.

---

## Scope

- Write `test_kb_context_resolver.py` with the pinned legacy-output fixture FIRST and make it pass on the
  unmodified code.
- Modify `_build_kb_context` (new flag + 4-line branch), add `_legacy_build_kb_context`, extend `register_kb`.
- Add the AC24 test: a plain agent (no `knowledge_resolver`) is unaffected.

**NOT in scope**: anything else in `abstract.py`; `ExpertAgent` (TASK-4924); the request-time knowledge rendering gap
noted in TASK-4918 (record what you observe in the Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Resolver branch, legacy wrapper, invalidate on register |
| `packages/ai-parrot/tests/bots/test_kb_context_resolver.py` | CREATE | Pinned legacy output + delegation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.abstract import AbstractBot   # verified: parrot/bots/abstract.py (class AbstractBot)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
self.knowledge_bases: List[AbstractKnowledgeBase] = []          # line 583
def register_kb(self, kb: AbstractKnowledgeBase):               # line 1189 — last line 1198: self.logger.debug(f"Registered KB: …")
async def _build_kb_context(self, question: str, user_id: Optional[str] = None,
                            session_id: Optional[str] = None, ctx: Optional[RequestContext] = None
                            ) -> Tuple[str, Dict[str, Any]]:     # line 3889
    """Compute KB context and metadata."""                        # line 3896
    kb_context = ""                                               # line 3898
    metadata = {"activated_kbs": []}
    if not self.knowledge_bases: return kb_context, metadata      # line 3901
# KnowledgeResolver (TASK-4919): has_handle(kind: str) -> bool; async search_kb(bot, question, *, user_id, session_id, ctx)
```

### Does NOT Exist
- ~~`AbstractBot.knowledge_resolver`~~ — never declared on the base class; read it with `getattr(self, "knowledge_resolver", None)` (spec §6).
- ~~an override of `_build_kb_context` in any subclass~~ — verified none at `9d5a6476b8`.
- ~~a new ContextVar for the bypass~~ — forbidden by AC16; use the keyword-only parameter.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_kb_context_resolver.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._build_kb_context",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.register_kb"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Run `wikitoolkit symbols blast _build_kb_context` before editing and paste the result in the Completion Note.
- The legacy body below the new branch must not change by a single character (diff review).
- The pinned fixture: a minimal bot with two fake KBs (`always_active=True`, deterministic `search`), `use_kb=False`,
  `use_kb_selector=False`; capture `(kb_context, metadata)` once on unmodified code and hard-code it in the test.

---

## Implementation Blueprint

### Steps (in order)
1. Write and pass the pinned test on unmodified code — *why*: proves the legacy branch never moves (AC11).
2. Add the flag + branch, the wrapper, the `register_kb` line.
3. Add the delegation and AC24 tests.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY) — signature + branch
```python
# occurrences: 1 (verified: grep -c '        """Compute KB context and metadata."""' packages/ai-parrot/src/parrot/bots/abstract.py)
# FILL IN: disambiguate not needed (count 1). Two edits around the anchor (verified: abstract.py:3889-3898):
# (a) in the signature, after `        ctx: Optional[RequestContext] = None,` add the line:
        *,
        _bypass_resolver: bool = False,
# (b) AFTER — insert below `        """Compute KB context and metadata."""` (line 3896):
        resolver = None if _bypass_resolver else getattr(self, "knowledge_resolver", None)
        if resolver is not None and resolver.has_handle("kb"):
            # FEAT-778 U5: experts route the KB search through their KnowledgeResolver.
            return await resolver.search_kb(self, question, user_id=user_id, session_id=session_id, ctx=ctx)
```
**Why**: the flag is keyword-only and private, so the six existing callers are untouched; the resolver calls back
through the wrapper with the flag set, which runs the original body.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY) — wrapper
```python
# AFTER — insert as a new method directly ABOVE `    async def _build_kb_context(` (verified: abstract.py:3889)
    async def _legacy_build_kb_context(
        self,
        question: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ctx: Optional[RequestContext] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """The pre-FEAT-778 KB search, bypassing any KnowledgeResolver (called by KnowledgeResolver.search_kb)."""
        return await self._build_kb_context(question, user_id, session_id, ctx, _bypass_resolver=True)

```

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY) — register_kb
```python
# occurrences: 1 (verified: grep -c '        self.logger.debug(f"Registered KB: {kb.name} with priority {kb.priority}")' packages/ai-parrot/src/parrot/bots/abstract.py)
# AFTER — insert below that line (verified: abstract.py:1198)
        resolver = getattr(self, "knowledge_resolver", None)
        if resolver is not None:
            resolver.invalidate()  # FEAT-778: a new KB changes the expert's kb handle
```

### FILL IN checklist
- [ ] Pinned fixture values captured from unmodified code.
- [ ] Blast-radius output recorded in the Completion Note.

---

## Acceptance Criteria

- [ ] AC11 — a bot without a resolver returns exactly the pinned `(kb_context, metadata)`; a bot with a resolver
      that has a `kb` handle calls `resolver.search_kb` once and returns its result unchanged in shape.
- [ ] AC24 (KB part) — a plain agent has no `knowledge_resolver` attribute and its output equals the pinned fixture.
- [ ] `register_kb` calls `invalidate()` only when a resolver is present.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/abstract.py` reports nothing new.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_kb_context_resolver.py -q`
- `pytest packages/ai-parrot/tests/bots/test_knowledge_index_flags.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_kb_context_resolver.py
async def test_build_kb_context_legacy_path_unchanged(): ...       # FILL IN: pinned fixture
async def test_build_kb_context_delegates_to_resolver(): ...       # FILL IN: fake resolver(has_handle=True)
async def test_resolver_without_kb_handle_uses_legacy(): ...       # FILL IN
async def test_legacy_wrapper_bypasses_resolver(): ...             # FILL IN: no recursion
def test_register_kb_invalidates_resolver(): ...                   # FILL IN
async def test_plain_yaml_agent_unaffected(): ...                  # FILL IN: AC24 KB part
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4923 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker; Seat: gpt-5.6-sol (codex) · Attempts: 1
**Date**: 2026-10-30
**Notes**: Merged; task-tier and chunk merge-tier validation green.

**Deviations from spec**: none
