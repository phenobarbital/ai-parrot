# TASK-3339: Reference loaders and catalog identity resolution

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3337
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 2: reference** (stage 4 of §2 Overview, and the "Catalog resolution" block of
§2 *Decided semantics*). Every later stage needs the *reference side* of the comparison:

- the planogram as an ordered list of expected physical facings (`PlanogramRef`),
- the user-supplied catalog that bridges manufacturer part numbers to what is printed on the
  package (`Catalog`) — **required**, never LLM-generated (spec §1 Non-Goals),
- the optional expected-price file,
- and `resolve_identity()`, which turns one open-set LLM reading (`SlotReading`) into a SKU
  **without ever looking at what the planogram expects** (that independence is what makes the
  strict score unbiased).

Design-research finding S3 (spec §9) is implemented here: the planogram's `position` field is
**not** monotone left→right (real shelf 1 reads 1,2,3,4,5,8,6,7); the physical axis is `slot`.

---

## Scope

- Implement `load_planogram(path)`: parse the source schema `{"planogram": {...}, "shelves": [...]}`,
  order every shelf by `slot` (never by `position`, never by dict order), validate that the slots of
  a shelf are exactly `1..n`, expand `facings` into one `PlanogramFacing` per physical facing, map
  `CLOSEOUT` → `identity_required=False`, carry `confidence` → `source_confidence` and
  `read_method` → `reference_read_method`.
- Implement `load_catalog(path, planogram)`: validate the file as `Catalog`, return it together with
  the identity-required planogram SKUs it does not cover (returned, **not** raised).
- Implement `load_prices(path)`: `{"<sku>": "29.99"}` → `dict[str, Decimal]`, `ValueError` on a
  non-numeric value.
- Implement `emit_catalog_template(planogram, path)`: one `CatalogItem` skeleton per distinct
  identity-required SKU; refuses to overwrite (`FileExistsError`).
- Implement `normalize_brand(text, catalog)` and `resolve_identity(reading, catalog)` with the three
  §2 rules (identifier → descriptor signature → alias). XL/standard, colour and pack variants are
  never fuzzy-merged.
- Write `examples/planogram/tests/test_plancheck_reference.py` with the seven M2 tests of spec §4.

