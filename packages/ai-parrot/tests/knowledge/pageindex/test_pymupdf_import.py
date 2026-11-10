"""The shared PyMuPDF import tolerates the legacy ``fitz`` name and a missing install."""
from __future__ import annotations

import builtins
import importlib
import sys
import types

import pytest

HELPER = "parrot.knowledge.pageindex._pymupdf"


def _reload_helper(monkeypatch: pytest.MonkeyPatch, blocked: set[str], fake: dict[str, types.ModuleType]):
    """Reload the helper with ``blocked`` imports failing and ``fake`` modules importable."""
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in blocked:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    for key, module in fake.items():
        monkeypatch.setitem(sys.modules, key, module)
    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.delitem(sys.modules, HELPER, raising=False)
    return importlib.import_module(HELPER)


def test_uses_pymupdf_when_available() -> None:
    pytest.importorskip("pymupdf")
    helper = importlib.import_module(HELPER)
    assert helper.pymupdf is not None
    assert helper.pymupdf.__name__ == "pymupdf"


def test_falls_back_to_fitz(monkeypatch: pytest.MonkeyPatch) -> None:
    fitz = types.ModuleType("fitz")
    helper = _reload_helper(monkeypatch, blocked={"pymupdf"}, fake={"fitz": fitz})
    assert helper.pymupdf is fitz


def test_none_when_neither_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _reload_helper(monkeypatch, blocked={"pymupdf", "fitz"}, fake={})
    assert helper.pymupdf is None
