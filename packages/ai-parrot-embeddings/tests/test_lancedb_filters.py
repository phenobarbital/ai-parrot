"""Filter and hostile-input matrix (FEAT-542, AC5). No SDK required."""

from __future__ import annotations

import math

import pytest

from parrot.stores.lancedb_filters import (
    FilterCompilationError,
    combine,
    compile_metadata_filter,
    parent_exclusion_clause,
)
from parrot.stores.lancedb_models import LanceDBConfig


@pytest.fixture
def config():
    return LanceDBConfig(
        uri="/tmp/x",
        metadata_fields={"custom_int": "int", "custom_float": "float", "custom_flag": "bool"},
    )


class TestSupportedMappings:
    @pytest.mark.parametrize(
        "value,expected_fragment",
        [
            ("source_a", "meta_source = 'source_a'"),
            (["source_a", "source_b"], "meta_source IN ("),
            (None, "meta_source IS NULL"),
        ],
    )
    def test_typed_equality_membership_and_null(self, config, value, expected_fragment):
        clause = compile_metadata_filter({"source": value}, config)
        assert expected_fragment in clause

    def test_empty_membership_list_matches_nothing(self, config):
        clause = compile_metadata_filter({"source": []}, config)
        assert clause == "((1 = 0))"

    def test_bool_field_equality(self, config):
        clause = compile_metadata_filter({"is_chunk": True}, config)
        assert "meta_is_chunk = TRUE" in clause

    def test_int_and_float_custom_fields(self, config):
        clause = compile_metadata_filter({"custom_int": 5, "custom_float": 1.5}, config)
        assert "meta_custom_int = 5" in clause
        assert "meta_custom_float = 1.5" in clause

    def test_multiple_keys_combine_with_and(self, config):
        clause = compile_metadata_filter({"source": "a", "is_chunk": True}, config)
        assert " AND " in clause

    def test_no_filters_returns_none(self, config):
        assert compile_metadata_filter(None, config) is None
        assert compile_metadata_filter({}, config) is None


class TestRejections:
    @pytest.mark.parametrize(
        "bad_filters",
        [
            {"nonexistent_field": "x"},  # unknown field
            {"source": {"$in": ["a"]}},  # nested filter object
            {"custom_int": "5"},  # str-as-number
            {"is_chunk": 1},  # int/bool-as-int confusion (1 is int, not bool)
            {"custom_int": True},  # bool does not count as int
            {"source": ["a", 1]},  # mixed-type list
            {"source": ["a", None]},  # list containing null
        ],
    )
    def test_rejected_before_any_sdk_call(self, config, bad_filters):
        with pytest.raises(FilterCompilationError):
            compile_metadata_filter(bad_filters, config)


class TestParentVisibility:
    def test_missing_markers_remain_visible(self):
        clause = parent_exclusion_clause()
        # A legacy row with no markers has NULL for both columns — the
        # clause must be satisfied (True) for that row, i.e. both NULL
        # branches must be present as OR-escape-hatches.
        assert "meta_is_full_document IS NULL" in clause
        assert "meta_document_type IS NULL" in clause

    def test_is_chunk_cannot_override_explicit_parent_marker(self):
        clause = parent_exclusion_clause()
        # is_chunk is simply never referenced by this clause.
        assert "is_chunk" not in clause

    def test_excludes_explicit_full_document_and_parent_types(self):
        clause = parent_exclusion_clause()
        assert "meta_is_full_document = FALSE" in clause
        assert "'parent'" in clause
        assert "'parent_chunk'" in clause


class TestHostileInput:
    @pytest.mark.parametrize(
        "payload",
        [
            "O'Brien's report",  # embedded quote
            "'; DROP TABLE agent_knowledge; --",  # SQL-like payload
            "a\x00b",  # NUL byte
        ],
    )
    def test_string_literals_escaped_or_rejected(self, config, payload):
        if "\x00" in payload:
            with pytest.raises(FilterCompilationError):
                compile_metadata_filter({"source": payload}, config)
        else:
            clause = compile_metadata_filter({"source": payload}, config)
            # The literal must be safely quoted — no unescaped single quote
            # can terminate the string early.
            assert "''" in clause or "'" not in payload

    def test_non_finite_float_rejected(self, config):
        with pytest.raises(FilterCompilationError):
            compile_metadata_filter({"custom_float": math.nan}, config)
        with pytest.raises(FilterCompilationError):
            compile_metadata_filter({"custom_float": math.inf}, config)

    def test_malicious_identifier_rejected_as_unknown_field(self, config):
        with pytest.raises(FilterCompilationError):
            compile_metadata_filter({"source; DROP TABLE x; --": "a"}, config)


class TestCombine:
    def test_combine_all_none_returns_none(self):
        assert combine(None, None) is None

    def test_combine_skips_empty_and_ands_the_rest(self):
        result = combine("a = 1", None, "b = 2")
        assert result == "(a = 1) AND (b = 2)"


class TestDeleteFilterReuse:
    def test_compiler_signals_empty_filter_as_none_not_unrestricted_sql(self, config):
        """An empty/absent filter compiles to ``None`` (no predicate string).

        This module never emits an "always true" SQL fragment for an empty
        filter. Enforcing that deletion REQUIRES a non-empty explicit
        selector (rejecting ``None`` here with a ``ValueError`` before ever
        reaching the SDK) is the store's responsibility, not this pure
        compiler's — see spec §2 "no implicit delete-all operation exists"
        and this task's declared NOT-in-scope: delete execution.
        """
        assert compile_metadata_filter(None, config) is None
        assert compile_metadata_filter({}, config) is None

    def test_delete_uses_metadata_compiler_without_parent_predicate(self, config):
        metadata_clause = compile_metadata_filter({"source": "source_a"}, config)
        # Deletion combines ONLY the metadata clause — parent_exclusion_clause
        # is a search-only concern and must not be part of this combination.
        delete_predicate = combine(metadata_clause)
        assert "is_full_document" not in delete_predicate
        assert "document_type" not in delete_predicate
