"""Tests for the extended USE_CASE_DESCRIPTIONS taxonomy and tag assignments.

Covers TASK-964: five new use-case tags (qa, long-context, instruct,
asymmetric, symmetric) and their assignment to existing catalog entries.
"""
import pytest
from parrot.embeddings.catalog import (
    EMBEDDING_MODELS,
    USE_CASE_DESCRIPTIONS,
    get_use_cases,
)


class TestUseCaseDescriptionsExtended:
    """Verify the taxonomy dictionary has all 10 expected keys."""

    def test_original_five_preserved(self):
        """Original 5 use-case keys must still be present."""
        for key in ("similarity", "retrieval", "clustering", "multilingual", "code"):
            assert key in USE_CASE_DESCRIPTIONS, (
                f"Original key '{key}' missing from USE_CASE_DESCRIPTIONS"
            )

    def test_five_new_keys_present(self):
        """New 5 use-case keys must be present."""
        for key in ("qa", "long-context", "instruct", "asymmetric", "symmetric"):
            assert key in USE_CASE_DESCRIPTIONS, (
                f"New key '{key}' missing from USE_CASE_DESCRIPTIONS"
            )

    def test_get_use_cases_returns_ten_keys(self):
        """get_use_cases() must return a dict with at least 10 keys."""
        result = get_use_cases()
        expected = {
            "similarity", "retrieval", "clustering", "multilingual", "code",
            "qa", "long-context", "instruct", "asymmetric", "symmetric",
        }
        assert expected.issubset(result.keys()), (
            f"Missing keys: {expected - result.keys()}"
        )

    def test_all_descriptions_are_non_empty(self):
        """Every description string must be non-empty."""
        for key, desc in USE_CASE_DESCRIPTIONS.items():
            assert desc and desc.strip(), (
                f"USE_CASE_DESCRIPTIONS['{key}'] is empty"
            )


class TestTagAssignmentRules:
    """Verify new tags are correctly assigned to existing and new entries."""

    def test_multi_qa_models_have_qa_tag(self):
        """All multi-qa-* models must carry the 'qa' tag."""
        for entry in EMBEDDING_MODELS:
            if "multi-qa-" in entry["model"]:
                assert "qa" in entry["use_case"], (
                    f"{entry['model']} is missing 'qa' tag"
                )

    def test_paraphrase_models_have_symmetric_tag(self):
        """All paraphrase-* models must carry the 'symmetric' tag."""
        for entry in EMBEDDING_MODELS:
            if "paraphrase-" in entry["model"]:
                assert "symmetric" in entry["use_case"], (
                    f"{entry['model']} is missing 'symmetric' tag"
                )

    def test_long_context_tag_for_4k_plus_models(self):
        """Every model with max_seq_length >= 4096 must have 'long-context'."""
        for entry in EMBEDDING_MODELS:
            if entry["max_seq_length"] >= 4096:
                assert "long-context" in entry["use_case"], (
                    f"{entry['model']} (max_seq_length={entry['max_seq_length']}) "
                    f"is missing 'long-context' tag"
                )

    def test_e5_family_has_asymmetric_tag(self):
        """E5 non-instruct models must carry 'asymmetric'."""
        for entry in EMBEDDING_MODELS:
            name = entry["model"].lower()
            is_e5 = (
                ("/e5-" in name or "intfloat/e5" in name or "multilingual-e5" in name)
                and "-instruct" not in name
            )
            if is_e5:
                assert "asymmetric" in entry["use_case"], (
                    f"{entry['model']} (E5 family) missing 'asymmetric' tag"
                )

    def test_bge_en_v15_has_asymmetric_tag(self):
        """BGE English v1.5 models must carry 'asymmetric'."""
        for entry in EMBEDDING_MODELS:
            name = entry["model"].lower()
            is_bge_en = "baai/bge-" in name and "en-v1.5" in name
            if is_bge_en:
                assert "asymmetric" in entry["use_case"], (
                    f"{entry['model']} (BGE-EN-v1.5) missing 'asymmetric' tag"
                )

    def test_instruct_models_have_instruct_tag(self):
        """All *-instruct and nv-embed-v2 models must carry 'instruct'."""
        for entry in EMBEDDING_MODELS:
            name = entry["model"].lower()
            if "instruct" in name or "nv-embed-v2" in name:
                assert "instruct" in entry["use_case"], (
                    f"{entry['model']} (instruct model) missing 'instruct' tag"
                )

    def test_bge_m3_has_long_context_tag(self):
        """BAAI/bge-m3 has 8192 ctx and must have 'long-context'."""
        entry = next(
            (e for e in EMBEDDING_MODELS if e["model"] == "BAAI/bge-m3"), None
        )
        assert entry is not None, "BAAI/bge-m3 not found in catalog"
        assert "long-context" in entry["use_case"], (
            "BAAI/bge-m3 missing 'long-context' tag"
        )

    def test_jina_v2_long_context_entries_tagged(self):
        """Jina v2 models with 8192-token context must have 'long-context'."""
        jina_v2_models = [
            "jinaai/jina-embeddings-v2-base-code",
            "jinaai/jina-embeddings-v2-base-en",
        ]
        for model_id in jina_v2_models:
            entry = next(
                (e for e in EMBEDDING_MODELS if e["model"] == model_id), None
            )
            if entry is not None:
                assert "long-context" in entry["use_case"], (
                    f"{model_id} (8192-token context) missing 'long-context' tag"
                )


