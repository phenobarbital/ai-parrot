# TASK-3699: Manual card models, immutable step identity, applicability (M2 core)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3697, TASK-3698
**Assigned-to**: unassigned

---

## Context

Spec §2 "Data Models" and §3 **Module 2** (core half). This creates the `parrot.knowledge.manuals` package and its
card family: `ManualCard` (one per document, `manual_id == PageIndex tree_name`, Q2), `Procedure`, `Step` with an
**immutable, order-independent** `StepIdentity` (R1), part/tool/hazard/media refs, bitemporal `ManualVersion` (G7),
technician `Tip` (U3), serial/model `Applicability` (Q7, G10) and exploded-view `Callout*` models (Q8, G11).
Every extracted fact carries `Evidence` (G2): a `Step` without a substantiating quote cannot be constructed (AC3).

The answer-side models (`ProcedureCitation`, `derive_provenance`, the `*View` models, `ProcedureRef`,
`ProcedureAnswer`) are appended to the same file by TASK-3700.

Parallelism: imports Evidence/Extracted/FieldProvenance from TASK-3697 (knowledge/common/provenance.py); its tests
live in `tests/knowledge/manuals/` whose `__init__`/`conftest` TASK-3698 creates.

---

## Scope

- Create `parrot/knowledge/manuals/__init__.py` as a **lazy facade**: a `_LAZY_EXPORTS: dict[str, str]` (name →
  submodule) covering the public names of *every* manuals module the feature will add (models, domain, catalog,
  catalog_postgres, carding, figures, video, tips, datasource, graph_loader, library, export) plus a module-level
  `__getattr__` — so **no later task edits `__init__.py`**. Nothing is imported eagerly (asyncpg/arango/pymupdf
  must not be required to import the package).
- Create `parrot/knowledge/manuals/models.py` with everything in spec §3 M2 skeleton **except**
  `ProcedureCitation`, `derive_provenance`, `ProcedureAnswer`, the `*View`/`Prerequisites` models and `ProcedureRef`
  (TASK-3700): literals, `mint_step_id`, `content_hash`, `StepIdentity`, `PartRef`, `ToolRef`, `Hazard`,
  `Callout`, `CalloutMap`, `CalloutLink`, `MediaRef`, `MediaLink`, `SerialRange`, `Applicability`,
  `normalize_serial`, `applies`, `Step`, `ManualVersion`, `Procedure`, `EquipmentRef`, `Tip`, `ManualCard`,
  `manual_snapshot_payload`.
- Tests: `test_models.py` and `test_applicability.py`.

**NOT in scope**: answer models (TASK-3700); YAML ontology (TASK-3701); any I/O. Nothing here is exported into
`parrot.models` (names must not collide with `parrot.models.infographic.StepsBlock/ChecklistBlock`, spec F030).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/__init__.py` | CREATE | Lazy `__getattr__` facade for all manuals public names |
| `packages/ai-parrot/src/parrot/knowledge/manuals/models.py` | CREATE | Card family, step identity, applicability, callouts, tips |
| `packages/ai-parrot/tests/knowledge/manuals/test_models.py` | CREATE | Identity, evidence, media, card invariants |
| `packages/ai-parrot/tests/knowledge/manuals/test_applicability.py` | CREATE | `normalize_serial` / `applies` matrix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.common.provenance import (Evidence, Extracted, FieldProvenance, trim_quote, MAX_QUOTE_CHARS,
    VerificationState, ProvenanceOrigin, AnswerProvenance)      # created by TASK-3697 (moved from contracts/models.py:88-311)
from parrot.knowledge.bookstore.models import TocEntry          # bookstore/models.py:98 (contracts/models.py:22 imports it the same way)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import hashlib, importlib, re, uuid
from datetime import date, datetime
from typing import Any, Literal, Optional, Sequence
```

