"""Cross-consistency between EMBEDDING_MODELS and _resolve_prefixes.

The catalog and the loader's prefix resolver are kept in sync by this test:
adding a prefix-requiring model on either side without the matching
counterpart will fail CI.

Two directions of the consistency check:

1. Catalog -> Resolver: for every HuggingFace entry in the catalog,
   _resolve_prefixes(entry["model"]) must equal
   (entry["prefix_query"], entry["prefix_passage"]).

2. Resolver -> Catalog: every "known prefix model" (per spec §4) must exist
   in the catalog with requires_prefix=True and a matching prefix pair.

Covers TASK-966.
"""
import pytest

from parrot.embeddings.catalog import EMBEDDING_MODELS
from parrot.embeddings.huggingface import _resolve_prefixes


@pytest.fixture
def hf_catalog_entries() -> list[dict]:
    """Entries that the resolver actually serves (HuggingFace only)."""
    return [e for e in EMBEDDING_MODELS if e["provider"] == "huggingface"]


@pytest.fixture
def known_prefix_models() -> list[str]:
    """Models that MUST be handled by both sides (per spec §4)."""
    return [
        "intfloat/e5-base-v2",
        "intfloat/e5-large-v2",
        "intfloat/multilingual-e5-base",
        "intfloat/multilingual-e5-large",
        "BAAI/bge-small-en-v1.5",
        "BAAI/bge-base-en-v1.5",
        "BAAI/bge-large-en-v1.5",
        "jinaai/jina-embeddings-v3",
        "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        "intfloat/e5-mistral-7b-instruct",
        "nvidia/NV-Embed-v2",
    ]


class TestCatalogToResolver:
    """Direction 1: every catalog HF entry must match the resolver output."""

    def test_every_hf_entry_matches_resolver(self, hf_catalog_entries):
        """For each HF entry, _resolve_prefixes(model) == (prefix_query, prefix_passage).

        Collects all mismatches before failing so the human sees the full picture.
        """
        mismatches = []
        for entry in hf_catalog_entries:
            expected = (entry["prefix_query"], entry["prefix_passage"])
            actual = _resolve_prefixes(entry["model"])
            if actual != expected:
                mismatches.append(
                    f"{entry['model']}:\n"
                    f"  catalog  = {expected!r}\n"
                    f"  resolver = {actual!r}"
                )
        assert not mismatches, (
            "Catalog <-> resolver mismatch (catalog -> resolver direction):\n"
            + "\n".join(mismatches)
        )

    def test_no_hf_entry_has_prefix_false_with_nonnone_prefix(
        self, hf_catalog_entries
    ):
        """requires_prefix=False with a non-None prefix is a catalog defect.

        This is already enforced by EmbeddingModelEntry, but an explicit
        test at the integration layer makes the contract visible.
        """
        problems = []
        for entry in hf_catalog_entries:
            if not entry["requires_prefix"]:
                if entry["prefix_query"] or entry["prefix_passage"]:
                    problems.append(
                        f"{entry['model']}: requires_prefix=False but "
                        f"prefix_query={entry['prefix_query']!r}, "
                        f"prefix_passage={entry['prefix_passage']!r}"
                    )
        assert not problems, "\n".join(problems)


class TestResolverToCatalog:
    """Direction 2: every known prefix model must be in the catalog with the right flags."""

    def test_every_known_model_in_catalog(self, known_prefix_models):
        """All 11 known prefix-requiring models must appear in EMBEDDING_MODELS."""
        catalog_names = {e["model"] for e in EMBEDDING_MODELS}
        missing = [m for m in known_prefix_models if m not in catalog_names]
        assert not missing, (
            "Resolver knows but catalog is missing: " + str(missing)
        )

    def test_every_known_model_requires_prefix(self, known_prefix_models):
        """All 11 known models must have requires_prefix=True in the catalog."""
        problems = []
        for name in known_prefix_models:
            entry = next(
                (e for e in EMBEDDING_MODELS if e["model"] == name), None
            )
            if entry is None:
                continue  # caught by test_every_known_model_in_catalog
            if entry["requires_prefix"] is not True:
                problems.append(
                    f"{name}: requires_prefix={entry['requires_prefix']}"
                )
        assert not problems, "\n".join(problems)

    def test_every_known_model_prefix_pair_matches(self, known_prefix_models):
        """For each known model, catalog prefix pair must equal resolver output.

        Collects all mismatches before failing.
        """
        problems = []
        for name in known_prefix_models:
            entry = next(
                (e for e in EMBEDDING_MODELS if e["model"] == name), None
            )
            if entry is None:
                continue  # caught by test_every_known_model_in_catalog
            expected = (entry["prefix_query"], entry["prefix_passage"])
            actual = _resolve_prefixes(name)
            if actual != expected:
                problems.append(
                    f"{name}:\n"
                    f"  catalog  = {expected!r}\n"
                    f"  resolver = {actual!r}"
                )
        assert not problems, (
            "Catalog <-> resolver mismatch (resolver -> catalog direction):\n"
            + "\n".join(problems)
        )
