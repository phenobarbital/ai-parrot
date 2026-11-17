"""AC18 / AC17 — the satellite imports with core and never imports polars or grpc."""

from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "parrot" / "squawk"


def test_import_and_version():
    import parrot.squawk as sq

    assert re.match(r"^\d+\.\d+\.\d+", sq.__version__)


def test_no_namespace_init():
    assert not (SRC.parent / "__init__.py").exists(), "PEP 420: src/parrot/__init__.py must not exist"


def test_no_forbidden_imports():
    pat = re.compile(r"^\s*(import|from)\s+(polars|grpc)\b", re.M)
    for py in SRC.rglob("*.py"):
        assert not pat.search(py.read_text()), f"forbidden import in {py}"
