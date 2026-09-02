"""FEAT-498 TASK-2746 — `python.yaml` (refs + imports only) tests."""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import yaml
from parrot.knowledge.wiki.languages import astgrep
from parrot.knowledge.wiki.languages.python import PythonScanner

from .conftest import requires_astgrep

FIXTURES = Path(__file__).parent / "fixtures" / "structural"


def test_python_rules_have_no_symbols():
    data = yaml.safe_load(
        importlib.resources.files("parrot.knowledge.wiki.languages.rules")
        .joinpath("python.yaml")
        .read_text(encoding="utf-8")
    )
    assert data["symbols"] == []


def test_ruleset_loads_without_warning(caplog):
    astgrep.RuleSet.load.cache_clear()
    ruleset = astgrep.RuleSet.load("python")
    assert ruleset is not None
    assert ruleset.language == "python"
    assert ruleset.symbols == []
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


@requires_astgrep
def test_python_refs_only():
    src = (FIXTURES / "sample.py").read_text(encoding="utf-8") + "\n\n@helper(1)\ndef g():\n    return helper(2)\n"
    out = PythonScanner().outline(src, "sample.py")
    calls = {(r.src_qualname, r.target_text) for r in out.refs if r.rel == "calls"}
    assert ("UserService.get_user", "helper") in calls
    assert ("g", "helper") in calls
    # The decorator's own call site is never a `calls` ref.
    assert not any(r.target_text == "helper" and r.src_qualname == "" for r in out.refs if r.rel == "calls")
    extends = {(r.src_qualname, r.target_text) for r in out.refs if r.rel == "extends"}
    assert ("UserService", "BaseService") in extends


def test_python_symbols_identical_with_and_without_seam():
    src = (FIXTURES / "sample.py").read_text(encoding="utf-8")
    scanner = PythonScanner()
    with_seam = scanner.outline(src, "sample.py")

    original = astgrep.is_available
    try:
        astgrep.is_available = lambda: False
        without_seam = scanner.outline(src, "sample.py")
    finally:
        astgrep.is_available = original

    assert [s.model_dump() for s in with_seam.symbols] == [s.model_dump() for s in without_seam.symbols]
    assert with_seam.outline == without_seam.outline
    assert with_seam.summary == without_seam.summary
    assert with_seam.imports == without_seam.imports
    assert without_seam.refs == []


@requires_astgrep
def test_python_mode_is_always_ast():
    src = (FIXTURES / "sample.py").read_text(encoding="utf-8")
    scanner = PythonScanner()
    scanner.outline(src, "sample.py")
    assert scanner.mode == "ast"