### Existing Signatures to Use
```python
# parrot/knowledge/common/provenance.py (TASK-3697; verbatim copy of contracts/models.py)
class Evidence(BaseModel): node_id: str (min_length=1); quote: str (max 300, trimmed); page: Optional[int] ge=1
    @property substantiates -> bool          # PROPERTY — use `evidence.substantiates`, never `substantiates()`
class Extracted(BaseModel, Generic[T]): value: Optional[T]; evidence: Optional[Evidence]; confidence: float
    @property substantiated -> bool
# packages/ai-parrot/src/parrot/knowledge/contracts/models.py  (shape to mirror — do NOT import contracts)
class ContractVersion(BaseModel):   # :417-475 n ge=1, revision, valid_from/valid_to (exclusive), source_sha256, card_snapshot,
                                    #   recorded_at, evidence_ref; _no_recursive_snapshot :450; _check_interval :457; in_force(as_of) :463
def card_snapshot_payload(card) -> dict[str, Any]   # :597-611 model_dump(mode="json") minus "versions"
SourceFormat = Literal["pdf", "docx", "md", "txt"]  # :164
CardOrigin = Literal["llm", "fallback", "manual"]   # :165
# packages/ai-parrot/src/parrot/knowledge/contracts/__init__.py  (lazy facade pattern to copy)
_LAZY_EXPORTS: dict[str, str] = {...}   # :77-87 name -> sibling module; module __getattr__ resolves on first access
```

### Does NOT Exist
- ~~`parrot.knowledge.manuals`~~ — created by this task.
- ~~A `step_key` derived from `slug:order`; content-hash "similarity"~~ — rejected by R1; `step_id` is minted once, `content_hash` is equality-only (AC4).
- ~~`Applicability`, `SerialRange`, `CalloutMap`, a serial-number parser~~ anywhere in the tree — all new (the *qualifier text* parser `parse_serial_qualifier` is TASK-3708, not here).
- ~~`Evidence.substantiates()`~~ — property.
- ~~Importing anything from `parrot.knowledge.contracts`~~ in manuals — forbidden (U2 motivation).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_models.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_applicability.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#TocEntry",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#ContractVersion",
    "sym:packages/ai-parrot/src/parrot/knowledge/contracts/models.py#card_snapshot_payload"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Identity (R1, AC4)**: `mint_step_id(manual_id, procedure_slug)` returns `f"{manual_id}:{procedure_slug}:{uuid4().hex[:12]}"`.
  It must be ArangoDB `_key`-safe — `:` is allowed in `_key`; reject/normalize any char outside `[A-Za-z0-9_\-:.@()+,=;$!*'%]`.
  `content_hash` = sha256 hex over a **normalized** canonical string (whitespace-collapsed, casefolded text +
  `torque` + `duration_minutes` + sorted `applies_to`), joined with an unambiguous separator (`"\x1f"`). It is used for
  **exact equality only**; never compute a distance on it.
- **Evidence (G2, AC3)**: `Step` validator raises `ValueError` unless `text.evidence is not None and text.evidence.substantiates`.
  `Applicability` validator: `serial_ranges` non-empty ⇒ `evidence` required and substantiating (critical field).
- **Media (G4, AC13)**: `MediaRef` validator — `kind in {"figure","photo"}` ⇒ `storage_key` required; `video_segment` ⇒
  `uri` required and `t_start < t_end`; `storage_key` must never start with `http://`/`https://`/`file://`.
- **Serials (Q7)**: `normalize_serial(value, *, format)` returns a comparable tuple of ints from the digit groups of
  `value` after checking it matches the *shape* of `format` (same count/order of digit and letter groups, same
  separators); raises `ValueError` otherwise. `applies()` is pure: model mismatch ⇒ `"no"`; ranges present and serial
  None ⇒ `"unknown"`; serial not normalizable under a range's format ⇒ that range is undecidable (if no range decides ⇒
  `"unknown"`); inside any range ⇒ `"yes"`; outside every decidable range ⇒ `"no"`; no qualifiers ⇒ `"yes"`.
  An open bound (`start`/`end` None) is unbounded on that side.
- **Card (Q2)**: `ManualCard` validator — `manual_id` matches `^[a-z0-9][a-z0-9\-_.]*$` (it is the PageIndex tree name)
  and `procedures[].slug` are unique. `ManualVersion.card_snapshot` must not carry `versions` (copy contracts rule).
