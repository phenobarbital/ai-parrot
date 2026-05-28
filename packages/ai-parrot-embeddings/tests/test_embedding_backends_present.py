"""Smoke tests for TASK-1334: embedding backends moved to satellite."""
import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize("backend", ["google", "huggingface", "openai"])
def test_backend_resolves_to_satellite(backend):
    """Moved backend modules resolve inside the satellite distribution."""
    importlib.invalidate_caches()
    mod = importlib.import_module(f"parrot.embeddings.{backend}")
    assert "ai-parrot-embeddings" in mod.__file__, (
        f"Expected {backend} to resolve inside ai-parrot-embeddings, "
        f"but got: {mod.__file__}"
    )


def test_satellite_does_not_create_embeddings_init():
    """Satellite did not accidentally create __init__.py at the embeddings level."""
    init = (
        Path(__file__).parent.parent
        / "src" / "parrot" / "embeddings" / "__init__.py"
    )
    assert not init.exists(), f"forbidden file: {init}"
