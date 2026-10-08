# TASK-2669: Contradiction protocol (§22)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2661, TASK-2662, TASK-2667
**Assigned-to**: unassigned
**Parallel**: true

---

## Context

Spec Module 11. Contradictions are first-class objects, never silently overwritten
(rule #8, §22). Detect materially incompatible claims BEFORE updating knowledge.

## Scope

- `nodes/contradictions.py` + `render/contradiction.py`: detect conflicts between the new meeting's claims and current project/Wiki knowledge (strong-tier client + GraphIndex retrieval).
- Create/update `Wiki/Contradictions/<Title>.md` (exact §22 template): record each claim + its source, impact, severity, `status: open` unless a source resolves it.
- Link the contradiction from every affected project/entity/concept/source page; add to `Wiki/Contradictions/index.md`; high-impact → `Wiki/Review Queue.md`.
- Never choose a winner by recency; resolve only with explicit evidence or user instruction.

**NOT in scope**: project reconcile (TASK-2667 calls this first, per §27 step 9).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/contradictions.py` | CREATE | detection + linking |
| `.../wiki_ingest/render/contradiction.py` | CREATE | §22 renderer |
| `packages/ai-parrot/tests/unit/test_wiki_kb_contradictions.py` | CREATE | detection + no-recency tests |

## Codebase Contract (Anti-Hallucination)
### Existing Signatures to Use
```python
async def invoke(self, prompt, *, output_type=None, ...) -> InvokeResult   # clients/base.py:1747
async def create_note(...); async def update_note(...); async def search_notes(...)  # tools/obsidian.py:439/471/300
```
### Does NOT Exist
- ~~auto-resolution by recency~~ — forbidden (§22 step 9).

## Implementation Notes
- Run detection before any project update (§27 step 9). Preserve both claims + sources.
- Severity: low/medium/high/critical (§10.5).

## Acceptance Criteria
- [ ] Incompatible claims produce a linked §22 contradiction page; both claims preserved.
- [ ] Never resolved by recency; high-impact adds a review item.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_conflict_creates_linked_contradiction(): ...
async def test_not_resolved_by_recency(): ...
```

### Completion Note

`render/contradiction.py`: `render_contradiction_page()` reproduces §22
verbatim — Claim A/B (text/source/date), Why They Conflict, Impact,
Resolution Needed, and Resolution (defaults to "Leave unresolved until
supported." — structurally never populated from recency).

`nodes/contradictions.py`: `detect_contradictions()` — a single
strong-tier `invoke(output_type=ContradictionDetectionResult)` call
comparing existing project/Wiki claims against the new meeting's claims,
returning zero or more `ConflictCandidate`s (skips the LLM call entirely
when either side is empty). `run_contradiction_detection()` renders one
page per conflict via `build_contradiction_page()`, always
`status="open"`; `severity in {"high","critical"}` attaches a
`contradiction` review-item draft (§22 rule 8). If the LLM cites an
`existing_claim_text` that doesn't match anything actually supplied, the
conflict is dropped rather than fabricating a source/date for Claim A
(rule #12) — never guessed. `affected_pages` (§22 rule 6 — link from
every affected project/entity/concept/source page) is caller-supplied,
since only the orchestrator (Module 6) knows which pages this operation
touched.

Verified: `pytest packages/ai-parrot/tests/unit/test_wiki_kb_contradictions.py`
(5 passed — linked contradiction creation, never-resolved-by-recency
with the older claim preserved verbatim, no-conflict produces no pages,
empty-input skips the LLM call, an unrecognized cited claim is dropped
not fabricated); `ruff check` clean; `mypy` clean; full wiki-kb suite (71
tests) stays green.
