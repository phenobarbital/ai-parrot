"""Smoke tests for TASK-1336: reranker backends moved to satellite."""
import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize("backend", ["local", "llm"])
def test_backend_resolves_to_satellite(backend):
    """Moved backend modules resolve inside the satellite distribution."""
    importlib.invalidate_caches()
    mod = importlib.import_module(f"parrot.rerankers.{backend}")
    assert "ai-parrot-embeddings" in mod.__file__, (
        f"Expected {backend} to resolve inside ai-parrot-embeddings, "
        f"but got: {mod.__file__}"
    )


def test_lazy_getattr_still_resolves():
    """The host's __getattr__ lazy loader still returns the satellite-supplied classes."""
    from parrot.rerankers import LocalCrossEncoderReranker, LLMReranker
    assert LocalCrossEncoderReranker.__module__ == "parrot.rerankers.local"
    assert LLMReranker.__module__ == "parrot.rerankers.llm"


def test_factory_still_resolves():
    """create_reranker's local-import dispatch still finds the moved classes."""
    from parrot.rerankers.factory import create_reranker  # smoke import only
    assert create_reranker is not None


def test_satellite_did_not_create_rerankers_init():
    """Satellite did not accidentally create __init__.py at the rerankers level."""
    init = (
        Path(__file__).parent.parent
        / "src" / "parrot" / "rerankers" / "__init__.py"
    )
    assert not init.exists(), f"forbidden file: {init}"
