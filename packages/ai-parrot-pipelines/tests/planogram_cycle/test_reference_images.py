"""Tests for reference-image loading and expectation-free selection."""

from PIL import Image

from parrot_pipelines.planogram.contracts import CycleContext, OcrReading, ReferenceImage
from parrot_pipelines.planogram.identification.references import (
    flatten_references,
    load_reference_bank,
    reference_label,
    select_references,
)
from parrot_pipelines.planogram.layout import ReferencePolicy


class InlineExecutor:
    """Run submitted encoding functions inline."""

    async def run(self, fn, *args):
        return fn(*args)


def _ctx(policy=None):
    layout = type("Layout", (), {"references": policy or ReferencePolicy()})()
    return CycleContext(executor=InlineExecutor(), layout=layout)


def test_flatten_sorted_keys_and_stable_list_order(tmp_path):
    p1 = tmp_path / "p1.png"
    p2 = tmp_path / "p2.png"
    p3 = tmp_path / "p3.png"

    assert flatten_references({"b": [p2, p1], "a": p3}) == [("a", p3), ("b", p2), ("b", p1)]


async def test_path_list_and_pil_inputs_load_with_stable_labels(tmp_path):
    p1 = tmp_path / "one.png"
    p2 = tmp_path / "two.png"
    Image.new("RGB", (2, 2), "red").save(p1)
    Image.new("RGB", (2, 2), "blue").save(p2)

    bank = await load_reference_bank({"a": p1, "b": [p2], "c": Image.new("RGB", (2, 2), "green")}, _ctx())

    assert [reference.label for reference in bank] == [reference_label(1), reference_label(2), reference_label(3)]
    assert all(reference.image.startswith(b"\x89PNG") for reference in bank)


async def test_missing_file_is_isolated_and_reported(tmp_path):
    good = tmp_path / "good.png"
    Image.new("RGB", (2, 2), "red").save(good)

    ctx = _ctx()
    bank = await load_reference_bank({"a": tmp_path / "missing.png", "b": good}, ctx)

    assert [reference.label for reference in bank] == ["ref-0002"]
    assert "a[1]" in ctx.errors[0]


def _bank(count=7):
    return [
        ReferenceImage(label=reference_label(index), image=b"png", catalog_key=str(index))
        for index in range(1, count + 1)
    ]


def test_all_selection_caps_and_reports_omitted():
    selected, diagnostics = select_references(_bank(), {}, ReferencePolicy(max_per_call=5))

    assert [reference.label for reference in selected] == [f"ref-{index:04d}" for index in range(1, 6)]
    assert any("ref-0006, ref-0007" in diagnostic for diagnostic in diagnostics)


def test_by_brand_uses_only_observed_text():
    bank = [
        ReferenceImage(label="x", image=b"x", catalog_key="x", brand="Acme"),
        ReferenceImage(label="y", image=b"y", catalog_key="y", brand="Zeta"),
    ]

    selected, _ = select_references(bank, {"s1": OcrReading(text="ACME 62XL")}, ReferencePolicy(selection="by_brand"))

    assert [reference.label for reference in selected] == ["x"]


def test_by_brand_without_observed_brand_falls_back_to_all():
    selected, diagnostics = select_references(
        _bank(2), {"s1": OcrReading(text="unrelated")}, ReferencePolicy(selection="by_brand")
    )

    assert len(selected) == 2
    assert any("fell back to all" in diagnostic for diagnostic in diagnostics)


def test_disabled_policy_selects_nothing():
    selected, diagnostics = select_references(_bank(), {}, ReferencePolicy(enabled=False))

    assert selected == []
    assert diagnostics == ["references: disabled"]
