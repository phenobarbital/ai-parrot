"""Shared fixtures for the ai-parrot-embeddings test suite."""
import importlib.util
import subprocess
import zipfile
from pathlib import Path

import pytest


def _package_available(name: str) -> bool:
    """Return True if the given package is importable."""
    return importlib.util.find_spec(name) is not None


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "requires_huggingface: requires the huggingface extra (sentence-transformers)",
    )
    config.addinivalue_line(
        "markers",
        "requires_faiss: requires the faiss extra (faiss-cpu — always present in core)",
    )
    config.addinivalue_line(
        "markers",
        "requires_pgvector: requires the pgvector extra",
    )
    config.addinivalue_line(
        "markers",
        "requires_milvus: requires the milvus extra",
    )


def pytest_runtest_setup(item):
    """Auto-skip tests that require unavailable extras."""
    markers = {m.name for m in item.iter_markers()}
    if "requires_huggingface" in markers:
        if not _package_available("sentence_transformers"):
            pytest.skip("requires huggingface extra (sentence-transformers)")
    if "requires_milvus" in markers:
        if not _package_available("pymilvus"):
            pytest.skip("requires milvus extra (pymilvus)")
    if "requires_pgvector" in markers:
        if not _package_available("pgvector"):
            pytest.skip("requires pgvector extra")


@pytest.fixture(scope="session")
def satellite_pkg_root() -> Path:
    """Return the root of the satellite package directory."""
    # This file lives at packages/ai-parrot-embeddings/tests/conftest.py
    return Path(__file__).parent.parent.resolve()


@pytest.fixture(scope="session")
def satellite_wheel_path(satellite_pkg_root, tmp_path_factory) -> Path:
    """Build the satellite wheel once per session and return its path."""
    out_dir = tmp_path_factory.mktemp("wheel")
    subprocess.check_call(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir), str(satellite_pkg_root)],
    )
    wheels = list(out_dir.glob("ai_parrot_embeddings-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"
    return wheels[0]


@pytest.fixture(scope="session")
def satellite_wheel_namelist(satellite_wheel_path) -> list[str]:
    """All filenames inside the satellite wheel (slash-separated)."""
    with zipfile.ZipFile(satellite_wheel_path) as zf:
        return zf.namelist()


@pytest.fixture
def host_pyproject_text() -> str:
    """The host's current pyproject.toml text."""
    # Navigate from tests/ up to packages/ai-parrot-embeddings then to packages/ai-parrot
    here = Path(__file__).parent.parent.parent  # packages/
    return (here / "ai-parrot" / "pyproject.toml").read_text(encoding="utf-8")