class TestNoTagRegressions:
    """Verify that adding new tags did not accidentally remove any existing ones."""

    # Snapshot of original tags per model (based on the pre-TASK-962 catalog)
    _original_tags = {
        "sentence-transformers/all-mpnet-base-v2": {"similarity", "clustering"},
        "sentence-transformers/all-MiniLM-L12-v2": {"similarity", "clustering"},
        "sentence-transformers/all-MiniLM-L6-v2": {"similarity"},
        "thenlper/gte-small": {"retrieval", "similarity"},
        "thenlper/gte-base": {"retrieval", "similarity"},
        "thenlper/gte-large": {"retrieval", "similarity"},
        "sentence-transformers/msmarco-MiniLM-L12-v3": {"retrieval"},
        "sentence-transformers/multi-qa-mpnet-base-dot-v1": {"retrieval"},
        "sentence-transformers/msmarco-distilbert-base-v4": {"retrieval"},
        "sentence-transformers/gtr-t5-large": {"retrieval"},
        "intfloat/e5-base-v2": {"retrieval"},
        "intfloat/e5-large-v2": {"retrieval"},
        "intfloat/multilingual-e5-base": {"retrieval", "multilingual"},
        "intfloat/multilingual-e5-large": {"retrieval", "multilingual"},
        "BAAI/bge-small-en-v1.5": {"retrieval", "clustering"},
        "BAAI/bge-base-en-v1.5": {"retrieval", "clustering"},
        "BAAI/bge-large-en-v1.5": {"retrieval", "clustering"},
        "BAAI/bge-m3": {"retrieval", "multilingual"},
        "Alibaba-NLP/gte-multilingual-base": {"retrieval", "multilingual"},
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": {
            "similarity", "multilingual"
        },
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2": {
            "similarity", "multilingual", "clustering"
        },
        "jinaai/jina-embeddings-v2-base-code": {"code", "retrieval"},
        "jinaai/jina-embeddings-v2-base-en": {"retrieval", "similarity"},
        "nomic-ai/nomic-embed-text-v1.5": {"retrieval", "clustering", "similarity"},
        "mixedbread-ai/mxbai-embed-large-v1": {"retrieval", "clustering"},
        "google/embeddinggemma-300m": {
            "retrieval", "similarity", "clustering", "multilingual"
        },
        "Snowflake/snowflake-arctic-embed-s": {"retrieval"},
        "Snowflake/snowflake-arctic-embed-m-v1.5": {"retrieval", "clustering"},
        "Snowflake/snowflake-arctic-embed-l": {"retrieval"},
        "text-embedding-3-large": {
            "retrieval", "similarity", "clustering", "multilingual"
        },
        "text-embedding-3-small": {"retrieval", "similarity", "multilingual"},
        "gemini-embedding-001": {"retrieval", "similarity", "multilingual"},
    }

    def test_original_tags_preserved(self):
        """No entry should have lost any tag it held before the taxonomy extension."""
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        catalog_map = {e["model"]: set(e["use_case"]) for e in EMBEDDING_MODELS}
        failures = []
        for model_id, original in self._original_tags.items():
            if model_id not in catalog_map:
                # Model was intentionally removed (ada-002) — skip.
                continue
            missing = original - catalog_map[model_id]
            if missing:
                failures.append(
                    f"{model_id}: lost tags {missing}"
                )
        assert not failures, "Tag regressions detected:\n" + "\n".join(failures)