**NOT in scope**: the models themselves (`examples/planogram/plancheck/models.py`, TASK-3337);
any use of planogram expectations for identification (that is pass 2, `plancheck/verify.py`,
TASK-3346); alignment scoring (`plancheck/registration.py`, TASK-3345); CLI wiring of
`--catalog` / `--emit-catalog-template` (TASK-3350); LLM catalog enrichment (out of scope for the feature).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/reference.py` | CREATE | Planogram / catalog / prices loaders, catalog template emitter, brand normalisation, identity resolution |
| `examples/planogram/tests/test_plancheck_reference.py` | CREATE | Unit tests for Module 2 (spec §4) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified 2026-09-17 on `dev`. Use these exact imports and names. Do not invent others.

### Verified Imports
```python
import json                      # stdlib
import logging                   # stdlib
import re                        # stdlib
from decimal import Decimal, InvalidOperation   # stdlib
from pathlib import Path         # stdlib
from rapidfuzz import fuzz       # verified by execution in the shared venv: rapidfuzz 3.11.0
#   fuzz.ratio(a, b) -> float 0..100 ; fuzz.token_set_ratio(a, b) -> float 0..100
#   rapidfuzz 3.x applies NO default preprocessing: "Acme 10 Black" vs "acme 10 black ink" scores 73.3,
#   the casefolded pair scores 100.0 → ALWAYS casefold both sides yourself before calling fuzz.*
import pytest                    # tests only
```

### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py — created by TASK-3337 (models-core). Import inside the package as:
from .models import Catalog, CatalogItem, PlanogramFacing, PlanogramRef, Resolution, SlotReading
# and from tests as:  from plancheck.models import ...   (conftest.py of TASK-3337 puts examples/planogram on sys.path)

class PlanogramFacing(StrictModel):      # extra="forbid"
    facing_id: str          # f"p{position:03d}_f{facing}"
    position: int; shelf: int; segment: str
    slot: int; segment_slot: int; facing: int
    sku: str; brand: str | None; identity_required: bool
    source_confidence: str = "unknown"; reference_read_method: str = "unknown"
    notes: str | None = None
class PlanogramRef(StrictModel):
    planogram_id: str; source: str; shelf_count: int; facings: list[PlanogramFacing]
    def shelf(self, number: int) -> list[PlanogramFacing]: ...   # ordered by (slot, facing)
class CatalogItem(StrictModel):
    sku: str; brand: str; display_name: str
    family: str | None = None; xl: bool = False
    colors: list[str] = []; pack: int = 1
    identifiers: list[str] = []; aliases: list[str] = []; provenance: str | None = None
class Catalog(StrictModel):
    items: list[CatalogItem]
    def by_sku(self, sku: str) -> CatalogItem | None: ...
class SlotReading(StrictModel):
    slot_id: str; occupancy: OccupancyState; visibility: Visibility
    brand: str | None = None; family: str | None = None; xl: bool | None = None
    colors: list[str] = []; pack: int | None = None
    visible_text: list[str] = []; evidence: str = ""
Resolution = Literal["direct", "verified_by_expectation", "inferred", "ambiguous", "unresolved"]

# examples/planogram/tests/conftest.py — created by TASK-3337. Fixtures to USE (never redefine):
#   mini_planogram_data() -> dict   raw source-schema dict, 3 shelves × slots 1..6; slots 1–3 brand "Acme"
#       SKUs AC-<shelf><slot>, slots 4–6 brand "Bolt" SKUs BO-<shelf><slot>; shelf 3 slot 6 is CLOSEOUT
#       (brand None, facings 2); shelf-1 positions are 1,2,5,3,4,6 for slots 1..6 (deliberately NOT monotone);
#       read_method "direct" except shelf 2 (all "inferred").
#   mini_planogram() -> PlanogramRef   same content built from models (19 facings).
#   mini_catalog() -> Catalog   one item per identity-required SKU; family "10"/"20"/"30" (Acme) and
#       "11"/"21"/"31" (Bolt) by shelf; slot 1/4 standard black, slot 2/5 XL black, slot 3/6 standard tri-color;
#       identifiers=[sku]; display_name e.g. "Acme 10 Black", "Acme 10XL Black"; aliases=[display_name].
```

### Existing Signatures to Use
```python
# Source schema of the planogram JSON (verified by loading examples/planogram/planogram_page1.json — that file is
# UNTRACKED retailer data: never copy its SKUs into code, tests or docs; tests use mini_planogram_data only):
# {"planogram": {"product_count", "physical_facing_count", "source", "shelves", "segments",
#                "planogram", "fixture", "option"},
#  "shelves": [{"shelf", "shelf_number", "product_count", "facing_count",
#               "products": {"pos <shelf>:<slot>": {"position": int, "segment": "left"|"right",
#                    "segment_number": int, "slot": int, "segment_slot": int, "product": str,
#                    "brand": str | None, "shelf": int, "facings": int, "confidence": str,
#                    "read_method": str, "notes": str | None}}}]}

# Reference only — facing expansion this task adapts. The file lives in the PRIMARY checkout only
# (examples/planogram/inkcheck/ is git-ignored and is NOT present in a worktree); the relevant lines are:
# examples/planogram/inkcheck/inkcheck/catalog.py:5-20 (verified)
#   for shelf in data["shelves"]:
#       for product in shelf["products"].values():                       # <- dict order: DO NOT replicate
#           for index in range(1, int(product.get("facings",1))+1):      # :11
#               facings.append({"id": f"p{product['position']:03d}_f{index}",   # :12
#                   ..., "identity_required":product["product"].upper()!="CLOSEOUT",   # :16
```

### Does NOT Exist
- ~~`import inkcheck`~~ / ~~`from inkcheck.catalog import normalize_planogram`~~ — not a package on the path and absent from worktrees; adapt, never import.
- ~~prices / product names / widths in the planogram JSON~~ — absent; do not read such keys.
- ~~LLM catalog enrichment~~ — explicitly out of scope; `--catalog` is user-supplied.
- ~~`rapidfuzz` default lower-casing~~ — removed in rapidfuzz 3.x; no `processor` is applied unless you pass one.
- ~~`PlanogramFacing.id`~~ — the field is `facing_id`. ~~`PlanogramFacing.read_method`~~ — it is `reference_read_method`.
- ~~`Catalog.brands`~~ / ~~`Catalog.by_brand()`~~ — only `items` and `by_sku()` exist; derive brands from `items`.
- ~~`from parrot… import …`~~ — this is a pure module: it must not import `parrot` or any network library.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/reference.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_reference.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Pure functions, no I/O beyond reading/writing the given `Path`. All text comparisons go through one
private normaliser (casefold + collapse whitespace) so the three rules behave identically.

