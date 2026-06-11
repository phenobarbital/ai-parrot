"""Unit tests for PandasAgent's cross-turn data-variable anti-stale guard.

Regression coverage for the bug where a DataFrame computed in a PREVIOUS
conversation turn (e.g. a map DataFrame from an earlier "show … on a map"
question) leaked into the current turn's ``response.data``. The
``PythonPandasTool`` REPL namespace persists across turns, so a stale
variable stays resolvable; when conversation history nudges the model to
re-declare it in ``data_variables``, the explicit injection path used to
resolve it blindly.

These tests exercise the two pure helpers that implement the guard:
``_current_turn_variable_names`` and ``_filter_declared_variables``.
"""
import types

import pytest

try:
    from parrot.bots.data import PandasAgent
except Exception:  # pragma: no cover - env-dependent
    PandasAgent = None


pytestmark = pytest.mark.skipif(
    PandasAgent is None, reason="parrot.bots.data not importable in this environment"
)


class _ToolCall:
    """Minimal ToolCall stub mirroring the attributes the helpers read."""

    def __init__(self, name, arguments=None, result=None):
        self.name = name
        self.arguments = arguments or {}
        self.result = result


def _bind(dataframes=None, alias_map=None):
    """Build a minimal object with the two guard helpers bound to it.

    The helpers only touch ``self.dataframes`` and
    ``self._get_dataframe_alias_map``; everything else is irrelevant.
    """
    ns = types.SimpleNamespace()
    ns.dataframes = dataframes or {}
    ns._get_dataframe_alias_map = lambda: (alias_map or {})
    ns._current_turn_variable_names = types.MethodType(
        PandasAgent._current_turn_variable_names, ns
    )
    ns._filter_declared_variables = types.MethodType(
        PandasAgent._filter_declared_variables, ns
    )
    return ns


# ---------------------------------------------------------------------------
# _current_turn_variable_names
# ---------------------------------------------------------------------------

def test_current_turn_vars_from_python_repl_assignments():
    ns = _bind()
    calls = [
        _ToolCall(
            "python_repl_pandas",
            arguments={"code": "kmr_final_df = base.groupby('w').size()\npreview = kmr_final_df.head()"},
        ),
    ]
    assert ns._current_turn_variable_names(calls) == {"kmr_final_df", "preview"}


def test_current_turn_vars_from_fetch_dataset():
    ns = _bind()
    calls = [
        _ToolCall("fetch_dataset", result={"python_variable": "kiosks_locations"}),
    ]
    assert ns._current_turn_variable_names(calls) == {"kiosks_locations"}


def test_current_turn_vars_empty_and_bad_syntax():
    ns = _bind()
    assert ns._current_turn_variable_names(None) == set()
    assert ns._current_turn_variable_names([]) == set()
    bad = [_ToolCall("python_repl_pandas", arguments={"code": "df = ("})]
    assert ns._current_turn_variable_names(bad) == set()


# ---------------------------------------------------------------------------
# _filter_declared_variables — the core anti-stale guard
# ---------------------------------------------------------------------------

def test_rejects_prior_turn_variable():
    """The reported bug: a prior turn's map DataFrame must be rejected."""
    ns = _bind()
    calls = [
        _ToolCall(
            "python_repl_pandas",
            arguments={"code": "kmr_final_df = base.groupby('w').size()"},
        ),
    ]
    allowed, rejected = ns._filter_declared_variables(
        ["kmr_final_df", "portland_map_df"], calls
    )
    assert allowed == ["kmr_final_df"]
    assert rejected == ["portland_map_df"]


def test_allows_registered_base_dataset_without_code():
    """A loaded dataset referenced with no pandas code this turn is allowed."""
    ns = _bind(dataframes={"kiosks_locations": object()}, alias_map={"kiosks_locations": "df1"})
    allowed, rejected = ns._filter_declared_variables(["kiosks_locations"], [])
    assert allowed == ["kiosks_locations"]
    assert rejected == []


def test_allows_base_dataset_by_alias():
    ns = _bind(dataframes={"sales": object()}, alias_map={"sales": "df1"})
    allowed, rejected = ns._filter_declared_variables(["df1"], None)
    assert allowed == ["df1"]
    assert rejected == []


def test_preserves_declaration_order():
    ns = _bind()
    calls = [
        _ToolCall(
            "python_repl_pandas",
            arguments={"code": "a = base.copy()\nb = base.copy()"},
        ),
    ]
    allowed, rejected = ns._filter_declared_variables(["b", "stale", "a"], calls)
    assert allowed == ["b", "a"]
    assert rejected == ["stale"]


def test_empty_declaration():
    ns = _bind()
    assert ns._filter_declared_variables(None, []) == ([], [])
    assert ns._filter_declared_variables([], []) == ([], [])
