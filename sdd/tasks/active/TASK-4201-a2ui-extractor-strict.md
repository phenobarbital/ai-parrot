# TASK-4201: `A2UIExtractor` core — models, parse + graph safety, walk, strict mode

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (G6, AC9, AC10, AC12; codex S3/S6). The reverse direction:
an A2UI `createSurface` → `FormSchema`. This task ships the module skeleton,
the result models, parsing (`deserialize` + `validate_envelope` first — S6),
the resource limits, the depth-first walk with cycle handling, and **strict
mode** (root carries `parrot_variant == "form"`): identity, sections and
field types are read from the `parrot_*` extensions FEAT-544 emits. The
heuristic mode for generic surfaces is TASK-4202 (same file, so it depends
on this one). Strict-mode fidelity is limited to the **strict projection**
named in spec §7 — no claim beyond it.

---

## Scope

- Create `extractors/a2ui.py` with `ExtractionMode`, `DroppedComponent`, `ExtractedForm`, `A2UI_MAX_COMPONENTS`, `A2UI_MAX_DEPTH`, `A2UIExtractor` (`extract`, `_parse`, `_walk`, `_field_from_component` strict path, `_build_form`), and a heuristic hook that TASK-4202 fills (`_heuristic_field` returns `None` + `dropped(reason="heuristic_not_implemented")` for now).
- Lazy PEP 562 export of `A2UIExtractor`, `ExtractedForm`, `ExtractionMode`, `DroppedComponent` in `extractors/__init__.py` (same pattern as `renderers/__init__.py:27-41`).
- Tests `tests/unit/extractors/test_a2ui_extractor_strict.py`: strict round-trip identity on the projection for every `FIELD_LOWERING` primitive ≠ notice/hidden, empty sections survive, missing extension warns, graph safety (duplicate ids, dangling child, two roots, cycle, limits), non-surface payload.

**NOT in scope**: heuristic mapping of generic surfaces (TASK-4202), import endpoint (TASK-4203), changing `renderers/a2ui.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py` | CREATE | extractor core + strict mode |
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/__init__.py` | MODIFY | lazy exports |
| `packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_strict.py` | CREATE | strict + graph-safety tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection   # core/schema.py:65, 401, 229, 153
from parrot_formdesigner.core.constraints import FieldConstraints                                # core/constraints.py (fields lines 44-56)
from parrot_formdesigner.core.options import FieldOption                                         # core/options.py:25-30
from parrot_formdesigner.core.resolution import resolve_rule_references                          # extractors/jsonschema.py:20
from parrot_formdesigner.core.types import FieldType                                             # core/types.py:16
from parrot_formdesigner.renderers.a2ui import FIELD_LOWERING, field_id_from_pointer_token       # renderers/a2ui.py:198, 92 (import INSIDE methods: renderers/a2ui imports nothing from parrot.* at module top, but keep the extractor's own parrot.* imports lazy)
# lazy, inside _a2ui_ns():
from parrot.outputs.a2ui.serialization import deserialize                                         # serialization.py:155
from parrot.outputs.a2ui.catalog import validate_envelope                                         # catalog/__init__.py:743
from parrot.outputs.a2ui.catalog.base import CatalogValidationError, ProducerOrigin               # catalog/base.py:317, 99
from parrot.outputs.a2ui.models import CreateSurface, Component                                   # models.py:446, 400
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class Component(BaseModel):  model_config = ConfigDict(populate_by_name=True, extra="allow")   # line 400, 427 — catalog props (label, value, variant, options, text, min, max, enableDate...) are in comp.model_extra
    id: str; component: str; child: str | None; children: ChildList | None; checks: list[CheckRule] | None; action: Action | None; metadata: ComponentMetadata | None   # 408-417
class CreateSurface(A2UIMessageBase): surface_id (alias surfaceId); components: list[Component]; data_model (alias dataModel); metadata   # 446-470
class A2UIAgentMessage(BaseModel): create_surface: CreateSurface | None = Field(default=None, alias="createSurface")   # 695-718
# metadata.extensions is Extensions(RootModel[dict]) → comp.metadata.extensions.root (341-347)
# packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py
def deserialize(data: dict | str | bytes) -> A2UIAgentMessage | A2UIRendererMessage | list[A2UIAgentMessage]   # line 155 (legacy "messageType" → DeprecationWarning)
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin=ProducerOrigin.TOOL, surface_catalog_id=None) -> None   # line 743 — raises CatalogValidationError (base.py:317) listing DUPLICATE_ID / MISSING_ROOT / DANGLING_CHILD / UNKNOWN_COMPONENT ...
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py — what strict mode READS (FEAT-544, frozen):
#   root Column id "root" (469) with extensions parrot_variant="form", parrot_form_uid, parrot_form_id, parrot_form_version, parrot_tenant, parrot_submit_url (474-479)
#   "root-title" / "root-description" Text (377, 389)
#   Card id f"sec-{section_id}" with child f"sec-{section_id}-body" Column; title Text f"sec-{section_id}-title" (parrot_role="title") (544-598)
#   Column id f"sub-{subsection_id}" with title Text f"sub-{subsection_id}-title"
#   field component id f"f-{field.field_id}" (649) with extensions parrot_field_id, parrot_field_uid, parrot_field_type, parrot_section_id, parrot_subsection_id, parrot_read_only (634-642)
#   notices: parrot_role="notice" + parrot_field_type (652, 718, 724); HIDDEN fields: no component, value only in dataModel
#   dataModel = {"answers": {field_id: value}, "errors": {...}} (488); field value binding {"path": "/answers/<escaped>"}
FIELD_LOWERING: dict[FieldType, A2UIFieldLowering]  # .primitive in {"TextField","CheckBox","ChoicePicker","Slider","DateTimeInput","notice","hidden"} (154-262)
def field_id_from_pointer_token(token: str) -> str   # line 92
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/__init__.py:27-41 — PEP 562 lazy export pattern (_LAZY_EXPORTS + __getattr__)
```

