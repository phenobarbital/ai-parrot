# TASK-3708: Deterministic assemble_card + serial qualifier parsing (M5 Q7)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3705, TASK-3707
**Assigned-to**: unassigned

> Parallelism: modifies manuals/carding.py created by TASK-3707 (same file — serialized) and consumes its CardingDraft; calls pair_figures from TASK-3705 (manuals/figures.py).

---

## Context

Spec §3 **Module 5**, second half: the **deterministic** `assemble_card` (G1 — Python decides, the LLM only
proposed) plus Q7 serial applicability parsing (G10, **AC20**). `assemble_card` resolves parts
(`similarity ≥ 0.85` else literal + `resolved=False`), mints step ids, hashes content (Applicability is part of the
hash), derives `precedes` from order plus evidence-backed "before/after step N" cross-refs, pairs `figure_refs` to
media via `pair_figures` (TASK-3705), parses serial qualifiers into `Applicability`, and sums durations into
`estimated_minutes`. Spec §7 "Positional step identity" (R1, **AC4**): on refresh, identities of steps matched by
`source_identity` or exact `content_hash` against the previous card are **carried forward** so tips relink
without a graph round-trip.

---

## Scope

- Append to `manuals/carding.py`: `SourceInfo`, `SERIAL_QUALIFIER_RE`, `parse_serial_qualifier`,
  `PART_SIMILARITY_THRESHOLD`, private `_similarity`, `_carry_forward_identity`, `assemble_card`.
- `SourceInfo` carries everything `assemble_card` needs beyond the fixed skeleton args (source uri/sha/format,
  revision, equipment, toc/digest, page_count, the `FigureCandidate` list for pairing, and `previous_card` for
  identity carry-forward) — the skeleton signature
  `assemble_card(draft, *, manual_id, source, figures, page_map, now)` is not changed.
- Tests: `test_assemble_card_resolves_parts_and_precedes`, `test_parse_serial_qualifier`, identity carry-forward.

**NOT in scope**: writing the verification queue (TASK-3713 reads the returned warnings / unresolved lists);
`ManualVersion` append (TASK-3713/3702); `applies()` evaluation (TASK-3699 models; used by TASK-3721).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/carding.py` | MODIFY | `SourceInfo`, serial parsing, `assemble_card` |
| `packages/ai-parrot/tests/knowledge/manuals/test_assemble_card.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.manuals.models import (   # created by TASK-3699 (spec §3 M2)
    Applicability, EquipmentRef, Hazard, ManualCard, MediaLink, MediaRef, PartRef, Procedure, SerialRange, Step,
    StepIdentity, ToolRef, content_hash, mint_step_id,
)
from parrot.knowledge.manuals.figures import FigureCandidate, pair_figures   # created by TASK-3705
from parrot.knowledge.bookstore.carding import slugify, unique_slug          # verified: bookstore/carding.py:49, 73
from parrot.knowledge.common.provenance import Evidence, Extracted, FieldProvenance   # created by TASK-3697
from datetime import datetime
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/contracts/carding.py (pattern — copy, do NOT import)
PARENT_SIMILARITY_THRESHOLD = 0.85                                   # :821
def similarity(left: str, right: str) -> float                      # :868-892 rapidfuzz token_sort_ratio/100, RuntimeError hint
def assemble_card(draft, *, contract_id, source_uri, source_sha256, source_format, today, toc=(), toc_digest="",
                  page_count=None, ...) -> ContractCard                # :1056 — deterministic, clock injected
# packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py
def slugify(text: str) -> str          # :49 — collapses non-Latin titles to "book" (spec §7 gotcha)
def unique_slug(base: str, taken: set[str]) -> str   # :73

