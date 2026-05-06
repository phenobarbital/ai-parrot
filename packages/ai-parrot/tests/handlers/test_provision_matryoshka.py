"""Unit tests for _provision_vector_store Matryoshka dim-equality check.

Tests spec §3 Module 5 — the configure-time validation that rejects
``vector_store_config.dimension != embedding_model.matryoshka.dimension``
before the pgvector table is created.

The handlers conftest requires compiled Cython extensions not available in
all environments. These tests exercise the validation logic directly via
a minimal stub that avoids importing the full handler class hierarchy.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog
from parrot.exceptions import ConfigError


# ---------------------------------------------------------------------------
# Minimal reproduction of the validation logic from _provision_vector_store
# ---------------------------------------------------------------------------

async def _run_matryoshka_validation(vector_store_config: dict) -> None:
    """Extract and run ONLY the Matryoshka validation block from
    ``_provision_vector_store``. This isolates the logic under test from the
    full handler import chain.

    Raises:
        ConfigError: If the Matryoshka configuration is invalid.
    """
    dimension = vector_store_config.get("dimension", 384)
    embedding_model = vector_store_config.get("embedding_model")

    if embedding_model:
        matryoshka_dict = embedding_model.get("matryoshka")
        if isinstance(matryoshka_dict, dict) and matryoshka_dict.get("enabled"):
            try:
                cfg = MatryoshkaConfig(**matryoshka_dict)
            except Exception as exc:
                raise ConfigError(
                    f"Invalid matryoshka config in "
                    f"vector_store_config.embedding_model: {exc}"
                ) from exc
            validate_against_catalog(cfg, embedding_model.get("model_name", ""))
            if cfg.dimension != dimension:
                raise ConfigError(
                    f"vector_store_config.dimension ({dimension}) must equal "
                    f"embedding_model.matryoshka.dimension ({cfg.dimension}) "
                    f"because the pgvector column is created with the former. "
                    f"Update both values to match."
                )


class TestProvisionMatryoshkaValidation:
    """Tests for the Matryoshka dim-equality guard."""

    @pytest.mark.asyncio
    async def test_dim_match_passes(self):
        """Matching dims run without raising ConfigError."""
        cfg = {
            "table": "t",
            "schema": "s",
            "dimension": 512,
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": True, "dimension": 512},
            },
        }
        # Should not raise.
        await _run_matryoshka_validation(cfg)

    @pytest.mark.asyncio
    async def test_dim_mismatch_raises(self):
        """Mismatched dims raise ConfigError naming both values."""
        cfg = {
            "table": "t",
            "schema": "s",
            "dimension": 768,
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": True, "dimension": 512},
            },
        }
        with pytest.raises(ConfigError) as exc_info:
            await _run_matryoshka_validation(cfg)
        msg = str(exc_info.value)
        assert "768" in msg
        assert "512" in msg

    @pytest.mark.asyncio
    async def test_unsupported_dim_raises(self):
        """A dim not in catalog matryoshka_dimensions raises ConfigError."""
        cfg = {
            "table": "t",
            "schema": "s",
            "dimension": 300,
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": True, "dimension": 300},
            },
        }
        with pytest.raises(ConfigError):
            await _run_matryoshka_validation(cfg)

    @pytest.mark.asyncio
    async def test_unknown_model_raises(self):
        """A model not in the catalog raises ConfigError."""
        cfg = {
            "table": "t",
            "schema": "s",
            "dimension": 512,
            "embedding_model": {
                "model_name": "does-not-exist/foo",
                "model_type": "huggingface",
                "matryoshka": {"enabled": True, "dimension": 512},
            },
        }
        with pytest.raises(ConfigError):
            await _run_matryoshka_validation(cfg)

    @pytest.mark.asyncio
    async def test_disabled_no_validation(self):
        """When matryoshka.enabled=False, no dim check runs."""
        cfg = {
            "table": "t",
            "schema": "s",
            "dimension": 768,  # intentionally different from matryoshka.dimension
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": False, "dimension": 512},
            },
        }
        # Should NOT raise — disabled Matryoshka skips the check.
        await _run_matryoshka_validation(cfg)

    @pytest.mark.asyncio
    async def test_no_matryoshka_no_validation(self):
        """When matryoshka key is absent, no dim check runs."""
        cfg = {
            "table": "t",
            "schema": "s",
            "dimension": 768,
            "embedding_model": {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
            },
        }
        await _run_matryoshka_validation(cfg)

    @pytest.mark.asyncio
    async def test_no_embedding_model_no_validation(self):
        """When embedding_model is absent, no check runs."""
        cfg = {"table": "t", "schema": "s", "dimension": 384}
        await _run_matryoshka_validation(cfg)

    @pytest.mark.asyncio
    async def test_all_supported_models_and_dims(self):
        """All catalog-declared Matryoshka models and dims pass validation."""
        valid_cases = [
            ("nomic-ai/nomic-embed-text-v1.5", [64, 128, 256, 512, 768]),
            ("mixedbread-ai/mxbai-embed-large-v1", [128, 256, 512, 768, 1024]),
            ("google/embeddinggemma-300m", [128, 256, 512, 768]),
            ("Snowflake/snowflake-arctic-embed-m-v1.5", [128, 256, 384, 512, 768]),
        ]
        for model_name, dims in valid_cases:
            for dim in dims:
                cfg = {
                    "table": "t",
                    "schema": "s",
                    "dimension": dim,
                    "embedding_model": {
                        "model_name": model_name,
                        "model_type": "huggingface",
                        "matryoshka": {"enabled": True, "dimension": dim},
                    },
                }
                await _run_matryoshka_validation(cfg)  # should not raise