### Does NOT Exist
- ~~`A2UIExtractor` / `extractors/a2ui.py`~~ — this task creates them.
- ~~`Component.props`~~ — catalog props live in `comp.model_extra` (extra="allow"), e.g. `comp.model_extra.get("label")`.
- ~~`A2UIFormRenderer.unlower()` / any inverse helper~~ — none; the extractor reads extensions and ids.
- ~~section descriptions / field descriptions / options_source / depends_on in the surface~~ — the renderer does not emit them (strict projection, spec §7); strict mode emits ONE `strict_projection_only` warning and never guesses them.
- ~~`validate_envelope` returning a list~~ — it raises `CatalogValidationError`; catch it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/extractors/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_strict.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py#FIELD_LOWERING",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py#field_id_from_pointer_token",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/resolution.py#resolve_rule_references",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#CreateSurface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#Component"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `validate_envelope(origin=TOOL)` runs **before** any walk (S6); its `CatalogValidationError` becomes `ValueError(f"invalid surface: {exc}")`.
- Limits: `len(components) > max_components` → `ValueError`; walk depth `> max_depth` → `ValueError`. A component reached twice (cycle) is recorded as `DroppedComponent(reason="cycle")` + warning and not re-walked. Components never reached from `root` → `dropped(reason="unreachable")`.
- Strict projection per field: `field_id`, `field_uid`, `field_type` (from `parrot_field_type`, validated against `FieldType`), `label` (`model_extra["label"]`), `required` (a `required` check present), `read_only` (`parrot_read_only`), `placeholder` (TextField `model_extra["placeholder"]`), `options` (ChoicePicker `model_extra["options"]` → `FieldOption(value,label)`), constraints from checks (`regex`→pattern, `length`→min/max_length, `numeric`→min/max_value), `default` from `dataModel["answers"][field_id]`.
- Notices (`parrot_role == "notice"`) are **degraded fields**: rebuild a `FormField` with `field_type = parrot_field_type`, label from the Text, warning `degraded_field_restored:<id>`.
- Strict mode falls back to the heuristic hook for a component whose `parrot_field_type` is missing/invalid (warning `strict_missing_extension:<id>`).

---

## Implementation Blueprint

### Steps (in order)
1. Models + constants + `_a2ui_ns()` (copy the lazy pattern of `renderers/a2ui.py:104-150`, exposing `deserialize`, `validate_envelope`, `CatalogValidationError`, `ProducerOrigin`, `CreateSurface`) — *why*: AC12.
2. `extract()`: parse → validate → limits → mode → walk → build → `resolve_rule_references` — *why*: the order IS the S6 guarantee.
3. `_walk()` DFS with `visited`/`depth`, yielding `(component, ancestors)`; afterwards diff against all ids for `unreachable`.
4. Strict `_field_from_component` + section assembly keyed by `sec-<id>` / `sub-<id>` ids (so empty sections survive).
5. `extractors/__init__.py` lazy export.
6. Tests: render fixtures with the real `A2UIFormRenderer` (importorskip) and extract.

