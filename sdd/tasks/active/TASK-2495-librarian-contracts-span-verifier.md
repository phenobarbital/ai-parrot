# TASK-2495: Librarian contracts, deterministic `SpanVerifier`, append-only `SuppressionLog`

**Feature**: FEAT-449 — Legal Librarian Answer Layer
**Spec**: `sdd/specs/legal-librarian-answer-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2492, TASK-2494
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 — the heart of the feature. The one-line invariant (R2):
*"the system cannot assert anything about the corpus without a verifiable span
reference; without a citation, the answer is 'no encontré'"*. This task ships
the Pydantic contracts (final `LegalAnswer` + LLM-facing `DraftAnswer`), the
**pure-code** existence gate (`SpanVerifier` — no LLM, no network, fully
unit-testable) and the append-only suppression log. **The LLM never emits
offsets**: it emits `payload_key` + verbatim `quote`; the verifier locates the
quote deterministically and derives `start/end`.

Blocks TASK-2497 and TASK-2499.

---

## Scope

- Create package `parrot_tools/legal/librarian/` (`__init__.py`).
- `models.py`: `SpanRef`, `ConflictNote`, `ReadingNote`, `LegalAnswer`,
  `SuppressionRecord`, `DraftSpan`, `DraftReadingNote`, `DraftConflictNote`,
  `DraftAnswer`, `PayloadEntry` — spec §2 Data Models + §3 M4 verbatim.
  Key formats: `payload_key = f"{articulo_key}:{version_n}"`; span key =
  `f"{payload_key}:{start}-{end}"`. Provide a `span_key(ref: SpanRef) -> str`
  helper.
- `verifier.py`: `class SpanVerifier` with the single method
  `verify(draft, retrieval_set, *, as_of, materias, execution_id, user_id=None)
  -> tuple[LegalAnswer, list[SuppressionRecord]]` implementing the ordered
  checks (first failure wins, reason exact):
  1. `payload_key not in retrieval_set` → `span_not_found`
  2. `seal_hash(entry.payload) != entry.content_hash` → `hash_mismatch`
  3. `entry.payload.find(quote) == -1` → `quote_mismatch`; else offsets =
     first occurrence (document in docstring).
  Then: reading notes lose pruned spans; a note with zero surviving spans is
  suppressed (`anchor_lost`, `suppressed_count += 1`); conflict notes with
  either side pruned are dropped + recorded (`anchor_lost`); `reading_order`
  filtered silently to surviving payload keys; surviving `DraftSpan`s become
  `SpanRef`s (kind/id/version_n/url/as_of/basis from `PayloadEntry`);
  `dossier` = deduped surviving `SpanRef`s in `retrieval_set` insertion
  order; empty dossier ⇒ `LegalAnswer(not_found=[corpus-scoped statement from
  materias + as_of], reading_guide=[], conflicts=[], dossier=[])`. The class
  docstring carries the R2 invariant verbatim.
- `suppression.py`: `class SuppressionLog` with exactly ONE public method
  `async def append(self, record: SuppressionRecord) -> None` inserting into
  `span_suppressions` via `OntologyGraphStore.insert_document` (or the
  tenant connection) with `suppression_id = f"{execution_id}:{seq}"` (seq
  maintained per log instance). No update/delete/list methods.
- Unit tests (deterministic): `test_span_verifier_hash_mismatch_prunes`,
  `test_span_verifier_quote_mismatch_prunes`,
  `test_span_verifier_unknown_key_prunes`,
  `test_reading_note_loses_all_anchors_is_suppressed`,
  `test_conflict_with_pruned_side_dropped`, `test_empty_dossier_is_no_encontre`,
  `test_offsets_are_first_occurrence_and_slice_equals_quote`,
  `test_suppression_log_append_only` (fake store records inserts; assert no
  other public methods).

**NOT in scope**: `as_of` extraction and `search_articles` (TASK-2496); the
flow/agent that calls the verifier (TASK-2497); groundedness atom check
(TASK-2497 — but the `atom_contradicted` reason literal IS defined here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/__init__.py` | CREATE | exports |
| `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/models.py` | CREATE | all contracts |
| `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/verifier.py` | CREATE | `SpanVerifier` |
| `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/suppression.py` | CREATE | `SuppressionLog` |
| `packages/ai-parrot-tools/tests/legal/test_librarian_models.py` | CREATE | contract/validator tests |
| `packages/ai-parrot-tools/tests/legal/test_span_verifier.py` | CREATE | gate tests |
| `packages/ai-parrot-tools/tests/legal/test_suppression_log.py` | CREATE | append-only tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-27 against `dev` (+ TASK-2492/2494 deliverables).