- Pydantic v2, `ConfigDict(extra="forbid")` on every model **except** those used as structured LLM output (`Callout`,
  `CalloutMap`) which keep the default so provider schemas stay simple.
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`.

---

## Implementation Blueprint

### Steps (in order)
1. Write `__init__.py` with the full lazy map below — *why*: later tasks add modules without touching `__init__` (no file overlap).
2. Write `models.py` literals, helpers and small ref models — *why*: every other module types against them.
3. Write `Step`, `Procedure`, `ManualVersion`, `EquipmentRef`, `Tip`, `ManualCard` with validators — *why*: G2/G7/Q2 invariants live in the model, not in callers.
4. Implement `normalize_serial` / `applies` — *why*: pure functions the assembly (TASK-3721) filters with.
5. Write the tests (§4 names).

### `packages/ai-parrot/src/parrot/knowledge/manuals/__init__.py` (CREATE)
```python
"""Manuals knowledge plane — equipment procedure graph (FEAT-601).

Every public name is resolved lazily from the submodule that defines it, so
importing ``parrot.knowledge.manuals`` needs no asyncpg, arango or pymupdf.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_EXPORTS: dict[str, str] = {
    # models (TASK-3699 / TASK-3700)
    **{name: "models" for name in (
        "ManualCard", "Procedure", "Step", "StepIdentity", "PartRef", "ToolRef", "Hazard", "MediaRef", "MediaLink",
        "SerialRange", "Applicability", "Callout", "CalloutMap", "CalloutLink", "ManualVersion", "EquipmentRef", "Tip",
        "mint_step_id", "content_hash", "normalize_serial", "applies", "manual_snapshot_payload",
        "ProcedureCitation", "derive_provenance", "ProcedureRef", "ProcedureView", "StepView", "HazardView",
        "MediaView", "TipView", "Prerequisites", "ProcedureAnswer",
    )},
    # domain (TASK-3701)
    "PROCEDURES_DOMAIN": "domain", "ProceduresDomainNotLoaded": "domain", "default_tenant_manager": "domain",
    # catalog (TASK-3702 / TASK-3703)
    "ManualCatalogStore": "catalog", "SearchHit": "catalog", "UpsertResult": "catalog",
    "VerificationQueueEntry": "catalog", "AnswerRecord": "catalog", "PublicationRecord": "catalog",
    "PostgresManualCatalog": "catalog_postgres",
    # carding / figures / video (TASK-3705..3709)
    "draft_manual": "carding", "assemble_card": "carding",
    "extract_figures": "figures", "pair_figures": "figures", "caption_figures": "figures",
    "upload_figures": "figures", "presign": "figures", "map_callouts": "figures",
    "align_video": "video",
    # tips / datasource / graph / library / export (TASK-3710..3714)
    "relink_tips": "tips", "add_tip": "tips", "retire_tip": "tips", "RelinkReport": "tips",
    "ManualCardDataSource": "datasource",
    "ManualGraphLoader": "graph_loader", "EdgeSpec": "graph_loader", "GraphPublicationReport": "graph_loader",
    "ManualLibrary": "library", "IngestResult": "library",
    "export_bundle": "export",
}

__all__ = tuple(sorted(_LAZY_EXPORTS))


def __getattr__(name: str) -> Any:
    """Resolve a public name from its defining submodule on first access."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f".{module_name}", __name__), name)
    globals()[name] = value
    return value
