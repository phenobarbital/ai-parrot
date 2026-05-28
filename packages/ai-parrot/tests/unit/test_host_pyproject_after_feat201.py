"""Tests verifying the host pyproject.toml changes from FEAT-201 (TASK-1337)."""
import tomllib
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def host_pyproject() -> dict:
    """Load the host pyproject.toml."""
    text = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    return tomllib.loads(text)


def test_moved_extras_gone(host_pyproject):
    """Extras that moved to ai-parrot-embeddings no longer exist in the host."""
    extras = host_pyproject["project"]["optional-dependencies"]
    for name in ("embeddings", "milvus", "chroma", "arango"):
        assert name not in extras, f"host still declares the {name!r} extra"


def test_pgvector_extracted_from_images(host_pyproject):
    """pgvector no longer rides inside the images extra."""
    images = host_pyproject["project"]["optional-dependencies"]["images"]
    pgvector_lines = [d for d in images if d.startswith("pgvector")]
    assert pgvector_lines == [], f"pgvector still in images: {pgvector_lines}"


def test_faiss_cpu_in_core_deps(host_pyproject):
    """faiss-cpu must remain a core dependency for episodic memory."""
    deps = host_pyproject["project"]["dependencies"]
    assert any(d.startswith("faiss-cpu") for d in deps), (
        f"faiss-cpu missing from core deps: {deps}"
    )


def test_all_meta_extra_includes_satellite(host_pyproject):
    """pip install ai-parrot[all] must reach ai-parrot-embeddings[all]."""
    all_extra = host_pyproject["project"]["optional-dependencies"]["all"]
    assert any("ai-parrot-embeddings" in d for d in all_extra), (
        f"all meta-extra missing satellite ref: {all_extra}"
    )


def test_all_fast_meta_extra_includes_satellite(host_pyproject):
    """pip install ai-parrot[all-fast] must reach ai-parrot-embeddings."""
    fast = host_pyproject["project"]["optional-dependencies"]["all-fast"]
    assert any("ai-parrot-embeddings" in d for d in fast), (
        f"all-fast missing satellite ref: {fast}"
    )


def test_namespaces_setting_preserved(host_pyproject):
    """Namespace discovery must stay enabled."""
    find = host_pyproject["tool"]["setuptools"]["packages"]["find"]
    assert find["namespaces"] is True
    assert find["include"] == ["parrot*"]
    assert find["where"] == ["src"]