### Verified Imports
```python
from parrot_tools.legal.boe.hashing import seal_hash, HASH_NORM_VERSION    # TASK-2492
from parrot_tools.legal.boe.models import ArticleVersion                   # boe/models.py:16
from parrot.knowledge.ontology.graph_store import OntologyGraphStore       # graph_store.py:34
from parrot.knowledge.ontology.schema import TenantContext                 # schema.py:406
```

### Existing Signatures to Use
```python
# graph_store.py — generic document helpers usable by SuppressionLog
async def insert_document(self, ctx: TenantContext, collection: str, doc: dict[str, Any], ...)  # :570 — READ the exact signature
async def ensure_collection(self, ctx, name, ...)                                                # :490
# span_suppressions is declared as the SpanSuppression entity collection (TASK-2494) and
# created by initialize_tenant; SuppressionLog must NOT create collections itself.

# security/audit_ledger.py:296,338 — NOT used here:
class AuditLedger:
    async def append(*, user_id, channel, tool, provider, credential_material) -> AuditLedgerEntry
# requires credential_material + KMS fingerprints — a suppression has none (spec §8).
```

### Does NOT Exist
- ~~`parrot_tools.legal.librarian`~~ — created by this task.
- ~~LLM-emitted `start`/`end` offsets~~ — `DraftSpan` has `payload_key` + `quote` ONLY; offsets are derived by `payload.find(quote)`. Any design that has the LLM produce integers is wrong.
- ~~`SuppressionLog.list()` / `.delete()` / `.update()`~~ — append-only by construction.
- ~~`AuditLedger` generic event method~~ — none exists; do not route suppressions through it.
- ~~`EvidenceIndex` as a span verifier~~ — atom-based only; the existence gate is this task's new code.
- ~~Fuzzy/normalized quote matching~~ — exact `str.find` on the stored normalized payload; the quote must be verbatim.

---

## Implementation Notes

### Pattern to Follow
```python
# models.py — final contracts (spec §2)
class SpanRef(BaseModel):
    kind: Literal["norma", "articulo"]
    id: str; version_n: int | None; start: int; end: int; quote: str
    content_hash: str; hash_norm_version: int; title: str; url: str
    as_of: date | None; basis: Literal["retrieval", "traversal"]

class SuppressionRecord(BaseModel):
    execution_id: str; suppressed_text: str; claimed_anchors: list[str]
    reason: Literal["span_not_found", "hash_mismatch", "quote_mismatch", "anchor_lost", "atom_contradicted"]
    user_id: str | None; created_at: datetime

class PayloadEntry(BaseModel):
    payload_key: str; payload: str; content_hash: str; title: str; url: str
    as_of: date; version_n: int; articulo_key: str; basis: Literal["retrieval", "traversal"]

# Draft (LLM-facing): DraftSpan(payload_key, quote); DraftReadingNote(text, spans[min 1], basis);
# DraftConflictNote(span_a, span_b, note); DraftAnswer(reading_order, conflicts, reading_guide, not_found)
```

```python
# verifier.py — per-span check order (spec §3 M4)
entry = retrieval_set.get(span.payload_key)
if entry is None:                          reason = "span_not_found"
elif seal_hash(entry.payload) != entry.content_hash:  reason = "hash_mismatch"
else:
    idx = entry.payload.find(span.quote)
    if idx == -1:                          reason = "quote_mismatch"
    else: start, end = idx, idx + len(span.quote)
```

### Key Constraints
- Pure functions: `verify` is sync, no I/O. `SuppressionLog.append` is the
  only async piece.
