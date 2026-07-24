"""Unit tests for :class:`AdhocDatasetAdapter` (FEAT-327, Module 1).

Verifies the adapter satisfies the FEAT-326 validation gate
(``validate_descriptor_datasets``) identically to a real ``DatasetManager``-
like object, over both ad-hoc ``{name: DataFrame}`` dicts and REPL locals.
"""
import pandas as pd
import pytest

from parrot.tools.infographic_sections import (
    AdhocDatasetAdapter,
    SectionDescriptor,
    SectionSpec,
    validate_descriptor_datasets,
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


class TestAdhocDatasetAdapter:
    def test_frames_dict_entry_columns(self):
        df = pd.DataFrame({"actual": [1, 2], "budget": [3, 4]})
        adapter = AdhocDatasetAdapter(frames={"revenue": df})

        entry = adapter.get_dataset_entry("revenue")

        assert entry is not None
        assert list(entry.columns) == ["actual", "budget"]

    def test_unknown_name_returns_none(self):
        adapter = AdhocDatasetAdapter(frames={"revenue": pd.DataFrame({"a": [1]})})

        assert adapter.get_dataset_entry("unknown") is None

    def test_repl_locals_only_dataframes(self):
        df = pd.DataFrame({"x": [1, 2]})
        repl_locals = {
            "revenue": df,
            "count": 5,
            "name": "not-a-frame",
            "func": lambda: None,
        }
        adapter = AdhocDatasetAdapter(repl_locals=repl_locals)

        assert adapter.get_dataset_entry("revenue") is not None
        assert list(adapter.get_dataset_entry("revenue").columns) == ["x"]
        # Non-DataFrame locals are invisible to the adapter.
        assert adapter.get_dataset_entry("count") is None
        assert adapter.get_dataset_entry("name") is None
        assert adapter.get_dataset_entry("func") is None

    def test_frames_precedence_over_locals(self):
        frame_df = pd.DataFrame({"a": [1], "b": [2]})
        locals_df = pd.DataFrame({"c": [1]})
        adapter = AdhocDatasetAdapter(
            frames={"revenue": frame_df},
            repl_locals={"revenue": locals_df},
        )

        entry = adapter.get_dataset_entry("revenue")

        assert list(entry.columns) == ["a", "b"]

    def test_gate_pass_and_deficit_equivalence(self):
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

        # Passing case: DatasetManager-like vs adapter-wrapped ad-hoc frame.
        df = pd.DataFrame({"actual": [1], "budget": [2], "extra": [3]})
        dm = _FakeDatasetManager({"revenue": ["actual", "budget", "extra"]})
        adapter = AdhocDatasetAdapter(frames={"revenue": df})

        validate_descriptor_datasets(desc, dm)  # should not raise
        validate_descriptor_datasets(desc, adapter)  # should not raise

        # Deficit case: missing column "budget" on both paths, identical shape.
        df_missing = pd.DataFrame({"actual": [1]})
        dm_missing = _FakeDatasetManager({"revenue": ["actual"]})
        adapter_missing = AdhocDatasetAdapter(frames={"revenue": df_missing})

        with pytest.raises(InfographicValidationError) as exc_dm:
            validate_descriptor_datasets(desc, dm_missing)
        with pytest.raises(InfographicValidationError) as exc_adapter:
            validate_descriptor_datasets(desc, adapter_missing)

        assert exc_dm.value.detail == exc_adapter.value.detail