### Key Constraints
- Pure module: no `parrot`, no network, no `print` — `logger = logging.getLogger(__name__)`.
- Pydantic v2 (`model_validate`, `model_validate_json`, `model_dump`), strict type hints, Google-style
  docstrings, black line length 120.
- `resolve_identity` **never** receives or uses the planogram.
- Rules apply **in order and short-circuit**: the first rule that yields at least one SKU decides
  (one SKU → `direct`, several → `ambiguous`). Only when all three yield nothing → `unresolved`.
- XL/standard, colour and pack are compared exactly. `rapidfuzz` is allowed in exactly two places:
  `normalize_brand` (`fuzz.ratio >= 90`) and rule 3 (`fuzz.token_set_ratio >= 92`).
- Measured on the shared fixture (rapidfuzz 3.11.0, casefolded): `"acme 10 black"` vs `"acme 10xl black"` =
  92.9 and `"acme 10 tri-color"` vs `"acme 20 tri-color"` = 94.1 — i.e. rule 3 legitimately returns
  **several** items for near-twin aliases → `ambiguous`. That is the intended "never fuzzy-merge" outcome;
  do not add tie-breakers. The alias test therefore builds its own two-item catalog with dissimilar aliases.
- Synthetic data only in tests and docstrings (public repo).

### References in Codebase
- `examples/planogram/plancheck/models.py` (TASK-3337) — the models this module returns.
- `examples/planogram/tests/conftest.py` (TASK-3337) — `mini_planogram_data`, `mini_planogram`, `mini_catalog`.
- Spec §2 "Decided semantics → Catalog resolution"; §2 Overview stage 4.

---

## Implementation Blueprint

> Write each block to its path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path fixed here (they come from spec §3 Module 2).

### Steps (in order)
1. Create `reference.py` part 1 (imports, normaliser, `load_planogram`) — *why*: every other function depends on the normaliser and on the facing order being right.
2. In `load_planogram`, sort each shelf's products by `slot` and validate `slots == [1..n]` **before** expanding facings — *why*: `position` is not monotone and dict order is an accident of the extractor (spec §9 S3); a wrong axis silently breaks registration later.
3. Add part 2 (`load_catalog`, `load_prices`, `emit_catalog_template`) — *why*: these are thin validated loaders; missing SKUs are data for the report (`run.catalog_missing_skus`), not an error.
4. Add part 3 (`normalize_brand`, `resolve_identity`) implementing the three rules in order with short-circuit — *why*: identifier evidence is stronger than descriptors, which are stronger than fuzzy aliases.
5. Casefold both operands before every `fuzz.*` call — *why*: rapidfuzz 3.x does no preprocessing (verified: 73.3 vs 100.0).
6. Write the tests, using the conftest fixtures and `tmp_path` for files — *why*: no real planogram data may enter the repo.
7. Run the validation command and `ruff check` on both files.