# TASK-3699 contract (spec §3 M2):
def mint_step_id(manual_id: str, procedure_slug: str) -> str
def content_hash(text: str, *, torque=None, duration_minutes=None, applies_to: Sequence[str] = ()) -> str
class StepIdentity(BaseModel): step_id; source_identity=None; content_hash
class SerialRange(BaseModel): start: str | None; end: str | None; format: str
class Applicability(BaseModel): models=[]; serial_ranges=[]; evidence: Evidence | None — serial_ranges ⇒ evidence required
class Step(...): identity, order, text, torque, duration_minutes, applicability, figure_refs, parts, tools, hazards, media: list[MediaLink], cross_refs
class Procedure(...): procedure_id, slug, kind, title, steps, estimated_minutes, skill_level, active, verification, versions, supersedes
# TASK-3705: pair_figures(steps, figures, *, page_of_step: Mapping[int, int]) -> list[tuple[int, MediaLink]]
# TASK-3707: CardingDraft(header, procedures, warnings, origin, llm_calls, ...), StepDraft, ProcedureDraft
```

### Does NOT Exist
- ~~`SourceInfo`~~ anywhere in `parrot.knowledge` (grep: no `class SourceInfo`) — created here.
- ~~A serial-number parser / `Applicability` anywhere pre-FEAT-601~~ (spec §6).
- ~~A `step_key` derived from `slug:order`; content-hash "similarity"~~ — rejected by R1; hash is equality-only (AC4).
- ~~Importing `similarity` from `parrot.knowledge.contracts`~~ — manuals must not import contracts; keep a private copy.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/carding.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_assemble_card.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/carding.py#assemble_card",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/carding.py#similarity",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#slugify",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py#unique_slug"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …`.
- Pure and deterministic: `now` injected; ids minted with `mint_step_id` only for steps that do **not** carry
  forward; sort outputs by (procedure order, step order).
- Carry-forward order (R1): same `source_identity` (when both non-None) ⇒ reuse `step_id`; else exact
  `content_hash` equality ⇒ reuse; else mint. Never a fuzzy match here (fuzzy is a curator-candidate concern of
  `relink_tips`, TASK-3710).
- Serial qualifier unparseable ⇒ keep the literal in `warnings` (queue item), `Applicability` without that range;
  a parsed range always carries the qualifier's `Evidence` (validator in TASK-3699).
- Slug of procedure titles via `slugify` + `unique_slug`; empty/"book" fallback ⇒ `f"procedure-{n}"`.
- No new third-party dependency; Google docstrings, type hints, Pydantic v2, `logger`.

---

## Implementation Blueprint

### Steps (in order)
1. Add imports (models, figures) under the existing import block — *why*: assembly consumes TASK-3699/3705 contracts.
2. Add `SourceInfo` and the serial regex/parser — *why*: Q7 applicability is extracted deterministically from evidence.
3. Add `_similarity` + part resolution — *why*: part numbers/names resolve deterministically (≥ 0.85) or stay literal.
4. Add `_carry_forward_identity` — *why*: R1/AC4 immutable step identity across revisions.
5. Add `assemble_card` — *why*: the single deterministic point that turns drafts into a `ManualCard`.

