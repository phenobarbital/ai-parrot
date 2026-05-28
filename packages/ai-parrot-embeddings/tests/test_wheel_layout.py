"""Wheel-content verification test for TASK-1338.

Locks the U3 decision (pure PEP 420) into CI:
- The satellite wheel must NOT contain __init__.py at any of the four
  namespace levels.
- The satellite wheel MUST contain all expected backend .py files.
"""
import pytest


FORBIDDEN_INIT_PATHS = [
    "parrot/__init__.py",
    "parrot/embeddings/__init__.py",
    "parrot/stores/__init__.py",
    "parrot/rerankers/__init__.py",
]

EXPECTED_BACKENDS = [
    "parrot/embeddings/google.py",
    "parrot/embeddings/huggingface.py",
    "parrot/embeddings/openai.py",
    "parrot/stores/postgres.py",
    "parrot/stores/pgvector.py",
    "parrot/stores/faiss_store.py",
    "parrot/stores/milvus.py",
    "parrot/stores/arango.py",
    "parrot/stores/bigquery.py",
    "parrot/rerankers/local.py",
    "parrot/rerankers/llm.py",
]


class TestWheelHasNoInitAtNamespaceLevels:
    """U3: pure PEP 420 — no __init__.py at the four namespace levels."""

    @pytest.mark.parametrize("forbidden", FORBIDDEN_INIT_PATHS)
    def test_no_init_at(self, satellite_wheel_namelist, forbidden):
        """Assert the satellite wheel does not contain the forbidden __init__.py."""
        assert forbidden not in satellite_wheel_namelist, (
            f"satellite wheel must not contain {forbidden!r} "
            f"(violates U3 / pure PEP 420 namespace package). "
            f"Found names: {[n for n in satellite_wheel_namelist if forbidden in n]}"
        )


class TestWheelContainsExpectedBackends:
    """The moved backends must actually ship in the wheel."""

    @pytest.mark.parametrize("expected", EXPECTED_BACKENDS)
    def test_present(self, satellite_wheel_namelist, expected):
        """Assert the satellite wheel contains the expected backend file."""
        assert expected in satellite_wheel_namelist, (
            f"satellite wheel missing {expected!r}. "
            f"Available parrot/ entries: "
            f"{[n for n in satellite_wheel_namelist if n.startswith('parrot/')]}"
        )