```
**Why this shape**: identical to the contracts facade (`contracts/__init__.py:77-87`) but fully lazy; names that a later
task has not landed yet simply raise `ImportError`/`AttributeError` on access, never at package import.

### `packages/ai-parrot/src/parrot/knowledge/manuals/models.py` (CREATE — part 1/2: literals, helpers, refs)
```python
"""Typed manual/procedure models — the data plane of FEAT-601 (spec §2, §3 M2)."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from parrot.knowledge.bookstore.models import TocEntry
from parrot.knowledge.common.provenance import (
    MAX_QUOTE_CHARS, AnswerProvenance, Evidence, Extracted, FieldProvenance, ProvenanceOrigin, VerificationState, trim_quote,
)

ProcedureKind = Literal["assembly", "disassembly", "maintenance", "inspection", "troubleshooting"]
MediaKind = Literal["figure", "photo", "video_segment"]
MediaRole = Literal["primary", "secondary", "overview"]
HazardSeverity = Literal["caution", "warning", "danger"]
TipOrigin = Literal["manual", "technician", "memory"]
SourceFormat = Literal["pdf", "docx", "md", "txt"]
CardOrigin = Literal["llm", "fallback", "manual"]
ProcedureAnswerKind = Literal["procedure", "step", "prerequisites", "lookup", "clarification", "not_found",
                              "out_of_scope", "denied", "incomplete"]
Applies = Literal["yes", "no", "unknown"]

_ARANGO_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_\-:.@()+,=;$!*'%]")


def mint_step_id(manual_id: str, procedure_slug: str) -> str:
    """Return ``f"{manual_id}:{procedure_slug}:{uuid4().hex[:12]}"`` — minted once, never derived from order (R1)."""
    # FILL IN: replace unsafe chars with "-" in both parts; bounded by Arango _key charset (_ARANGO_KEY_UNSAFE)


def content_hash(text: str, *, torque: Optional[str] = None, duration_minutes: Optional[int] = None,
                 applies_to: Sequence[str] = ()) -> str:
    """sha256 over normalized text + numeric/qualifier fields — EXACT equality only, never similarity (R1, AC4)."""
    # FILL IN: canonical = "\x1f".join([" ".join(text.split()).casefold(), torque normalized, str(duration), *sorted(applies_to)])


class StepIdentity(BaseModel):
    """Immutable identity of a step, independent of display order (R1)."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    step_id: str = Field(..., min_length=1)
    source_identity: Optional[str] = None      # vendor-stable numbering ("4.2.3") when the manual carries one
    content_hash: str = Field(..., min_length=64, max_length=64)


class PartRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_id: str; part_number: Optional[str] = None; name: Extracted[str]; quantity: Optional[int] = Field(default=None, ge=1)
    resolved: bool = False


class ToolRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_id: str; name: Extracted[str]; spec: Optional[str] = None


class Hazard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hazard_id: str; severity: HazardSeverity; text: Extracted[str]; applies_to: list[str] = Field(default_factory=list)


class Callout(BaseModel):
    """One numbered callout read off an exploded view (vision structured output, Q8)."""
    label: str; description: str = ""; part_number: Optional[str] = None
    bbox: Optional[tuple[float, float, float, float]] = None


class CalloutMap(BaseModel):
    callouts: list[Callout] = Field(default_factory=list)


class CalloutLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_id: str; part_id: str; callout: str; confidence: float = Field(..., ge=0.0, le=1.0); origin: Literal["vision"] = "vision"


class MediaRef(BaseModel):
    """A figure, photo or video segment — a *reference*, never a stored URL (G4)."""
    model_config = ConfigDict(extra="forbid")
    media_id: str; kind: MediaKind; storage_key: Optional[str] = None; uri: Optional[str] = None; page: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None; sha256: Optional[str] = None; caption: Optional[str] = None
    label: Optional[str] = None; t_start: Optional[float] = None; t_end: Optional[float] = None; origin: TipOrigin = "manual"
    callouts: list[CalloutLink] = Field(default_factory=list); unresolved_callouts: list[Callout] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_kind(self) -> "MediaRef":
        # FILL IN: figure/photo ⇒ storage_key; video_segment ⇒ uri and t_start < t_end; storage_key never http(s)/file URL — AC13
        return self


class MediaLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_id: str; role: MediaRole; confidence: float = Field(..., ge=0.0, le=1.0); origin: Literal["manual", "llm"] = "manual"
```
**Why**: literals and refs are what every other module (carding, figures, graph loader, export) types against; the
media validator is the single enforcement point for "no URL is ever persisted" (AC13).

### `packages/ai-parrot/src/parrot/knowledge/manuals/models.py` (CREATE — part 2/2: applicability, step, card)
```python
class SerialRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: Optional[str] = None; end: Optional[str] = None; format: str = Field(..., min_length=1)   # vendor format preserved


class Applicability(BaseModel):
    """Model qualifiers + serial ranges; empty = applies to all (Q7)."""
    model_config = ConfigDict(extra="forbid")
    models: list[str] = Field(default_factory=list); serial_ranges: list[SerialRange] = Field(default_factory=list)
    evidence: Optional[Evidence] = None

    @model_validator(mode="after")
    def _serials_need_evidence(self) -> "Applicability":
        # FILL IN: serial_ranges ⇒ evidence is not None and evidence.substantiates, else ValueError (G2)
        return self


