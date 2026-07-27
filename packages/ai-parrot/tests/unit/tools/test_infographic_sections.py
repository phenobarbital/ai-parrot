"""Unit tests for the section descriptor contract + validation gate (FEAT-326, Module 1)."""
import pytest
from pydantic import ValidationError

from parrot.tools.infographic_sections import (
    GapReport,
    ProvenanceDescriptor,
    SectionDescriptor,
    SectionSpec,
    TransformerGap,
    validate_descriptor_datasets,
    validate_payload_shape,
)
from parrot.tools.infographic_toolkit import InfographicValidationError


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeEntry:
    """Minimal DatasetEntry stand-in exposing a ``columns`` attribute."""

    def __init__(self, columns):
        self.columns = columns


class _FakeDatasetManager:
    """Minimal DatasetManager stand-in with ``get_dataset_entry``."""

    def __init__(self, datasets):
        # datasets: alias -> list[str] of columns
        self._datasets = {alias: _FakeEntry(cols) for alias, cols in datasets.items()}

    def get_dataset_entry(self, name):
        return self._datasets.get(name)


def _descriptor(sections, mode="data-splice"):
    return SectionDescriptor(template="tpl", mode=mode, sections=sections)


# ---------------------------------------------------------------------------
# Descriptor model tests
# ---------------------------------------------------------------------------

class TestSectionDescriptor:
    def test_forbids_extra_fields(self):
        with pytest.raises(ValidationError):
            SectionDescriptor(
                template="tpl", mode="jinja", sections=[], bogus="x"
            )

    def test_section_spec_forbids_extra_fields(self):
        with pytest.raises(ValidationError):
            SectionSpec(name="s", target="s", shape="records", extra="nope")

    def test_requires_mode_literal(self):
        with pytest.raises(ValidationError):
            SectionDescriptor(template="tpl", mode="pdf", sections=[])

    def test_defaults(self):
        desc = SectionDescriptor(template="tpl", mode="data-splice", sections=[])
        assert desc.splice_marker_id == "report-data"
        assert desc.params == {}


# ---------------------------------------------------------------------------
# Validation gate — datasets/columns
# ---------------------------------------------------------------------------

class TestValidationGate:
    def test_missing_dataset_listed(self):
        desc = _descriptor(
            [SectionSpec(name="hero", target="/hero", datasets=["revenue"], shape="records")]
        )
        dm = _FakeDatasetManager({})  # revenue absent
        with pytest.raises(InfographicValidationError) as exc:
            validate_descriptor_datasets(desc, dm)
        assert exc.value.code == "sections_unmet"
        section = exc.value.detail["sections"][0]
        assert section["section"] == "hero"
        assert "revenue" in section["missing_datasets"]

    def test_missing_columns_listed_per_alias(self):
        desc = _descriptor(
            [
                SectionSpec(
                    name="hero",
                    target="/hero",
                    datasets=["revenue"],
                    columns={"revenue": ["actual", "budget"]},
                    shape="records",
                )
            ]
        )
        dm = _FakeDatasetManager({"revenue": ["actual"]})  # budget missing
        with pytest.raises(InfographicValidationError) as exc:
            validate_descriptor_datasets(desc, dm)
        section = exc.value.detail["sections"][0]
        assert section["missing_columns"]["revenue"] == ["budget"]

    def test_all_deficits_aggregated_in_one_error(self):
        desc = _descriptor(
            [
                SectionSpec(name="a", target="/a", datasets=["ds1"], shape="records"),
                SectionSpec(
                    name="b",
                    target="/b",
                    datasets=["ds2"],
                    columns={"ds2": ["x"]},
                    shape="records",
                ),
            ]
        )
        dm = _FakeDatasetManager({"ds2": ["y"]})  # ds1 missing, ds2 missing col x
        with pytest.raises(InfographicValidationError) as exc:
            validate_descriptor_datasets(desc, dm)
        sections = exc.value.detail["sections"]
        assert {s["section"] for s in sections} == {"a", "b"}

    def test_passes_when_all_present(self):
        desc = _descriptor(
            [
                SectionSpec(
                    name="hero",
                    target="/hero",
                    datasets=["revenue"],
                    columns={"revenue": ["actual", "budget"]},
                    shape="records",
                )
            ]
        )
        dm = _FakeDatasetManager({"revenue": ["actual", "budget", "extra"]})
        # Should not raise
        validate_descriptor_datasets(desc, dm)


# ---------------------------------------------------------------------------
# Validation gate — payload shape
# ---------------------------------------------------------------------------

class TestPayloadShape:
    def test_payload_shape_mismatch(self):
        desc = _descriptor(
            [SectionSpec(name="hero", target="hero", datasets=[], shape="records")]
        )
        with pytest.raises(InfographicValidationError) as exc:
            validate_payload_shape(desc, {"hero": 42})  # scalar, expected records
        assert exc.value.code == "payload_shape_mismatch"
        assert exc.value.detail["sections"][0]["problem"] == "shape_mismatch"

    def test_missing_target_reported(self):
        desc = _descriptor(
            [SectionSpec(name="hero", target="/days", datasets=[], shape="mapping")]
        )
        with pytest.raises(InfographicValidationError) as exc:
            validate_payload_shape(desc, {})
        assert exc.value.detail["sections"][0]["problem"] == "target_missing"

    def test_json_pointer_and_shapes_pass(self):
        desc = _descriptor(
            [
                SectionSpec(name="days", target="/days", datasets=[], shape="mapping"),
                SectionSpec(name="rows", target="/rows", datasets=[], shape="table"),
                SectionSpec(name="total", target="/total", datasets=[], shape="scalar"),
                SectionSpec(name="items", target="/items", datasets=[], shape="records"),
            ]
        )
        payload = {
            "days": {"20260101": []},
            "rows": [[1, 2], [3, 4]],
            "total": 99.5,
            "items": [{"a": 1}],
        }
        validate_payload_shape(desc, payload)  # should not raise


# ---------------------------------------------------------------------------
# Provenance / gap-report models
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_provenance_has_no_code_field(self):
        assert not any(
            "code" in field or "source" in field
            for field in ProvenanceDescriptor.model_fields
        )

    def test_provenance_roundtrip(self):
        desc = _descriptor([])
        prov = ProvenanceDescriptor(
            descriptor=desc,
            dataset_snapshots={"revenue": "2026-07-24T00:00:00+00:00"},
            artifact_id="art-1",
            tier="one-shot",
        )
        assert prov.recipe_ref is None
        assert prov.tier == "one-shot"


class TestGapReport:
    def test_gap_report_shape(self):
        report = GapReport(
            gaps=[
                TransformerGap(
                    section="hero",
                    proposed_name="build_hero",
                    suggested_source="def build_hero(inputs, params): ...",
                )
            ],
            covered=["footer"],
        )
        assert report.gaps[0].section == "hero"
        assert report.covered == ["footer"]
