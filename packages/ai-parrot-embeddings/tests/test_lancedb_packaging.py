"""Manifest contract for the optional LanceDB extra (FEAT-542, AC1).

Reads pyproject.toml directly: these assertions must hold whether or not the
extra is installed in the running environment.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"

_EXPECTED_ALL_BACKENDS = (
    "huggingface",
    "google",
    "openai",
    "pgvector",
    "milvus",
    "arango",
    "bigquery",
    "faiss",
    "chroma",
    "lancedb",
    "reranker-local",
    "reranker-llm",
    "multimodal",
)


@pytest.fixture(scope="module")
def extras() -> dict:
    return tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]


def test_lancedb_extra_declares_exact_pin(extras):
    """The lancedb extra exists and pins one exact version."""
    assert "lancedb" in extras
    reqs = extras["lancedb"]
    assert len(reqs) == 1
    assert reqs[0] == "lancedb==0.38.0"
    assert "==" in reqs[0]
    assert not any(op in reqs[0] for op in (">=", "<=", "~=", ">", "<")) or reqs[0].count("==") == 1


def test_all_aggregator_includes_lancedb_without_dropping_backends(extras):
    """The all extra gains lancedb and keeps every pre-existing name."""
    assert "all" in extras
    assert len(extras["all"]) == 1
    aggregator = extras["all"][0]
    for backend in _EXPECTED_ALL_BACKENDS:
        assert backend in aggregator, f"{backend!r} missing from [all] aggregator"


def test_importing_core_does_not_require_the_sdk():
    """parrot.stores imports cleanly with no lancedb installed (subprocess-isolated)."""
    script = (
        "import sys, builtins\n"
        "_real_import = builtins.__import__\n"
        "def _blocked(name, *a, **k):\n"
        "    if name == 'lancedb' or name.startswith('lancedb.'):\n"
        "        raise ImportError('lancedb must not be imported here')\n"
        "    return _real_import(name, *a, **k)\n"
        "builtins.__import__ = _blocked\n"
        "import parrot.stores\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