def normalize_serial(value: str, *, format: str) -> tuple[int, ...]:
    """Deterministic comparison key for a serial under a vendor format; ValueError when the shapes differ."""
    # FILL IN: tokenize value and format into digit/letter/separator groups; shapes must match; return digit groups as ints


def applies(step: "Step", *, model: Optional[str], serial: Optional[str]) -> Applies:
    """Pure applicability decision (see Implementation Notes for the full matrix)."""
    # FILL IN: matrix per Implementation Notes — undecidable is "unknown", never a silent "yes" (spec §7 Risks)


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: StepIdentity; order: int = Field(..., ge=1); text: Extracted[str]
    torque: Optional[Extracted[str]] = None; duration_minutes: Optional[Extracted[int]] = None
    applicability: Applicability = Field(default_factory=Applicability); figure_refs: list[str] = Field(default_factory=list)
    parts: list[PartRef] = Field(default_factory=list); tools: list[ToolRef] = Field(default_factory=list)
    hazards: list[Hazard] = Field(default_factory=list); media: list[MediaLink] = Field(default_factory=list)
    cross_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _text_needs_evidence(self) -> "Step":
        # FILL IN: ValueError unless self.text.evidence is not None and self.text.evidence.substantiates (AC3)
        return self


class ManualVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = Field(..., ge=1); revision: str = Field(..., min_length=1); valid_from: Optional[date] = None
    valid_to: Optional[date] = None; source_sha256: str = ""; card_snapshot: dict[str, Any] = Field(default_factory=dict)
    recorded_at: Optional[datetime] = None; evidence_ref: Optional[str] = None
    # FILL IN: _no_recursive_snapshot + _check_interval + in_force(as_of) copied from contracts/models.py:450-475


class Procedure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    procedure_id: str; slug: str; kind: ProcedureKind; title: Extracted[str]; steps: list[Step] = Field(default_factory=list)
    estimated_minutes: Optional[int] = None; skill_level: Optional[str] = None; active: bool = True
    verification: VerificationState = "extracted"; versions: list[ManualVersion] = Field(default_factory=list)
    supersedes: Optional[str] = None


class EquipmentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    equipment_id: str; model: str; family: Optional[str] = None; revision: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class Tip(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tip_id: str; text: str = Field(..., min_length=1); origin: TipOrigin = "technician"
    author_employee_id: Optional[str] = None; created_at: datetime; active: bool = True; orphaned: bool = False
    source_revision: str; attached_step_id: Optional[str] = None; history: list[dict[str, Any]] = Field(default_factory=list)


class ManualCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manual_id: str; equipment: list[EquipmentRef] = Field(default_factory=list); revision: str
    source_uri: Optional[str] = None; source_sha256: str = ""; source_format: SourceFormat = "pdf"
    toc: list[TocEntry] = Field(default_factory=list); toc_digest: str = ""; page_count: int = Field(default=0, ge=0)
    procedures: list[Procedure] = Field(default_factory=list); global_parts: list[PartRef] = Field(default_factory=list)
    global_tools: list[ToolRef] = Field(default_factory=list); global_hazards: list[Hazard] = Field(default_factory=list)
    figures: list[MediaRef] = Field(default_factory=list); field_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    verification: VerificationState = "extracted"; versions: list[ManualVersion] = Field(default_factory=list)
    card_origin: CardOrigin = "llm"

    @model_validator(mode="after")
    def _check_identity(self) -> "ManualCard":
        # FILL IN: manual_id tree-name rule + unique procedures[].slug (Q2) — ValueError on violation
        return self


def manual_snapshot_payload(card: ManualCard) -> dict[str, Any]:
    """JSON-mode dump without ``versions`` (mirrors contracts card_snapshot_payload, :597-611)."""
    payload = card.model_dump(mode="json")
    payload.pop("versions", None)
    return payload
```
**Why**: validators encode G2 (evidence), Q2 (card identity) and G7 (bitemporal intervals) in one place. `trim_quote`,
`MAX_QUOTE_CHARS`, `ProvenanceOrigin`, `AnswerProvenance` are imported now because TASK-3700 appends models that use
them to this same file (`# noqa: F401` if ruff flags them before then).

### FILL IN checklist
- [ ] `mint_step_id` — Arango-safe normalization
- [ ] `content_hash` — canonical normalized string; equality only (AC4)
- [ ] `MediaRef._check_kind` — AC13
- [ ] `Applicability._serials_need_evidence` — G2
- [ ] `normalize_serial` / `applies` — Q7 matrix (AC20)
- [ ] `Step._text_needs_evidence` — AC3
- [ ] `ManualVersion` validators + `in_force` — copied semantics
- [ ] `ManualCard._check_identity` — Q2
- [ ] tests below

---

## Acceptance Criteria

- [ ] `import parrot.knowledge.manuals` works with no optional deps; `parrot.knowledge.manuals.ManualCard` resolves lazily
- [ ] `Step(text=Extracted(value=…, evidence=None))` ⇒ `ValueError` (AC3)
- [ ] `step_id` independent of `order`; renumbering leaves `step_id`/`content_hash` unchanged; text or torque change changes `content_hash` (AC4)
- [ ] `MediaRef(kind="figure", storage_key="https://…")` rejected (AC13)
- [ ] `applies()` matrix and `Applicability` evidence rule hold (AC20)
- [ ] No import from `parrot.knowledge.contracts` in `knowledge/manuals/`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_models.py -q`
- `pytest packages/ai-parrot/tests/knowledge/manuals/test_applicability.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_models.py
import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals.models import MediaRef, Step, StepIdentity, content_hash, mint_step_id


def _text(quote: str = "Torque the bolt to 12 Nm.") -> Extracted[str]:
    return Extracted[str](value=quote, evidence=Evidence(node_id="0003", quote=quote, page=3), confidence=0.9)


def test_step_requires_substantiated_evidence():
    with pytest.raises(ValueError):
        Step(identity=StepIdentity(step_id="m:p:abc", content_hash=content_hash("x")), order=1,
             text=Extracted[str](value="x", evidence=None))


def test_step_identity_order_independent():
    ...


def test_content_hash_numeric_fields():
    assert content_hash("Torque", torque="12 Nm") != content_hash("Torque", torque="14 Nm")


def test_mint_step_id_is_unique_and_key_safe():
    ...


def test_media_ref_never_stores_url():
    with pytest.raises(ValueError):
        MediaRef(media_id="m1", kind="figure", storage_key="https://bucket/x.png")


def test_manual_card_rejects_duplicate_procedure_slugs():
    ...


def test_manual_version_interval_and_snapshot_rules():
    ...


def test_lazy_facade_resolves_models_and_rejects_unknown():
    import parrot.knowledge.manuals as manuals
    assert manuals.ManualCard.__name__ == "ManualCard"
    with pytest.raises(AttributeError):
        manuals.DoesNotExist

# packages/ai-parrot/tests/knowledge/manuals/test_applicability.py
def test_applies_matrix():
    """model mismatch ⇒ no; ranges + no serial ⇒ unknown; inside/outside ranges; open bounds."""


def test_normalize_serial_rejects_foreign_format():
    ...


def test_applicability_requires_evidence():
    ...
```

---

## Agent Instructions

1. Read spec §2 Data Models, §3 Module 2, §5 AC3/AC4/AC13/AC20.
2. Confirm TASK-3697 and TASK-3698 are done; re-verify the contract anchors.
3. Update the per-spec index status → `in-progress`.
4. Implement from the blueprint; complete every `# FILL IN:`; signatures fixed by spec §3 are not renegotiable.
5. Run the Validation Commands with the worktree `PYTHONPATH`.
6. Move this file to `sdd/tasks/completed/`, update the index → `done`, fill the Completion Note.

---

## Completion Note


- Task: TASK-3699
- Feature: training-agent
- Implementation SHA: 5fd2446d1fdf7d0e42140438b69ceaa372114219
- Closed at (UTC): 2026-09-24T23:42:51+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 260.2s · Tokens: n/a |
| supplementary_test_evidence | 187 passed, 1 pre-existing unrelated failure (scoped direct pytest run over manuals+models) |
