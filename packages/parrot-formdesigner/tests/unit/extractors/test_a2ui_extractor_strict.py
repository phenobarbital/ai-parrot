"""A2UIExtractor strict mode + graph safety — FEAT-650 TASK-4201."""

from __future__ import annotations

import ast
import copy
import pathlib

import pytest

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection  # noqa: E402
from parrot_formdesigner.core.types import FieldType  # noqa: E402
from parrot_formdesigner.extractors import A2UIExtractor, ExtractionMode  # noqa: E402
from parrot_formdesigner.renderers import A2UIFormRenderer  # noqa: E402
from parrot_formdesigner.renderers.a2ui import FIELD_LOWERING  # noqa: E402

NATIVE = [t for t, low in FIELD_LOWERING.items() if low.primitive not in ("notice", "hidden")]
_OPTION_TYPES = (
    FieldType.SELECT,
    FieldType.MULTI_SELECT,
    FieldType.TAGS,
    FieldType.TRANSFER_LIST,
    FieldType.DYNAMIC_SELECT,
)


def _form(types=NATIVE) -> FormSchema:
    fields = [
        FormField(
            field_id=f"f_{t.value}",
            field_type=t,
            label={"en": t.value},
            required=(i % 2 == 0),
            options=[{"value": "x", "label": "X"}] if t in _OPTION_TYPES else None,
        )
        for i, t in enumerate(types)
    ]
    return FormSchema(
        form_id="rt",
        title={"en": "RT"},
        tenant="navigator",
        sections=[
            FormSection(section_id="s1", title={"en": "One"}, fields=fields[: len(fields) // 2]),
            FormSection(
                section_id="s2",
                title={"en": "Two"},
                fields=[FormSubsection(subsection_id="s2a", title={"en": "A"}, fields=fields[len(fields) // 2 :])],
            ),
            FormSection(section_id="empty", title={"en": "Empty"}, fields=[]),
        ],
    )


async def _surface(form):
    return (await A2UIFormRenderer().render(form)).content


def _comps(surface):
    return surface["createSurface"]["components"]


async def test_strict_roundtrip_identity_on_projection():
    form = _form()
    out = A2UIExtractor().extract(await _surface(form), tenant="navigator")
    assert out.mode is ExtractionMode.STRICT and "strict_projection_only" in out.warnings
    assert [s.section_id for s in out.form.sections] == ["s1", "s2", "empty"]
    back = {f.field_id: f for f in out.form.iter_fields_recursive()}
    for f in form.iter_fields_recursive():
        got = back[f.field_id]
        assert got.field_type == f.field_type
        assert got.field_uid == f.field_uid
        assert got.required == f.required
        assert got.label == f.label["en"]
        if f.options:
            assert [o.value for o in got.options] == [o.value for o in f.options]
    assert str(out.form.form_uid) == str(form.form_uid) and out.form.tenant == "navigator"


async def test_missing_extension_warns_and_falls_back():
    surface = copy.deepcopy(await _surface(_form([FieldType.TEXT])))
    comp = next(c for c in _comps(surface) if c["id"] == "f-f_text")
    comp["metadata"]["extensions"].pop("parrot_field_type")
    out = A2UIExtractor().extract(surface)
    assert "strict_missing_extension:f-f_text" in out.warnings


async def test_graph_safety():
    base = await _surface(_form([FieldType.TEXT]))

    dup = copy.deepcopy(base)
    _comps(dup).append(copy.deepcopy(_comps(dup)[1]))
    with pytest.raises(ValueError, match="invalid surface"):
        A2UIExtractor().extract(dup)

    dangling = copy.deepcopy(base)
    _comps(dangling)[0]["children"].append("nope")
    with pytest.raises(ValueError, match="invalid surface"):
        A2UIExtractor().extract(dangling)

    two_roots = copy.deepcopy(base)
    extra = copy.deepcopy(_comps(two_roots)[0])
    _comps(two_roots).append(extra)
    with pytest.raises(ValueError, match="invalid surface"):
        A2UIExtractor().extract(two_roots)

    cyc = copy.deepcopy(base)
    body = next(c for c in _comps(cyc) if c["id"] == "sec-s1-body")
    body["children"].append("sec-s1")
    try:
        out = A2UIExtractor().extract(cyc)
    except ValueError:
        pass  # rejected by catalog validation: also safe
    else:
        assert any(d.reason == "cycle" for d in out.dropped)

    with pytest.raises(ValueError, match="components"):
        A2UIExtractor(max_components=1).extract(base)
    with pytest.raises(ValueError, match="depth"):
        A2UIExtractor(max_depth=0).extract(base)


def test_rejects_non_surface():
    with pytest.raises(ValueError, match="createSurface"):
        A2UIExtractor().extract({"version": "v1.0", "action": {"surfaceId": "x", "name": "n"}})


def test_extractors_package_import_is_lazy():
    src = pathlib.Path(__file__).parents[3] / "src/parrot_formdesigner/extractors/__init__.py"
    tree = ast.parse(src.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
            assert not any(str(n).startswith("parrot.") for n in names)