### `examples/planogram/plancheck/reference.py` (CREATE) — part 1/3
```python
"""Reference side of the planogram check: planogram, catalog, prices, identity resolution (FEAT-565).

Pure module: no parrot import, no network. ``resolve_identity`` never sees planogram expectations.
"""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from rapidfuzz import fuzz

from .models import Catalog, CatalogItem, PlanogramFacing, PlanogramRef, Resolution, SlotReading

logger = logging.getLogger(__name__)

BRAND_MIN_RATIO = 90.0
ALIAS_MIN_RATIO = 92.0
CLOSEOUT = "CLOSEOUT"


def _norm(text: str) -> str:
    """Casefold and collapse whitespace; the single normaliser used by every comparison."""
    return " ".join(text.casefold().split())


def load_planogram(path: Path) -> PlanogramRef:
    """Load the planogram source JSON into an ordered ``PlanogramRef``.

    Args:
        path: File with ``{"planogram": {...}, "shelves": [...]}``.

    Returns:
        Facings of every shelf ordered by ``slot`` then ``facing`` (never by ``position`` or dict order).

    Raises:
        ValueError: Empty input, duplicate facing ids, or a shelf whose ``slot`` values are not exactly ``1..n``.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    shelves = data.get("shelves") or []
    if not shelves:
        raise ValueError(f"Planogram has no shelves: {path}")
    meta = data.get("planogram") or {}
    facings: list[PlanogramFacing] = []
    for shelf in shelves:
        products = sorted(shelf["products"].values(), key=lambda p: int(p["slot"]))
        slots = [int(p["slot"]) for p in products]
        if slots != list(range(1, len(products) + 1)):
            raise ValueError(f"Shelf {shelf.get('shelf_number')}: slots must be exactly 1..n, got {slots}")
        for product in products:
            sku = str(product["product"])
            for index in range(1, int(product.get("facings", 1)) + 1):
                facings.append(
                    PlanogramFacing(
                        facing_id=f"p{int(product['position']):03d}_f{index}",
                        position=int(product["position"]),
                        shelf=int(product["shelf"]),
                        segment=str(product["segment"]),
                        slot=int(product["slot"]),
                        segment_slot=int(product["segment_slot"]),
                        facing=index,
                        sku=sku,
                        brand=product.get("brand"),
                        identity_required=sku.upper() != CLOSEOUT,
                        source_confidence=str(product.get("confidence", "unknown")),
                        reference_read_method=str(product.get("read_method", "unknown")),
                        notes=product.get("notes"),
                    )
                )
    ids = [f.facing_id for f in facings]
    if len(set(ids)) != len(ids):
        raise ValueError("Planogram has duplicate facing ids")
    # FILL IN: planogram_id — a deterministic slug built from meta["planogram"], meta["fixture"], meta["option"]
    #   (casefold, non-alphanumerics → "-"), falling back to Path(path).stem when those keys are missing —
    #   bounded by: same file → same id on every run; no retailer-specific literal in code.
    # FILL IN: return PlanogramRef(planogram_id=..., source=str(meta.get("source", path)),
    #   shelf_count=len(shelves), facings=facings) — bounded by the PlanogramRef fields in the Codebase Contract.
    raise NotImplementedError
```
**Why this shape**: ordering + contiguity validation happen on the raw products *before* expansion, so
a multi-facing position keeps its facings adjacent and the error message can name the shelf. The facing id
format and the CLOSEOUT rule are the ones already used by inkcheck (`catalog.py:12,16`), which keeps the
two tools' ids comparable. Do not sort by `position` anywhere.

### `examples/planogram/plancheck/reference.py` (CREATE) — part 2/3
```python
def load_catalog(path: Path, planogram: PlanogramRef) -> tuple[Catalog, list[str]]:
    """Load the user-supplied catalog and report planogram SKUs it does not cover.

    Args:
        path: JSON file shaped as ``Catalog`` (``{"items": [CatalogItem, ...]}``).
        planogram: Loaded reference, used only to compute coverage.

    Returns:
        ``(catalog, missing)`` where ``missing`` lists, in planogram order and without repeats, the
        identity-required SKUs that have no catalog item. Missing SKUs are returned, never raised.

    Raises:
        ValueError: Invalid catalog file or duplicate ``sku`` entries.
    """
    # FILL IN: Catalog.model_validate_json(Path(path).read_text("utf-8")); wrap pydantic.ValidationError /
    #   json errors into ValueError naming the path — bounded by the docstring's Raises section.
    # FILL IN: reject duplicate sku values with ValueError — bounded by: by_sku() must be unambiguous.
    # FILL IN: missing = ordered-unique [f.sku for f in planogram.facings if f.identity_required
    #   and catalog.by_sku(f.sku) is None]; logger.warning once when non-empty —
    #   bounded by test_load_catalog_reports_missing_skus.
    raise NotImplementedError


def load_prices(path: Path) -> dict[str, Decimal]:
    """Load expected prices ``{"<sku>": "29.99"}`` as Decimals.

    Raises:
        ValueError: The file is not a JSON object or a value is not numeric.
    """
    # FILL IN: json.loads → must be a dict; Decimal(str(value)) per entry; InvalidOperation → ValueError naming
    #   the sku — bounded by: never float arithmetic (price equality is Decimal equality, spec §2 Metrics).
    raise NotImplementedError


def emit_catalog_template(planogram: PlanogramRef, path: Path) -> None:
    """Write a fill-in catalog skeleton: one item per distinct identity-required SKU.

    Each item pre-fills ``sku``, ``brand`` (empty string when the planogram has none), ``identifiers=[sku]``,
    ``display_name=""`` and leaves the descriptor fields at their defaults.

    Raises:
        FileExistsError: ``path`` already exists (never overwritten).
    """
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing catalog: {target}")
    # FILL IN: build the ordered-unique CatalogItem list (first occurrence order in planogram.facings),
    #   dump Catalog(items=...).model_dump(mode="json") with indent=2, write utf-8 —
    #   bounded by spec §5 "the template lists every identity-required planogram SKU exactly once".
    raise NotImplementedError
```
**Why this shape**: the catalog file format *is* the `Catalog` model, so template → user edit → load is a
round trip with no second schema. Missing coverage is report data (`RunInfo.catalog_missing_skus`), which is
why it is returned instead of raised.