- `LegalAnswer.disclaimer` and `materias`/`as_of` are filled by the verifier
  from its kwargs (caller passes them); a constant default disclaimer string
  lives in `models.py`.
- `not_found` statements are corpus-scoped ("no encontré en el corpus BOE
  para las materias X a fecha Y"), never ontological ("no existe tal ley").
- Deduplicate `SpanRef`s by span key; preserve first-seen order.
- Google-style docstrings; Pydantic v2 (`ConfigDict`, `model_validator`).

### References in Codebase
- `packages/ai-parrot/src/parrot/agents/security_advisor.py` — `_audit_citations` (grounded read-only agent precedent)
- `packages/ai-parrot-tools/tests/legal/conftest.py` — `FakeGraphStore` (extend with `insert_document` if absent)

---

## Acceptance Criteria

- [ ] Tampered payload (hash ≠ stored) ⇒ span pruned + `SuppressionRecord(reason="hash_mismatch")`
- [ ] Quote absent from payload ⇒ pruned + `quote_mismatch`; unknown `payload_key` ⇒ `span_not_found`
- [ ] Surviving spans satisfy `entry.payload[ref.start:ref.end] == ref.quote`
- [ ] A reading note whose every span is pruned is removed, `suppressed_count` incremented, record appended with `claimed_anchors`
- [ ] Empty dossier ⇒ `not_found` non-empty, `reading_guide == []`, no exception
- [ ] `SuppressionLog` exposes only `append`; it never creates/updates/deletes
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/ -v`
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/legal/librarian/`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_span_verifier.py
from datetime import date
from parrot_tools.legal.boe.hashing import seal_hash
from parrot_tools.legal.librarian.models import DraftAnswer, DraftReadingNote, DraftSpan, PayloadEntry
from parrot_tools.legal.librarian.verifier import SpanVerifier

TEXT = "El plazo será de tres meses. El plazo se cuenta desde la notificación."

def entry(text=TEXT, h=None):
    return PayloadEntry(payload_key="BOE-A-2000-1:art1:0", payload=text,
                        content_hash=h or seal_hash(text), title="t", url="u",
                        as_of=date(2024, 1, 1), version_n=0, articulo_key="BOE-A-2000-1:art1", basis="retrieval")

def draft(key="BOE-A-2000-1:art1:0", quote="tres meses"):
    return DraftAnswer(reading_order=[key], conflicts=[], not_found=[],
                       reading_guide=[DraftReadingNote(text="Plazo de tres meses.", basis="llm",
                                                       spans=[DraftSpan(payload_key=key, quote=quote)])])

def run(d, rs):
    return SpanVerifier().verify(d, rs, as_of=date(2024, 1, 1), materias=["civil"], execution_id="x")

def test_span_verifier_hash_mismatch_prunes():
    ans, recs = run(draft(), {"BOE-A-2000-1:art1:0": entry(h="deadbeef")})
    assert ans.dossier == [] and recs[0].reason == "hash_mismatch" and ans.suppressed_count == 1

def test_span_verifier_quote_mismatch_prunes():
    ans, recs = run(draft(quote="cuatro meses"), {"BOE-A-2000-1:art1:0": entry()})
    assert recs[0].reason == "quote_mismatch"

def test_offsets_are_first_occurrence_and_slice_equals_quote():
    ans, recs = run(draft(quote="El plazo"), {"BOE-A-2000-1:art1:0": entry()})
    ref = ans.dossier[0]
    assert (ref.start, ref.end) == (0, 8) and TEXT[ref.start:ref.end] == ref.quote and recs == []

def test_empty_dossier_is_no_encontre():
    ans, _ = run(draft(key="nope:0"), {})
    assert ans.dossier == [] and ans.reading_guide == [] and ans.not_found
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 Data Models, §3 M4, §6 Does NOT Exist, §7)
2. **Check dependencies** — TASK-2492 and TASK-2494 must be completed
3. **Verify the Codebase Contract** — read `graph_store.py:482-620` for the exact document-helper signatures before writing `SuppressionLog`
4. **Update status** in `sdd/tasks/index/legal-librarian-answer-layer.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2495-librarian-contracts-span-verifier.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