### `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py` (CREATE — part 1: models + parse)
```python
"""A2UI createSurface → FormSchema extractor (FEAT-650, spec §3 M5).

Strict mode (root ``parrot_variant == "form"``) reads the FEAT-544 ``parrot_*``
extensions; heuristic mode (TASK-4202) maps any Basic-catalog surface. Every
loss is reported in :class:`ExtractedForm`. ``parrot.outputs.a2ui`` is an
OPTIONAL extra — imported lazily in :func:`_a2ui_ns` only.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..core.constraints import FieldConstraints
from ..core.options import FieldOption
from ..core.resolution import resolve_rule_references
from ..core.schema import FormField, FormSchema, FormSection, FormSubsection
from ..core.types import FieldType

logger = logging.getLogger(__name__)

A2UI_MAX_COMPONENTS = int(os.environ.get("A2UI_MAX_IMPORT_COMPONENTS", "2000"))
A2UI_MAX_DEPTH = int(os.environ.get("A2UI_MAX_IMPORT_DEPTH", "32"))
_STRICT_WARNING = "strict_projection_only"


class ExtractionMode(str, Enum):
    STRICT = "strict"
    HEURISTIC = "heuristic"


class DroppedComponent(BaseModel):
    component_id: str
    component: str
    reason: str  # unsupported_component | not_in_basic_catalog | unreachable | no_binding | cycle | heuristic_not_implemented


class ExtractedForm(BaseModel):
    form: FormSchema
    mode: ExtractionMode
    warnings: list[str] = Field(default_factory=list)
    dropped: list[DroppedComponent] = Field(default_factory=list)


def _a2ui_ns() -> Any:
    """Lazy ai-parrot namespace (pattern: renderers/a2ui.py:104-150)."""
    try:
        from parrot.outputs.a2ui.catalog import validate_envelope
        from parrot.outputs.a2ui.catalog.base import CatalogValidationError, ProducerOrigin
        from parrot.outputs.a2ui.models import CreateSurface
        from parrot.outputs.a2ui.serialization import deserialize
    except ImportError as exc:
        raise RuntimeError("A2UIExtractor requires the 'ai-parrot' extra") from exc

    class _NS:
        pass

    ns = _NS()
    ns.validate_envelope, ns.CatalogValidationError, ns.ProducerOrigin = validate_envelope, CatalogValidationError, ProducerOrigin
    ns.CreateSurface, ns.deserialize = CreateSurface, deserialize
    return ns


def _ext(component: Any) -> dict[str, Any]:
    """``metadata.extensions`` as a plain dict (empty when absent)."""
    meta = getattr(component, "metadata", None)
    exts = getattr(meta, "extensions", None)
    return dict(getattr(exts, "root", None) or {})
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py` (CREATE — part 2: extractor)
```python
class A2UIExtractor:
    """Convert an A2UI v1.0 ``createSurface`` into a ``FormSchema`` (strict or heuristic)."""

    def __init__(self, *, default_section_id: str = "fields", max_components: int = A2UI_MAX_COMPONENTS,
                 max_depth: int = A2UI_MAX_DEPTH) -> None:
        self.logger = logging.getLogger(__name__)
        self.default_section_id = default_section_id
        self.max_components = max_components
        self.max_depth = max_depth

    def extract(self, surface: Any, *, form_id: str | None = None, title: str | None = None,
                tenant: str | None = None) -> ExtractedForm:
        """Parse, validate (S6), walk, build. Raises ValueError on a non-surface / invalid / oversized payload."""
        m = _a2ui_ns()
        cs = self._parse(surface, m)
        if len(cs.components) > self.max_components:
            raise ValueError(f"surface has {len(cs.components)} components > max {self.max_components}")
        try:
            m.validate_envelope(cs, origin=m.ProducerOrigin.TOOL)
        except m.CatalogValidationError as exc:
            raise ValueError(f"invalid surface: {exc}") from exc
        by_id = {c.id: c for c in cs.components}
        root = by_id.get("root")
        if root is None:
            raise ValueError("surface has no 'root' component")
        warnings: list[str] = []
        dropped: list[DroppedComponent] = []
        mode = ExtractionMode.STRICT if _ext(root).get("parrot_variant") == "form" else ExtractionMode.HEURISTIC
        if mode is ExtractionMode.STRICT:
            warnings.append(_STRICT_WARNING)
        reached: set[str] = set()
        fields_by_section: dict[tuple[str, str | None], list[FormField]] = {}
        sections_meta: dict[str, dict[str, Any]] = {}
        subsections_meta: dict[tuple[str, str], dict[str, Any]] = {}
        for comp, ancestors in self._walk(root, by_id, reached, dropped, warnings):
            # FILL IN: dispatch — section Cards (strict: id "sec-<sid>"; heuristic: TASK-4202 rule) → sections_meta;
            #          "sec-<sid>-title"/"sub-<ssid>-title" Texts → titles; sub Columns "sub-<ssid>" → subsections_meta;
            #          inputs/notices → self._field_from_component(comp, mode, cs.data_model, warnings, dropped) appended
            #          under (section_id, subsection_id) derived from extensions (strict) or ancestors (heuristic hook);
            #          Buttons → cancel_allowed flag; anything else → dropped(unsupported_component) — bounded by §7 strict projection
            pass
        for cid in set(by_id) - reached:
            dropped.append(DroppedComponent(component_id=cid, component=by_id[cid].component, reason="unreachable"))
        form = self._build_form(root, cs, mode, form_id, title, tenant, sections_meta, subsections_meta, fields_by_section)
        return ExtractedForm(form=resolve_rule_references(form), mode=mode, warnings=warnings, dropped=dropped)

    def _parse(self, surface: Any, m: Any) -> Any:
        """dict/str/bytes/CreateSurface → CreateSurface (ValueError when it is not a createSurface)."""
        if isinstance(surface, m.CreateSurface):
            return surface
        with_warn = m.deserialize(surface)  # legacy payloads emit DeprecationWarning → surfaced by the caller's warnings
        msg = with_warn[0] if isinstance(with_warn, list) else with_warn
        cs = getattr(msg, "create_surface", None)
        if cs is None:
            raise ValueError("payload is not an A2UI createSurface envelope")
        return cs

    def _walk(self, root: Any, by_id: dict[str, Any], reached: set[str], dropped: list[DroppedComponent],
              warnings: list[str]) -> Iterator[tuple[Any, list[str]]]:
        """Depth-first from root; cycles → dropped("cycle"); depth > max_depth → ValueError."""
        stack: list[tuple[str, list[str]]] = [("root", [])]
        while stack:
            cid, ancestors = stack.pop()
            if cid in reached:
                dropped.append(DroppedComponent(component_id=cid, component=by_id[cid].component, reason="cycle"))
                warnings.append(f"cycle_at:{cid}")
                continue
            if len(ancestors) > self.max_depth:
                raise ValueError(f"surface nesting exceeds max depth {self.max_depth}")
            reached.add(cid)
            comp = by_id[cid]
            yield comp, ancestors
            kids = [comp.child] if comp.child else []
            # FILL IN: append `children` ids — ChildList may be an explicit id list or a template binding (models.py:212 ChildTemplate);
            #          a template → dropped(reason="no_binding") for the child — bounded by models.py ChildList shape
            for kid in reversed(kids):
                stack.append((kid, [*ancestors, cid]))
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py` (CREATE — part 3: strict field + build)
```python
    def _field_from_component(self, comp: Any, mode: ExtractionMode, data_model: dict[str, Any],
                              warnings: list[str], dropped: list[DroppedComponent]) -> FormField | None:
        """Strict: parrot_* extensions decide identity/type; missing → heuristic hook (warning)."""
        ext = _ext(comp)
        props = dict(comp.model_extra or {})
        raw_type = ext.get("parrot_field_type")
        if mode is ExtractionMode.STRICT and raw_type in {t.value for t in FieldType}:
            from ..renderers.a2ui import FIELD_LOWERING  # lazy: keep module import light

            field_type = FieldType(raw_type)
            expected = FIELD_LOWERING[field_type].primitive
            if ext.get("parrot_role") != "notice" and expected not in (comp.component, "hidden") and expected != "notice":
                warnings.append(f"strict_primitive_mismatch:{comp.id}")
            field_id = ext.get("parrot_field_id") or comp.id.removeprefix("f-")
            if ext.get("parrot_role") == "notice":
                warnings.append(f"degraded_field_restored:{comp.id}")
            # FILL IN: constraints/required from comp.checks (required|regex|length|numeric → FieldConstraints / required flag),
            #          options from props["options"] → FieldOption(value,label), placeholder (TextField), default from
            #          data_model.get("answers", {}).get(field_id), read_only from ext.get("parrot_read_only") — bounded by §7 strict projection
            return FormField(field_id=field_id, field_uid=ext.get("parrot_field_uid") or None, field_type=field_type,
                             label=props.get("label") or str(field_id), required=required, read_only=bool(ext.get("parrot_read_only", False)),
                             placeholder=props.get("placeholder"), options=options or None, constraints=constraints, default=default)
        if mode is ExtractionMode.STRICT:
            warnings.append(f"strict_missing_extension:{comp.id}")
        return self._heuristic_field(comp, props, data_model, warnings, dropped)

    def _heuristic_field(self, comp: Any, props: dict[str, Any], data_model: dict[str, Any],
                         warnings: list[str], dropped: list[DroppedComponent]) -> FormField | None:
        """TASK-4202 implements HEURISTIC_PRIMITIVE_MAP here; until then every component is dropped."""
        dropped.append(DroppedComponent(component_id=comp.id, component=comp.component, reason="heuristic_not_implemented"))
        return None

    def _build_form(self, root, cs, mode, form_id, title, tenant, sections_meta, subsections_meta, fields_by_section) -> FormSchema:
        """Assemble sections (empty ones survive — ids come from Cards) and the FormSchema identity."""
        ext = _ext(root)
        # FILL IN: sections in first-seen order from sections_meta; each gets its FormSubsections (from subsections_meta) and
        #          fields from fields_by_section; no section at all → one FormSection(self.default_section_id);
        #          form_uid=ext.get("parrot_form_uid") (strict only, must parse as UUID else warn+mint), form_id=form_id or
        #          ext.get("parrot_form_id") or "form", version=ext.get("parrot_form_version") or "1.0", tenant=tenant (NEVER
        #          parrot_tenant — spec §7), title=title or root-title Text or form_id, description from root-description,
        #          cancel_allowed = a "root-cancel" Button was seen — bounded by §7 strict projection + "Tenant stamping"
        raise NotImplementedError
```
**Why this shape**: validation-before-walk and the limits are codex S6; sections keyed by `sec-`/`sub-` ids are what make empty sections reconstructible (S3 verification); the heuristic hook keeps TASK-4202 a pure extension of this file. `field_uid=... or None` lets pydantic mint a UUID when the extension is absent.