### `examples/planogram/plancheck/reference.py` (CREATE) — part 3/3
```python
def normalize_brand(text: str | None, catalog: Catalog) -> str | None:
    """Map free text to a catalog brand.

    Exact casefold match first; otherwise the single best ``fuzz.ratio`` (both sides casefolded) when it is
    ``>= BRAND_MIN_RATIO``. Returns the catalog's own spelling, or ``None``.
    """
    if not text or not text.strip():
        return None
    brands = sorted({item.brand for item in catalog.items if item.brand})
    # FILL IN: exact _norm() equality → return that brand; else score every brand with
    #   fuzz.ratio(_norm(text), _norm(brand)); return the best if >= BRAND_MIN_RATIO and strictly better than
    #   the runner-up, else None — bounded by spec §2 ("brand-name normalisation (≥ 90)").
    raise NotImplementedError


def _tokens(lines: list[str]) -> set[str]:
    """Normalised whole lines plus their whitespace-separated tokens, punctuation-trimmed (keeps ``#`` and ``-``)."""
    out: set[str] = set()
    for line in lines:
        norm = _norm(line)
        if not norm:
            continue
        out.add(norm)
        out.update(tok for tok in (re.sub(r"^[^\w#-]+|[^\w#-]+$", "", t) for t in norm.split()) if tok)
    return out


def resolve_identity(reading: SlotReading, catalog: Catalog) -> tuple[str | None, list[str], Resolution]:
    """Resolve one open-set reading to a catalog SKU using the three spec §2 rules, in order.

    Returns:
        ``(sku, candidate_skus, resolution)`` with resolution ``"direct"`` (one SKU; ``candidate_skus == [sku]``),
        ``"ambiguous"`` (``sku is None``, several candidates, catalog order) or ``"unresolved"`` (``None, []``).
        Never uses planogram expectations.
    """
    brand = normalize_brand(reading.brand, catalog)
    if brand is None:
        return None, [], "unresolved"
    items = [item for item in catalog.items if _norm(item.brand) == _norm(brand)]
    # FILL IN rule 1 (identifier): items having any _norm(identifier) in _tokens(reading.visible_text).
    # FILL IN rule 2 (descriptor signature): requires reading.family; item.family equal (normalised);
    #   colour sets equal (casefolded) WHEN item.colors is non-empty; pack equal WHEN reading.pack is not None;
    #   xl: if reading.xl is not None it must equal item.xl. If reading.xl IS None the xl criterion cannot be
    #   confirmed → the rule may only produce candidates: result is "ambiguous" even with a single item,
    #   never "direct" — bounded by spec §2 rule 2 "(reading xl not null)" and test_resolve_never_merges_xl.
    # FILL IN rule 3 (alias): items with any alias where
    #   fuzz.token_set_ratio(_norm(alias), _norm(line)) >= ALIAS_MIN_RATIO for some visible_text line.
    # FILL IN: short-circuit — the first rule with >= 1 item decides: 1 → (sku, [sku], "direct"),
    #   > 1 → (None, [skus in catalog order], "ambiguous"); none of the three → (None, [], "unresolved").
    raise NotImplementedError
```
**Why this shape**: brand gates everything ("always within the reading's normalised brand", spec §2), so a
reading without a recognisable brand is `unresolved` immediately. The rules are separate, ordered filters so
each can be tested alone; several hits are surfaced as `candidate_skus` because registration gives +3 when the
expected SKU is among them (spec §2 Alignment scores) — dropping them would lose anchors.

