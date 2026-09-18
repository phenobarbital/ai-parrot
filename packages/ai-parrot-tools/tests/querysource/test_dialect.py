import importlib.util
import pathlib
import re
import sys
import types

import pytest
from parrot_tools.querysource import dialect as d
from parrot_tools.querysource.errors import InvalidConditionsError


def test_build_conditions_shape_and_cap():
    p = d.build_conditions(
        placeholders={"firstdate": "2026-08-09"},
        filter={"store": ["1", "2"]},
        fields=["a"],
        ordering=None,
        grouping=None,
        limit=500,
        offset=10,
        refresh=True,
        max_rows=200,
        forced=None,
    )
    assert p == {
        "firstdate": "2026-08-09",
        "filter": {"store": ["1", "2"]},
        "fields": ["a"],
        "querylimit": 200,
        "_offset": 10,
        "refresh": True,
    }


def test_forced_precedence():
    p = d.build_conditions(
        placeholders={"program": "epson"},
        filter=None,
        fields=None,
        ordering=None,
        grouping=None,
        limit=None,
        offset=None,
        refresh=False,
        max_rows=50,
        forced={"program": "pokemon"},
    )
    assert p["program"] == "pokemon" and p["querylimit"] == 50


def test_validate_placeholders_unknown():
    with pytest.raises(InvalidConditionsError, match="Unknown placeholders"):
        d.validate_placeholders({"firstdate": "x", "fields": ["a"]}, allowed={"firstdate", "lastdate"})


@pytest.mark.parametrize(
    "flt",
    [
        {"a": "v"},
        {"a": "!v"},
        {"a!": "v"},
        {"a": ["x", "y"]},
        {"a": [">=", 1]},
        {"a": {">": 1}},
        {"a": "BETWEEN 1 AND 5"},
        {"a": "null"},
        {"a": True},
    ],
)
def test_validate_filter_accepts(flt):
    assert d.validate_filter(flt) == []


@pytest.mark.parametrize(
    "flt",
    [{"a b": 1}, {"a": {"LIKE": "v"}}, {"a": {">": 1, "<": 5}}, {"a": "BETWEEN 1 AND 5; DROP TABLE x"}, {"a;": 1}],
)
def test_validate_filter_rejects(flt):
    with pytest.raises(InvalidConditionsError):
        d.validate_filter(flt)


def test_version_guard():
    assert d.check_version_compatibility("4.6.0")
    assert d.check_version_compatibility("4.5.12") is None


def test_load_variables_from_settings(monkeypatch):
    mod = types.ModuleType("settings.settings")
    mod.QUERYSOURCE_VARIABLES = {"today": "querysource.libs.functions.first_day"}
    pkg = types.ModuleType("settings")
    pkg.settings = mod
    monkeypatch.setitem(sys.modules, "settings", pkg)
    monkeypatch.setitem(sys.modules, "settings.settings", mod)
    assert set(d.load_variables()) == {"@today"}


def test_load_variables_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "settings", None)
    monkeypatch.setitem(sys.modules, "settings.settings", None)
    monkeypatch.setitem(sys.modules, "querysource.parsers", None)
    assert d.load_variables() == {}


@pytest.mark.skipif(importlib.util.find_spec("querysource") is None, reason="querysource not installed")
def test_dialect_reference_matches_pxd():
    spec = importlib.util.find_spec("querysource")
    pxd = pathlib.Path(spec.submodule_search_locations[0]) / "parsers" / "abstract.pxd"
    text = pxd.read_text()
    for attr in (
        "filter",
        "filter_options",
        "fields",
        "ordering",
        "grouping",
        "querylimit",
        "cond_definition",
        "_offset",
    ):
        assert re.search(rf"\b{re.escape(attr)}\b", text), attr
