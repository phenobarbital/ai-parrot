import pytest

from navrules.operators import MISSING, OperatorRegistry, default_operators


@pytest.fixture
def ops() -> OperatorRegistry:
    return OperatorRegistry()


class TestMissingSemantics:
    def test_missing_only_matches_is_null(self, ops):
        for op in ("eq", "ne", "gt", "gte", "lt", "lte", "in", "contains"):
            assert ops.compare(op, MISSING, 1) is False
        assert ops.compare("is_null", MISSING, True) is True
        assert ops.compare("is_null", MISSING, False) is False

    def test_none_behaves_as_missing(self, ops):
        assert ops.compare("eq", None, None) is False
        assert ops.compare("ne", None, 1) is False
        assert ops.compare("is_null", None, True) is True

    def test_present_value_is_not_null(self, ops):
        assert ops.compare("is_null", 5, True) is False
        assert ops.compare("is_null", 5, False) is True


class TestNumericCoercion:
    def test_int_float_coerce(self, ops):
        assert ops.compare("eq", 8, 8.0) is True
        assert ops.compare("gt", 8.5, 8) is True
        assert ops.compare("lte", 7, 7.0) is True

    def test_bool_never_coerces_to_number(self, ops):
        assert ops.compare("eq", True, 1) is False
        assert ops.compare("eq", 1, True) is False
        assert ops.compare("eq", True, True) is True
        assert ops.compare("ne", True, 1) is True

    def test_str_number_mismatch(self, ops):
        assert ops.compare("eq", "8", 8) is False
        assert ops.compare("gt", "9", 8) is False


class TestOrdering:
    def test_string_ordering(self, ops):
        assert ops.compare("lt", "abc", "abd") is True
        assert ops.compare("gte", "b", "a") is True

    def test_between(self, ops):
        assert ops.compare("between", 5, [1, 10]) is True
        assert ops.compare("between", 0, [1, 10]) is False
        assert ops.compare("between", 5, [1]) is False


class TestMembership:
    def test_in_not_in(self, ops):
        assert ops.compare("in", "TECH1", ["TECH1", "TECH2"]) is True
        assert ops.compare("not_in", "MGR", ["TECH1", "TECH2"]) is True
        assert ops.compare("in", 5, [5.0, 6]) is True  # numeric coercion
        assert ops.compare("in", "x", "not-a-list") is False

    def test_contains(self, ops):
        assert ops.compare("contains", "hello world", "world") is True
        assert ops.compare("contains", ["a", "b"], "a") is True
        assert ops.compare("contains", 5, "x") is False


class TestStringOps:
    def test_startswith_endswith(self, ops):
        assert ops.compare("startswith", "TECH1", "TECH") is True
        assert ops.compare("endswith", "TECH1", "1") is True
        assert ops.compare("startswith", 10, "1") is False

    def test_regex(self, ops):
        assert ops.compare("regex", "job-1234", r"job-\d+") is True
        assert ops.compare("regex", "nope", r"^\d+$") is False


class TestRegistry:
    def test_unknown_operator_raises(self, ops):
        with pytest.raises(ValueError, match="Invalid operator"):
            ops.compare("nope", 1, 1)

    def test_custom_operator(self, ops):
        ops.register("divisible_by", lambda v, o: v % o == 0)
        assert ops.compare("divisible_by", 10, 5) is True
        assert ops.has_custom is True
        assert ops.is_builtin("divisible_by") is False
        assert default_operators.has_custom is False
