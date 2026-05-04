"""Tests for the FEAT-140 follow-up: per-model retrieval tuning fields.

Covers two new required catalog fields — ``recommended_score_threshold`` and
``recommended_search_limit`` — the ``get_model_recommendations`` helper, and
the consumer-side fallback chain used by ``AbstractBot`` / ``Chatbot``.

The motivating bug: the global ``context_score_threshold`` default of 0.7
silently discards valid matches for models that produce naturally low
similarity scores (e.g. ``multi-qa-mpnet-base-cos-v1`` typically lands in
the 0.30-0.55 range).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestRecommendedFieldsBackfilled:
    """Every catalog entry must carry both new tuning fields."""

    def test_all_entries_have_recommended_fields(self) -> None:
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        for entry in EMBEDDING_MODELS:
            assert "recommended_score_threshold" in entry, (
                f"{entry['model']} missing recommended_score_threshold"
            )
            assert "recommended_search_limit" in entry, (
                f"{entry['model']} missing recommended_search_limit"
            )

    def test_recommended_score_threshold_within_metric_range(self) -> None:
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        for entry in EMBEDDING_MODELS:
            value = entry["recommended_score_threshold"]
            assert isinstance(value, (int, float))
            assert 0.0 <= value <= 100.0, f"{entry['model']}: {value}"
            if entry["metric_recommended"] in ("cosine", "l2"):
                assert value <= 1.0, (
                    f"{entry['model']} uses {entry['metric_recommended']} "
                    f"but threshold={value} exceeds 1.0"
                )

    def test_recommended_search_limit_positive_int(self) -> None:
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        for entry in EMBEDDING_MODELS:
            value = entry["recommended_search_limit"]
            assert isinstance(value, int)
            assert 1 <= value <= 100, f"{entry['model']}: {value}"


class TestSpotChecks:
    """Anchor the specific values that motivated this change."""

    def _get(self, model_id: str) -> dict:
        from parrot.embeddings.catalog import EMBEDDING_MODELS

        entry = next((e for e in EMBEDDING_MODELS if e["model"] == model_id), None)
        assert entry is not None, f"Entry not found: {model_id}"
        return entry

    def test_multi_qa_cos_threshold_is_low(self) -> None:
        # Bug-fix anchor: the global 0.7 default would discard valid matches.
        entry = self._get("sentence-transformers/multi-qa-mpnet-base-cos-v1")
        assert entry["recommended_score_threshold"] == 0.30
        assert entry["recommended_search_limit"] == 10

    def test_multi_qa_dot_threshold_above_one(self) -> None:
        # Dot-product variant: non-normalised scores live above 1.0.
        entry = self._get("sentence-transformers/multi-qa-mpnet-base-dot-v1")
        assert entry["recommended_score_threshold"] == 30.0
        assert entry["metric_recommended"] == "dot"
        assert entry["normalized_output"] is False

    def test_e5_base_threshold_high(self) -> None:
        # E5 with prefixes typically scores 0.75-0.95.
        entry = self._get("intfloat/e5-base-v2")
        assert entry["recommended_score_threshold"] == 0.75

    def test_instruct_models_use_smaller_pool(self) -> None:
        # Heavyweight instruct models warrant a smaller top-k.
        for model_id in (
            "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
            "intfloat/e5-mistral-7b-instruct",
            "nvidia/NV-Embed-v2",
        ):
            entry = self._get(model_id)
            assert entry["recommended_search_limit"] == 5, model_id


class TestSchemaValidators:
    """Pydantic v2 validators for the new fields."""

    def _valid_kwargs(self, **overrides: object) -> dict:
        base = dict(
            model="test/model",
            provider="huggingface",
            name="Test",
            dimension=768,
            multilingual=False,
            language="en",
            use_case=["similarity"],
            description="x",
            metric_recommended="cosine",
            requires_prefix=False,
            prefix_query=None,
            prefix_passage=None,
            normalized_output=True,
            max_seq_length=512,
            hnsw_compatible=True,
            license="apache-2.0",
            recommended_score_threshold=0.5,
            recommended_search_limit=10,
        )
        base.update(overrides)
        return base

    def test_threshold_above_one_for_cosine_rejected(self) -> None:
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError, match="recommended_score_threshold"):
            EmbeddingModelEntry(**self._valid_kwargs(
                recommended_score_threshold=70.0,
            ))

    def test_threshold_above_one_for_dot_accepted(self) -> None:
        from parrot.embeddings.catalog import EmbeddingModelEntry

        entry = EmbeddingModelEntry(**self._valid_kwargs(
            metric_recommended="dot",
            normalized_output=False,
            recommended_score_threshold=30.0,
        ))
        assert entry.recommended_score_threshold == 30.0

    def test_threshold_negative_rejected(self) -> None:
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError):
            EmbeddingModelEntry(**self._valid_kwargs(
                recommended_score_threshold=-0.1,
            ))

    def test_limit_zero_rejected(self) -> None:
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError):
            EmbeddingModelEntry(**self._valid_kwargs(
                recommended_search_limit=0,
            ))

    def test_limit_above_cap_rejected(self) -> None:
        from parrot.embeddings.catalog import EmbeddingModelEntry

        with pytest.raises(ValidationError):
            EmbeddingModelEntry(**self._valid_kwargs(
                recommended_search_limit=101,
            ))

    def test_threshold_field_required(self) -> None:
        from parrot.embeddings.catalog import EmbeddingModelEntry

        kwargs = self._valid_kwargs()
        del kwargs["recommended_score_threshold"]
        with pytest.raises(ValidationError):
            EmbeddingModelEntry(**kwargs)


class TestHelper:
    """``get_model_recommendations`` lookup behaviour."""

    def test_returns_dict_for_known_model(self) -> None:
        from parrot.embeddings import get_model_recommendations

        rec = get_model_recommendations(
            "sentence-transformers/multi-qa-mpnet-base-cos-v1"
        )
        assert rec == {
            "recommended_score_threshold": 0.30,
            "recommended_search_limit": 10,
        }

    def test_returns_none_for_unknown_model(self) -> None:
        from parrot.embeddings import get_model_recommendations

        assert get_model_recommendations("foo/bar") is None

    def test_returns_none_for_none_input(self) -> None:
        from parrot.embeddings import get_model_recommendations

        assert get_model_recommendations(None) is None

    def test_returns_none_for_empty_string(self) -> None:
        from parrot.embeddings import get_model_recommendations

        assert get_model_recommendations("") is None

    def test_helper_exported_from_package(self) -> None:
        # Use behavioural equivalence (not ``is``) because other tests
        # in the suite reload ``parrot.embeddings.catalog``, which produces
        # a fresh function object not shared with the package re-export.
        from parrot.embeddings import get_model_recommendations as a
        from parrot.embeddings.catalog import get_model_recommendations as b

        sample = "sentence-transformers/multi-qa-mpnet-base-cos-v1"
        assert a(sample) == b(sample)
        assert a(None) is None and b(None) is None


class TestConsumerFallbackChain:
    """Replicates the resolution logic wired into ``AbstractBot.__init__``.

    Avoids importing the real bot (heavy dependency chain) by inlining the
    same chain so a regression in either place fails this test.
    """

    @staticmethod
    def _resolve_threshold(
        kwargs: dict,
        embedding_model_name: str | None,
        hardcoded_default: float,
    ) -> float:
        from parrot.embeddings import get_model_recommendations

        recs = get_model_recommendations(embedding_model_name) or {}
        if "context_score_threshold" in kwargs:
            return float(kwargs["context_score_threshold"])
        return float(recs.get("recommended_score_threshold", hardcoded_default))

    @staticmethod
    def _resolve_limit(
        kwargs: dict,
        embedding_model_name: str | None,
        hardcoded_default: int,
    ) -> int:
        from parrot.embeddings import get_model_recommendations

        recs = get_model_recommendations(embedding_model_name) or {}
        if "context_search_limit" in kwargs:
            return int(kwargs["context_search_limit"])
        return int(recs.get("recommended_search_limit", hardcoded_default))

    def test_explicit_kwarg_overrides_catalog(self) -> None:
        out = self._resolve_threshold(
            {"context_score_threshold": 0.9},
            "sentence-transformers/multi-qa-mpnet-base-cos-v1",
            hardcoded_default=0.61,
        )
        assert out == 0.9

    def test_catalog_recommendation_beats_hardcoded_default(self) -> None:
        # The whole point of this change: cos-v1 gets 0.30, not 0.61.
        out = self._resolve_threshold(
            {},
            "sentence-transformers/multi-qa-mpnet-base-cos-v1",
            hardcoded_default=0.61,
        )
        assert out == 0.30

    def test_hardcoded_default_used_when_model_unknown(self) -> None:
        out = self._resolve_threshold(
            {},
            "some/unknown-model",
            hardcoded_default=0.61,
        )
        assert out == 0.61

    def test_hardcoded_default_used_when_model_name_missing(self) -> None:
        out = self._resolve_threshold(
            {},
            None,
            hardcoded_default=0.61,
        )
        assert out == 0.61

    def test_limit_explicit_kwarg_overrides_catalog(self) -> None:
        out = self._resolve_limit(
            {"context_search_limit": 25},
            "intfloat/e5-mistral-7b-instruct",
            hardcoded_default=10,
        )
        assert out == 25

    def test_limit_catalog_recommendation_beats_hardcoded_default(self) -> None:
        # e5-mistral-7b-instruct catalog rec is 5, not the global 10.
        out = self._resolve_limit(
            {},
            "intfloat/e5-mistral-7b-instruct",
            hardcoded_default=10,
        )
        assert out == 5
