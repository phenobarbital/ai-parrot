"""Smoke tests for TASK-1333: satellite package scaffold."""
import importlib
from pathlib import Path

import pytest


def test_satellite_pyproject_exists():
    """The satellite's pyproject is present and parses."""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    assert pyproject.exists(), f"missing {pyproject}"
    # Sanity: contains the expected name and namespace config
    text = pyproject.read_text(encoding="utf-8")
    assert 'name = "ai-parrot-embeddings"' in text
    assert "namespaces = true" in text
    assert 'include = ["parrot*"]' in text


def test_no_init_at_namespace_levels():
    """U3 (pure PEP 420): satellite has no __init__.py at four namespace levels."""
    src_parrot = Path(__file__).parent.parent / "src" / "parrot"
    forbidden = [
        src_parrot / "__init__.py",
        src_parrot / "embeddings" / "__init__.py",
        src_parrot / "stores" / "__init__.py",
        src_parrot / "rerankers" / "__init__.py",
    ]
    offenders = [p for p in forbidden if p.exists()]
    assert offenders == [], f"unexpected __init__.py files: {offenders}"


def test_parrot_resolves_to_host():
    """The host owns parrot.__init__; satellite does not shadow it."""
    importlib.invalidate_caches()
    import parrot
    assert "ai-parrot/src/parrot/__init__.py" in parrot.__file__