### `examples/planogram/tests/test_plancheck_reference.py` (CREATE)
```python
"""Unit tests for plancheck.reference (FEAT-565, spec §4 — Module 2). Synthetic data only."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from plancheck.models import Catalog, CatalogItem, SlotReading
from plancheck.reference import (
    emit_catalog_template,
    load_catalog,
    load_planogram,
    load_prices,
    normalize_brand,
    resolve_identity,
)


def _write(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _reading(**kwargs: object) -> SlotReading:
    base = {"slot_id": "img_r01_s01", "occupancy": "occupied", "visibility": "full"}
    return SlotReading(**{**base, **kwargs})


def test_load_planogram_expands_facings(tmp_path, mini_planogram_data):
    # FILL IN: deepcopy the data, set the CLOSEOUT product's "facings" to 3 → 3 facings p018_f1..f3,
    #   all identity_required False, same slot; total facings == 20.
    raise NotImplementedError


def test_load_planogram_orders_by_slot_not_position(tmp_path, mini_planogram_data):
    # FILL IN: reverse the dict order of shelf 1's "products"; shelf(1) must come back in slot order 1..6
    #   with positions [1, 2, 5, 3, 4, 6]; shelf 2 facings carry reference_read_method == "inferred".
    raise NotImplementedError


def test_load_planogram_rejects_noncontiguous_slots(tmp_path, mini_planogram_data):
    # FILL IN: delete the slot-3 product of shelf 2 (slots 1,2,4,5,6) → pytest.raises(ValueError, match="1..n").
    raise NotImplementedError


def test_load_catalog_reports_missing_skus(tmp_path, mini_planogram, mini_catalog):
    # FILL IN: dump mini_catalog minus the items for "AC-11" and "BO-35"; load_catalog returns them as
    #   missing == ["AC-11", "BO-35"] (planogram order) and does not raise; duplicate sku → ValueError.
    raise NotImplementedError


def test_resolve_identifier_signature_alias(mini_catalog):
    # FILL IN (a) identifier: brand "acme", visible_text ["AC-12"] → ("AC-12", ["AC-12"], "direct").
    # FILL IN (b) signature: brand "Bolt", family "21", xl True, colors ["Black"] → "BO-25" direct.
    # FILL IN (c) alias: build a LOCAL two-item Catalog with dissimilar aliases (e.g. "Zeta 77 Photo Gloss",
    #   "Acme 10 Black"); reading with brand + visible_text ["zeta 77 photo gloss paper"] and no family →
    #   direct. (mini_catalog aliases are near-twins across families: token_set_ratio 94.1 → ambiguous.)
    raise NotImplementedError


def test_resolve_never_merges_xl(mini_catalog):
    # FILL IN: brand "Acme", family "10", colors ["black"], xl None → (None, ["AC-11", "AC-12"], "ambiguous").
    #   Also: unknown brand → (None, [], "unresolved"); xl False → "AC-11" direct.
    raise NotImplementedError


def test_emit_catalog_template_refuses_overwrite(tmp_path, mini_planogram):
    # FILL IN: first call writes a file that load_catalog accepts with missing == [] and exactly 17 items
    #   (every identity-required SKU once, CLOSEOUT absent); second call → pytest.raises(FileExistsError).
    raise NotImplementedError


def test_load_prices_decimal_and_errors(tmp_path):
    # FILL IN: {"AC-11": "29.99", "BO-14": 45.5} → Decimal values; {"AC-11": "n/a"} → ValueError; a JSON list → ValueError.
    raise NotImplementedError
```
**Why this shape**: test names are the spec §4 rows for M2 (plus one for `load_prices`, which has no row
but has a `Raises` contract). All data comes from the TASK-3337 fixtures or `tmp_path`; the alias case uses a
local catalog for the measured reason given in the comment.