### `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .yaml import YAMLExtractor, YamlExtractor' packages/parrot-formdesigner/src/parrot_formdesigner/extractors/__init__.py)
# AFTER — insert below `from .yaml import YAMLExtractor, YamlExtractor` (verified: extractors/__init__.py:10)
import importlib
from typing import TYPE_CHECKING

# FEAT-650 — the A2UI extractor imports ai-parrot lazily inside its functions, but keep the symbol itself lazy too
# (PEP 562, same pattern as renderers/__init__.py:27-41) so `import parrot_formdesigner.extractors` stays cheap.
_LAZY_EXPORTS = {"A2UIExtractor": ".a2ui", "ExtractedForm": ".a2ui", "ExtractionMode": ".a2ui", "DroppedComponent": ".a2ui"}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path, package=__name__), name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from .a2ui import A2UIExtractor, DroppedComponent, ExtractedForm, ExtractionMode
# and append the four names to __all__ (verified: `__all__ = [` at extractors/__init__.py:12)
```

### `packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_strict.py` (CREATE)
```python
"""A2UIExtractor strict mode + graph safety — FEAT-650 TASK-4201."""

from __future__ import annotations

import copy

import pytest

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection  # noqa: E402
from parrot_formdesigner.core.types import FieldType  # noqa: E402
from parrot_formdesigner.extractors import A2UIExtractor, ExtractionMode  # noqa: E402
from parrot_formdesigner.renderers import A2UIFormRenderer  # noqa: E402
from parrot_formdesigner.renderers.a2ui import FIELD_LOWERING  # noqa: E402