### `packages/ai-parrot/src/parrot/knowledge/manuals/carding.py` (MODIFY) — imports + SourceInfo + serials
```python
# occurrences: 1 (verified after TASK-3707 lands: grep -c 'from parrot.knowledge.manuals.models import ProcedureKind' carding.py)
# REPLACE that import line with:
from parrot.knowledge.bookstore.carding import slugify, unique_slug
from parrot.knowledge.common.provenance import FieldProvenance
from parrot.knowledge.manuals.figures import FigureCandidate, pair_figures
from parrot.knowledge.manuals.models import (
    Applicability, EquipmentRef, Hazard, ManualCard, MediaLink, MediaRef, PartRef, Procedure, ProcedureKind,
    SerialRange, Step, StepIdentity, ToolRef, content_hash, mint_step_id,
)
from datetime import datetime

# occurrences: 1 (verified after TASK-3707 lands: grep -c '^async def draft_manual(' carding.py)
# AFTER — append at end of file, below `async def draft_manual(` and its body
PART_SIMILARITY_THRESHOLD = 0.85
SERIAL_QUALIFIER_RE = re.compile(
    r"(?:S/N|serial(?:\s+numbers?)?|n[úu]mero de serie)\s*(?:from|desde|>=|≥|and later|y posteriores)?\s*"
    r"([A-Z0-9\-]+)(?:\s*(?:to|hasta|-|–)\s*([A-Z0-9\-]+))?",
    re.I,
)


class SourceInfo(BaseModel):
    """Source facts and ingest-time context handed to :func:`assemble_card`."""

    source_uri: str | None = None
    source_sha256: str
    source_format: str
    revision: str
    equipment: list[str] = Field(default_factory=list)
    toc: list[TocEntry] = Field(default_factory=list)
    toc_digest: str = ""
    page_count: int = 0
    figure_candidates: list[FigureCandidate] = Field(default_factory=list)
    previous_card: ManualCard | None = None          # refresh: identities are carried forward from it (R1)


def parse_serial_qualifier(text: str) -> SerialRange | None:
    """Parse one qualifier ("from S/N 2024-0001", "serial numbers A100 to A250") into a SerialRange.

    Returns None when the text does not match (caller keeps the literal and queues it).
    """
    match = SERIAL_QUALIFIER_RE.search(text or "")
    if not match:
        return None
    # FILL IN: start = group(1); end = group(2) or None (open range for "and later"/"y posteriores"/"from");
    #   "up to"/"hasta" alone ⇒ start None; format inferred from the literal (digits → "9", letters → "A",
    #   separators kept, e.g. "2024-0001" → "9999-9999") — bounded by AC20 and normalize_serial (TASK-3699).
    return SerialRange(start=match.group(1), end=match.group(2), format="")


def _similarity(left: str, right: str) -> float:
    """rapidfuzz token_sort_ratio / 100 (copy of contracts/carding.py:868-892)."""
    # FILL IN: copy body verbatim (empty ⇒ 0.0, identical ⇒ 1.0, RuntimeError install hint).
    return 0.0
```

### `packages/ai-parrot/src/parrot/knowledge/manuals/carding.py` (MODIFY) — identity + assembly
```python
# AFTER — continue appending below `def _similarity(`
def _carry_forward_identity(
    manual_id: str, slug: str, source_identity: str | None, digest: str, previous: Sequence[StepIdentity]
) -> StepIdentity:
    """Reuse a previous step_id by source_identity, then exact content_hash; else mint (R1, AC4)."""
    for prev in previous:
        if source_identity and prev.source_identity == source_identity:
            return StepIdentity(step_id=prev.step_id, source_identity=source_identity, content_hash=digest)
    for prev in previous:
        if prev.content_hash == digest:
            return StepIdentity(step_id=prev.step_id, source_identity=source_identity, content_hash=digest)
    return StepIdentity(step_id=mint_step_id(manual_id, slug), source_identity=source_identity, content_hash=digest)


def assemble_card(
    draft: CardingDraft,
    *,
    manual_id: str,
    source: SourceInfo,
    figures: Sequence[MediaRef],
    page_map: Mapping[str, int],
    now: datetime,
) -> ManualCard:
    """Deterministic: resolve parts (≥ 0.85), mint/carry step ids, hash content (Applicability included), derive
    precedes, pair figure_refs → media (pair_figures), parse serial qualifiers → Applicability (Q7), sum durations."""
    previous = [s.identity for p in (source.previous_card.procedures if source.previous_card else []) for s in p.steps]
    taken: set[str] = set()
    procedures: list[Procedure] = []
    warnings: list[str] = list(draft.warnings)
    for p_index, pdraft in enumerate(draft.procedures, start=1):
        base = slugify(pdraft.title.value or "")
        slug = unique_slug(base if base and base != "book" else f"procedure-{p_index}", taken)
        taken.add(slug)
        # FILL IN: page_of_step = {i: page_map.get(pdraft.node_id, 0)}; links = pair_figures(pdraft.steps,
        #   source.figure_candidates, page_of_step=...) mapped onto figures by media_id; per StepDraft:
        #   applicability (applies_models + parse_serial_qualifier per serial_qualifiers, evidence = qualifier evidence;
        #   unparseable ⇒ warnings.append), digest = content_hash(text, torque, duration, applies_to=models+range strs),
        #   identity via _carry_forward_identity, parts resolved against header parts (exact part number, else
        #   _similarity ≥ PART_SIMILARITY_THRESHOLD ⇒ resolved=True, else literal resolved=False + warning), tools,
        #   hazards, cross_refs kept; estimated_minutes = sum of duration values or None; procedure_id =
        #   f"{manual_id}:{slug}" — bounded by G1/G2/AC4/AC20, deterministic ordering.
        procedures.append(Procedure(procedure_id=f"{manual_id}:{slug}", slug=slug, kind=pdraft.kind, title=pdraft.title,
                                    steps=[], estimated_minutes=None, skill_level=None))
    # FILL IN: ManualCard(manual_id, equipment=[EquipmentRef...] from source.equipment + header models, revision,
    #   source_*, toc, toc_digest, page_count, procedures, global_parts/tools/hazards from header, figures=list(figures),
    #   field_provenance from header evidence, verification="extracted", versions=[], card_origin=draft.origin);
    #   log warnings count — bounded by the ManualCard validator (TASK-3699: unique slugs).
    raise NotImplementedError
```
**Why**: keeping every derivation in one pure function mirrors contracts `assemble_card` and makes R1/AC4
testable without a graph. `previous_card` lives on `SourceInfo` so the skeleton signature stays fixed.
Replace the trailing `raise NotImplementedError` when filling in.

### `packages/ai-parrot/tests/knowledge/manuals/test_assemble_card.py` (CREATE)
```python
"""FEAT-601 M5 — deterministic assembly + serial qualifiers (AC4, AC20)."""
from __future__ import annotations

import pytest

from parrot.knowledge.manuals import carding as cd


@pytest.mark.parametrize(
    "text, start, end",
    [
        ("from S/N 2024-0001", "2024-0001", None),
        ("serial numbers A100 to A250", "A100", "A250"),
        ("número de serie desde 2024-0100", "2024-0100", None),
    ],
)
def test_parse_serial_qualifier(text: str, start: str, end: str | None) -> None:
    rng = cd.parse_serial_qualifier(text)
    assert rng is not None and rng.start == start and rng.end == end and rng.format


def test_parse_serial_qualifier_unparseable() -> None:
    assert cd.parse_serial_qualifier("for early units only") is None


def test_assemble_card_resolves_parts_and_precedes() -> None:
    # FILL IN: CardingDraft with header parts ["P-7 Hex bolt M8"], one procedure, 3 StepDrafts (evidence-backed),
    #   step 3 cross_refs ["before step 2"] ⇒ assert parts resolved via ≥ 0.85, explicit cross_ref kept,
    #   estimated_minutes = sum, figure "1" primary link on the citing step.
    ...


def test_assemble_card_carries_identity_forward() -> None:
    # FILL IN: assemble rev A; rev B with step renumbered (same source_identity) and one reworded (new hash) ⇒
    #   same step_id for the first, new step_id for the reworded; unchanged text keeps id via content_hash.
    ...
```

### FILL IN checklist
- [ ] `parse_serial_qualifier` start/end/format inference — AC20.
- [ ] `_similarity` body copy.
- [ ] `assemble_card` step loop (applicability, hash, identity, parts, figures, durations) — G1/G2/AC4/AC20.
- [ ] `assemble_card` ManualCard construction; remove `raise NotImplementedError`.
- [ ] Test bodies.

---

## Acceptance Criteria

- [ ] `step_id` minted once; renumbered steps keep ids via `source_identity`, unchanged text via exact `content_hash`; no hash similarity anywhere (AC4).
- [ ] Parts resolve at `similarity ≥ 0.85`, else literal with `resolved=False`; `estimated_minutes` = sum of durations.
- [ ] Serial qualifiers parse into evidence-backed `Applicability`; unparseable ⇒ `None` + warning (AC20).
- [ ] No import of `parrot.knowledge.contracts`; `ruff check` + `black --check -l 120` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_assemble_card.py -q`
- `pytest packages/ai-parrot/tests/knowledge/manuals/test_carding.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_assemble_card_resolves_parts_and_precedes` | `similarity ≥ 0.85` resolves; "before step 3" keeps an explicit evidence-backed cross-ref |
| `test_parse_serial_qualifier` | "from S/N 2024-0001", "serial numbers A100 to A250", Spanish forms; unparseable ⇒ None |
| `test_assemble_card_carries_identity_forward` | R1 carry-forward by source_identity then exact hash |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/training-agent.spec.md` (module section named in Context).
2. **Check dependencies** — every `Depends-on` task must be in `sdd/tasks/completed/` (or merged in your feature branch).
3. **Verify the Codebase Contract** — before writing ANY code confirm every import, signature and line anchor
   above still holds (`grep -n` / `read`). Symbols marked "created by TASK-<X>" must exist now that the
   dependency landed; if a name differs, follow the landed code and record the deviation.
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes.
6. **Verify** — run every command in *Validation Commands* (with the worktree `PYTHONPATH`), plus `ruff check`
   and `black --check -l 120` on the touched files.
7. **Move this file** to `sdd/tasks/completed/`, set the index entry to `"done"`, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
