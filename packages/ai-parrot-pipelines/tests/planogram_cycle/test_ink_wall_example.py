"""Offline tests for examples/planogram/pipelines/ (FEAT-574 ink-wall example, loaded by file path)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot_pipelines.planogram.comparison import definition_coverage, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    FacingStatus,
    PositionResult,
    RenderRecord,
    ShelfScore,
)

_EXAMPLE_DIR = Path(__file__).resolve().parents[4] / "examples" / "planogram" / "pipelines"


def _load(name: str):
    """Load one example script as a module (nothing in examples/ is a package)."""
    spec = importlib.util.spec_from_file_location(name, _EXAMPLE_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # Pydantic resolves postponed annotations through sys.modules
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


@pytest.fixture(scope="module")
def builder():
    """``ink_wall_definition`` as a module."""
    yield from _load("ink_wall_definition")


@pytest.fixture(scope="module")
def runner():
    """``run_ink_wall`` as a module."""
    yield from _load("run_ink_wall")


def _page1() -> dict:
    """Two shelves in the page-1 layout: one position with two facings, one priced as text."""
    return {
        "planogram": {"planogram": "Ink", "shelves": 2},
        "shelves": [
            {
                "shelf": "Shelf 1",
                "shelf_number": 1,
                "products": {
                    "pos 1:1": {"position": 1, "slot": 1, "product": "CC640WN#140", "brand": "HP", "facings": 2},
                    "pos 1:2": {"position": 2, "slot": 2, "product": "T6M14AN", "brand": "HP", "price": "$64.85"},
                },
            },
            {
                "shelf": "Shelf 2",
                "shelf_number": 2,
                "products": {
                    "pos 2:1": {"position": 3, "slot": 1, "product": "C13T04D1", "brand": "EPSON"},
                },
            },
        ],
    }


# --------------------------------------------------------------------------- definition builder


def test_sku_identifiers_keeps_sku_and_base(builder):
    """The colour/region suffix is dropped into a second identifier; a plain SKU yields one."""
    assert builder.sku_identifiers("CC640WN#140") == ["CC640WN#140", "CC640WN"]
    assert builder.sku_identifiers("T6M14AN") == ["T6M14AN"]
    assert builder.sku_identifiers("  ") == []


def test_coerce_price_reads_text_prices(builder):
    """A page-1 price written as text becomes the float the model stores; nonsense becomes None."""
    assert builder.coerce_price("$64.85") == 64.85
    assert builder.coerce_price("29,99 USD") == 29.99
    assert builder.coerce_price(12) == 12.0
    assert builder.coerce_price("n/a") is None
    assert builder.coerce_price(None) is None


def test_seed_page1_fills_only_empty_fields(builder):
    """Seeds are added where nothing was authored; existing descriptors survive untouched."""
    page1 = _page1()
    page1["shelves"][0]["products"]["pos 1:2"]["display_name"] = "HP 902XL"
    seeded = builder.seed_page1(page1)

    first = seeded["shelves"][0]["products"]["pos 1:1"]
    assert first["display_name"] == "HP CC640WN#140"
    assert first["identifiers"] == ["CC640WN#140", "CC640WN"]
    second = seeded["shelves"][0]["products"]["pos 1:2"]
    assert second["display_name"] == "HP 902XL"  # not overwritten
    assert second["price"] == 64.85
    assert page1["shelves"][0]["products"]["pos 1:1"].get("display_name") is None  # input untouched


def test_build_produces_a_valid_definition(builder, tmp_path):
    """The seeded page-1 document loads, expands facings and numbers slots 1..n per shelf."""
    page1_path = tmp_path / "page1.json"
    page1_path.write_text(json.dumps(_page1()), encoding="utf-8")

    definition = builder.build(page1_path)

    assert [s.shelf_id for s in definition.shelves] == ["shelf_1", "shelf_2"]
    assert len(definition.all_facings()) == 4  # 2 facings + 1 + 1
    assert [f.facing_id for f in definition.shelves[0].facings] == ["p001_f1", "p001_f2", "p002_f1"]
    assert sorted({f.slot for f in definition.shelves[0].facings}) == [1, 2]
    assert all(f.descriptors.described for f in definition.all_facings())

    out = builder.write_definition(definition, tmp_path / "slots.json")
    assert load_slots_definition(out).model_dump() == definition.model_dump()  # round-trips


def test_build_merges_a_proposal_per_product(builder, tmp_path):
    """One proposal per product id reaches every facing of it; a conflicting second one is ignored."""
    page1_path = tmp_path / "page1.json"
    page1_path.write_text(json.dumps(_page1()), encoding="utf-8")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "p001_f1": {"display_name": "HP 62 Black", "family": "62", "pack": "2 pack", "price": 9.99},
                "p001_f2": {"display_name": "SOMETHING ELSE", "family": "99"},
                "p003_f1": {"display_name": "Epson 502 Black", "identifiers": ["502"], "colors": ["black"]},
            }
        ),
        encoding="utf-8",
    )

    definition = builder.build(page1_path, proposal_path)
    facings = {f.facing_id: f for f in definition.all_facings()}

    assert facings["p001_f1"].descriptors.display_name == "HP 62 Black"
    assert facings["p001_f2"].descriptors.display_name == "HP 62 Black"  # same product, same descriptors
    assert facings["p001_f1"].descriptors.pack == 2  # "2 pack" coerced
    assert facings["p001_f1"].descriptors.price is None  # a proposal never sets a price
    assert facings["p003_f1"].descriptors.identifiers == ["502"]
    assert facings["p002_f1"].descriptors.display_name == "HP T6M14AN"  # untouched seed


def test_strip_descriptors_keeps_one_described_position(builder, tmp_path):
    """--for-proposal output still loads (one described facing) and is otherwise descriptor-free."""
    page1_path = tmp_path / "page1.json"
    page1_path.write_text(json.dumps(_page1()), encoding="utf-8")

    stripped = builder.strip_descriptors(builder.build(page1_path))
    described = [f for f in stripped.all_facings() if f.descriptors.described]
    assert len(described) == 1

    out = builder.write_definition(stripped, tmp_path / "bare.json")
    reloaded = load_slots_definition(out)
    # The kept product covers BOTH of its facings: a described occurrence counts for every
    # facing of the same product id (definition_coverage).
    fraction, undescribed = definition_coverage(reloaded)
    assert undescribed == ["p002_f1", "p003_f1"] and fraction == pytest.approx(0.5)


# --------------------------------------------------------------------------- runner


def test_resolve_images_scans_and_validates(runner, tmp_path):
    """Explicit paths are kept, a directory is scanned in name order, and misses raise."""
    (tmp_path / "b.jpeg").write_bytes(b"x")
    (tmp_path / "a.JPG").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    assert [p.name for p in runner.resolve_images(None, tmp_path)] == ["a.JPG", "b.jpeg"]
    assert runner.resolve_images([tmp_path / "b.jpeg"], tmp_path) == [tmp_path / "b.jpeg"]
    with pytest.raises(FileNotFoundError):
        runner.resolve_images([tmp_path / "missing.jpg"], tmp_path)
    with pytest.raises(FileNotFoundError):
        runner.resolve_images(None, tmp_path / "empty")


def test_jsonable_survives_a_pil_image(runner):
    """A RenderRecord carries a PIL image: it becomes a marker instead of breaking json.dumps."""
    record = RenderRecord(image_id="photo1", rendered_image=Image.new("RGB", (2, 2)), overlay_path="/tmp/a.png")
    payload = runner.jsonable({"renders": [record], "status": FacingStatus.MATCH, "path": Path("/tmp/x")})

    assert payload["renders"][0]["rendered_image"] == "<PIL.Image>"
    assert payload["renders"][0]["overlay_path"] == "/tmp/a.png"
    assert payload["status"] == "match"
    assert payload["path"] == "/tmp/x"
    json.dumps(payload)  # must not raise


def _result() -> dict:
    """A minimal result dict shaped like ``PlanogramCompliance.run()``'s."""
    return {
        "resolved_backend": "google:gemini-flash-latest",
        "detection_source": "cv",
        "ocr_available": True,
        "detections": [
            {
                "image_id": "photo1",
                "image_size": [4032, 3024],
                "shapes": [{"shape_id": "s1"}],
                "slots": [{"slot_id": "photo1:r0:s1"}],
                "row_count": 5,
                "detection_source": "cv",
                "errors": ["photo1: strip 2 failed"],
            }
        ],
        "identifications": [
            {
                "image_id": "photo1",
                "identifications": [{"shape_id": "s1", "product": "HP 902XL", "occupancy": "occupied"}],
                "added": [],
                "errors": [],
            }
        ],
        "shelf_scores": [
            ShelfScore(
                shelf_id="shelf_1",
                shelf_level="shelf_1",
                expected_facings=17,
                lenient_score=0.25,
                strict_score=0.1,
                coverage=0.2,
                visible_fraction=0.5,
            )
        ],
        "compliance_results": [
            ComplianceResult(
                shelf_level="shelf_1",
                expected_products=["HP 902XL"],
                found_products=["HP 902XL"],
                missing_products=[],
                unexpected_products=[],
                compliance_status=ComplianceStatus.NON_COMPLIANT,
                compliance_score=0.25,
            )
        ],
        "position_results": [
            PositionResult(facing_id="p001_f1", shelf_id="shelf_1", status=FacingStatus.MATCH, identity="HP 902XL"),
            PositionResult(
                facing_id="p002_f1",
                shelf_id="shelf_1",
                status=FacingStatus.VARIANT_UNRESOLVED,
                notes=["candidates: HP 902, HP 902XL"],
            ),
        ],
        "overall_compliance_score": 0.25,
        "strict_compliance_score": 0.1,
        "coverage": 0.2,
        "definition_coverage": 1.0,
        "evidence_quality": None,
        "assessment_status": "inconclusive",
        "overall_compliant": False,
        "errors": ["photo1: strip 2 failed"],
    }