### FILL IN checklist
- [ ] `reference.py::load_planogram` — `planogram_id` slug + `PlanogramRef` construction; deterministic, no retailer literal.
- [ ] `reference.py::load_catalog` — validation → `ValueError`, duplicate SKU rejection, ordered-unique `missing`.
- [ ] `reference.py::load_prices` — `Decimal(str(v))`, `ValueError` on non-numeric / non-object.
- [ ] `reference.py::emit_catalog_template` — ordered-unique skeleton items, JSON dump (`mode="json"`, indent 2).
- [ ] `reference.py::normalize_brand` — exact casefold, then `fuzz.ratio >= 90` with a unique best.
- [ ] `reference.py::resolve_identity` — rules 1–3, short-circuit, `xl is None` ⇒ candidates only (`ambiguous`).
- [ ] `test_plancheck_reference.py` — eight test bodies per their FILL IN comments.

---

## Acceptance Criteria

- [ ] `load_planogram` orders by `slot`, rejects non-contiguous shelves, expands facings, maps CLOSEOUT → `identity_required=False`, carries `read_method`.
- [ ] `load_catalog` returns uncovered identity-required SKUs instead of raising; rejects duplicate SKUs.
- [ ] `emit_catalog_template` lists every identity-required SKU exactly once and never overwrites.
- [ ] `resolve_identity` implements the three rules in order, never returns `direct` for an XL/standard pair when `xl` is unknown, and takes no planogram argument.
- [ ] `reference.py` imports neither `parrot` nor any HTTP library; no `print`; every `fuzz.*` operand is casefolded.
- [ ] All tests pass: `pytest examples/planogram/tests/test_plancheck_reference.py -q`
- [ ] `ruff check examples/planogram/plancheck/reference.py examples/planogram/tests/test_plancheck_reference.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest examples/planogram/tests/test_plancheck_reference.py -q`

---

## Test Specification

The scaffold is the test-file blueprint block above. Required tests (spec §4, Module 2):

| Test | Asserts |
|---|---|
| `test_load_planogram_expands_facings` | 3-facing CLOSEOUT → 3 occupancy-only facings, ids `pNNN_fK` |
| `test_load_planogram_orders_by_slot_not_position` | facings in slot order although `position` and dict order disagree |
| `test_load_planogram_rejects_noncontiguous_slots` | slots 1,2,4,… → `ValueError` |
| `test_load_catalog_reports_missing_skus` | missing SKUs returned, not raised; duplicates rejected |
| `test_resolve_identifier_signature_alias` | each of the three rules yields `direct` |
| `test_resolve_never_merges_xl` | `xl=None` with XL + standard items → `ambiguous`, both candidates |
| `test_emit_catalog_template_refuses_overwrite` | round-trips through `load_catalog`; `FileExistsError` on second call |
| `test_load_prices_decimal_and_errors` | Decimal parsing and `ValueError` paths |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 "Catalog resolution", §2 Overview stage 4, §3 Module 2, §4, §6, §7).
2. **Check dependencies** — TASK-3337 must be in `sdd/tasks/completed/`; confirm `examples/planogram/plancheck/models.py` and `examples/planogram/tests/conftest.py` exist.
3. **Verify the Codebase Contract** — open `plancheck/models.py` and confirm the field names listed above; confirm `from rapidfuzz import fuzz` imports. If a model field differs, STOP and report — do not adapt silently.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint blocks; complete every `# FILL IN:`; never change a fixed signature.
6. **Verify** every acceptance criterion; run the validation command (in a worktree no `PYTHONPATH` prefix is needed — this module does not import parrot).
7. **Move this file** to `sdd/tasks/completed/TASK-3339-reference.md` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (backend nova, model mistral.devstral-2-123b, attempt_uid 1a0eb94d44a84a52bfb9d74fccd0f286)
**Date**: 2026-09-17
**Notes**: Created `examples/planogram/plancheck/reference.py` with `load_planogram`,
`load_catalog`, `load_prices`, `emit_catalog_template`, `normalize_brand`, `resolve_identity`,
and `examples/planogram/tests/test_plancheck_reference.py` with 8 tests covering all
acceptance criteria. `ruff check` clean. Engine lint autofix commit `e4d38697d`. Post-merge
full suite → 28 passed. Review recorded: `coder-review:6d92fde1c13f6b19c27d1e06`, no
corrections needed.

**Seat**: mistral · Backend: nova · Model: mistral.devstral-2-123b · Attempts: 1 · Duration: 229.0s · Tokens: 759196/7738

**Deviations from spec**: none