NATIVE = [t for t, l in FIELD_LOWERING.items() if l.primitive not in ("notice", "hidden")]


def _form(types=NATIVE) -> FormSchema:
    fields = [FormField(field_id=f"f_{t.value}", field_type=t, label={"en": t.value}, required=(i % 2 == 0),
                        options=[{"value": "x", "label": "X"}] if t in (FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.TAGS, FieldType.TRANSFER_LIST, FieldType.DYNAMIC_SELECT) else None)
              for i, t in enumerate(types)]
    return FormSchema(form_id="rt", title={"en": "RT"}, tenant="navigator", sections=[
        FormSection(section_id="s1", title={"en": "One"}, fields=fields[: len(fields) // 2]),
        FormSection(section_id="s2", title={"en": "Two"}, fields=[FormSubsection(subsection_id="s2a", title={"en": "A"}, fields=fields[len(fields) // 2 :])]),
        FormSection(section_id="empty", title={"en": "Empty"}, fields=[]),
    ])


async def _surface(form):
    return (await A2UIFormRenderer().render(form)).content


async def test_strict_roundtrip_identity_on_projection():
    form = _form()
    out = A2UIExtractor().extract(await _surface(form), tenant="navigator")
    assert out.mode is ExtractionMode.STRICT and "strict_projection_only" in out.warnings
    assert [s.section_id for s in out.form.sections] == ["s1", "s2", "empty"]
    back = {f.field_id: f for f in out.form.iter_fields_recursive()}
    for f in form.iter_fields_recursive():
        # FILL IN: assert back[f.field_id].field_type/field_uid/required/label text match; options values match where set — bounded by AC9
        pass
    assert str(out.form.form_uid) == str(form.form_uid) and out.form.tenant == "navigator"


async def test_missing_extension_warns_and_falls_back():
    surface = copy.deepcopy(await _surface(_form([FieldType.TEXT])))
    comp = next(c for c in surface["createSurface"]["components"] if c["id"] == "f-f_text")
    comp["metadata"]["extensions"].pop("parrot_field_type")
    out = A2UIExtractor().extract(surface)
    assert "strict_missing_extension:f-f_text" in out.warnings


async def test_graph_safety():
    base = await _surface(_form([FieldType.TEXT]))
    # FILL IN: duplicate id / dangling child / second "root" → ValueError("invalid surface"); a component whose child points back
    #          to an ancestor → dropped reason "cycle"; max_components=1 → ValueError; max_depth=0 → ValueError — bounded by AC10/S6


def test_rejects_non_surface():
    with pytest.raises(ValueError, match="createSurface"):
        A2UIExtractor().extract({"version": "v1.0", "action": {"surfaceId": "x", "name": "n"}})
```
**Why this shape**: the identity test iterates every natively-lowered `FieldType` (AC9) and includes an empty section (S3); graph-safety covers each S6 defect.

### FILL IN checklist
- [ ] `a2ui.py::extract` — walk dispatch into sections/subsections/fields; bounded by §7 strict projection.
- [ ] `a2ui.py::_walk` — `children` handling incl. `ChildTemplate`; bounded by `models.py:212`.
- [ ] `a2ui.py::_field_from_component` — checks→constraints, options, placeholder, default, read_only; bounded by §7.
- [ ] `a2ui.py::_build_form` — assembly + identity rules; bounded by §7 "Tenant stamping".
- [ ] `extractors/__init__.py` — `__all__` additions.
- [ ] tests `FILL IN` bodies; bounded by AC9/AC10.

---

## Acceptance Criteria

- [ ] Strict round-trip is identity on the §7 projection for every native `FIELD_LOWERING` primitive; empty sections survive (AC9).
- [ ] `validate_envelope` runs before the walk; duplicate ids / dangling children / multiple roots / cycles / limits behave per AC10.
- [ ] `import parrot_formdesigner.extractors` does not import `parrot.*` eagerly (AST test like `test_a2ui_export.py:19-30`) (AC12).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_strict.py -v`; `ruff check` clean; `renderers/a2ui.py` untouched.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_strict.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_extractors.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_export.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §3 M5, §7 "Strict projection", §9 S3/S6, and `renderers/a2ui.py:360-500, 507-700` (what is emitted)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — `grep -n 'extra="allow"\|create_surface' packages/ai-parrot/src/parrot/outputs/a2ui/models.py`; `grep -n 'class CatalogValidationError' packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the three files
9. **Close** with `scripts/sdd/close_task.sh TASK-4201 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