def test_format_report_covers_every_section(runner):
    """The report names each stage, both scores, the unresolved facing and the per-photo error."""
    report = runner.format_report(_result())

    assert "google:gemini-flash-latest" in report and "local_ocr=True" in report
    assert "photo1 4032x3024" in report and "identified=1" in report and "occupied=1" in report
    assert "shelf_1" in report and "25.0%" in report and "10.0%" in report
    assert "match=1" in report and "variant_unresolved=1" in report
    assert "p002_f1" in report and "candidates: HP 902, HP 902XL" in report
    assert "assessment_status    : inconclusive" in report
    assert "evidence quality     :     n/a" in report
    assert "photo1: strip 2 failed" in report


def test_facing_report_lists_violations_before_unseen_facings(runner):
    """A proven mismatch is actionable and comes first; a facing nobody saw comes last."""
    result = _result()
    result["position_results"] = [
        PositionResult(facing_id="p010_f1", shelf_id="shelf_1", status=FacingStatus.NOT_VISIBLE),
        PositionResult(facing_id="p011_f1", shelf_id="shelf_1", status=FacingStatus.VARIANT_UNRESOLVED),
        PositionResult(facing_id="p012_f1", shelf_id="shelf_1", status=FacingStatus.MISMATCH),
    ]
    listed = [line.split()[0] for line in runner.facing_report(result)[2:]]
    assert listed == ["p012_f1", "p011_f1", "p010_f1"]


def test_format_report_handles_an_empty_result(runner):
    """A run where every photo failed still renders a report instead of raising."""
    report = runner.format_report({"errors": ["photo1: boom"], "assessment_status": "inconclusive"})
    assert "Per photo" in report and "photo1: boom" in report
