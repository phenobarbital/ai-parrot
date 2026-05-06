"""Unit tests for MatryoshkaConfig and validate_against_catalog.

Tests spec §3 Module 1 — the Pydantic config model and the catalog validator.
No real model weights are loaded here; all tests operate purely on
configuration objects and the in-memory catalog.
"""
import pytest
from pydantic import ValidationError

from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog
from parrot.exceptions import ConfigError


class TestMatryoshkaConfig:
    """Tests for the MatryoshkaConfig Pydantic model."""

    def test_default_disabled(self):
        """Default construction yields disabled config with no dimension."""
        cfg = MatryoshkaConfig()
        assert cfg.enabled is False
        assert cfg.dimension is None

    def test_enabled_requires_dimension(self):
        """enabled=True without dimension must raise ValidationError."""
        with pytest.raises(ValidationError):
            MatryoshkaConfig(enabled=True)

    def test_dimension_must_be_positive(self):
        """dimension=0 is invalid (gt=0 constraint)."""
        with pytest.raises(ValidationError):
            MatryoshkaConfig(enabled=True, dimension=0)

    def test_disabled_with_dimension_ok(self):
        """enabled=False with a dimension provided is acceptable."""
        cfg = MatryoshkaConfig(enabled=False, dimension=512)
        assert cfg.enabled is False
        assert cfg.dimension == 512

    def test_enabled_with_valid_dimension(self):
        """enabled=True with a positive dimension builds cleanly."""
        cfg = MatryoshkaConfig(enabled=True, dimension=256)
        assert cfg.enabled is True
        assert cfg.dimension == 256

    def test_negative_dimension_raises(self):
        """Negative dimension must raise ValidationError."""
        with pytest.raises(ValidationError):
            MatryoshkaConfig(enabled=True, dimension=-1)


class TestValidateAgainstCatalog:
    """Tests for validate_against_catalog."""

    def test_disabled_skips_validation(self):
        """When enabled=False, validation is skipped even for unknown models."""
        cfg = MatryoshkaConfig(enabled=False)
        assert validate_against_catalog(cfg, "anything-goes") is None

    def test_disabled_with_dim_skips_validation(self):
        """When enabled=False with dimension set, validation is still skipped."""
        cfg = MatryoshkaConfig(enabled=False, dimension=512)
        assert validate_against_catalog(cfg, "does-not-exist/foo") is None

    def test_supported_model_and_dim(self):
        """A valid model+dimension combination passes silently."""
        cfg = MatryoshkaConfig(enabled=True, dimension=512)
        assert validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5") is None

    def test_supported_model_other_dims(self):
        """All declared dims for nomic should pass."""
        for dim in [64, 128, 256, 512, 768]:
            cfg = MatryoshkaConfig(enabled=True, dimension=dim)
            assert validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5") is None

    def test_mxbai_supported_dims(self):
        """mxbai-embed-large-v1 dims should all pass."""
        for dim in [128, 256, 512, 768, 1024]:
            cfg = MatryoshkaConfig(enabled=True, dimension=dim)
            assert validate_against_catalog(cfg, "mixedbread-ai/mxbai-embed-large-v1") is None

    def test_unsupported_dim(self):
        """A dimension not in the allowed list raises ConfigError."""
        cfg = MatryoshkaConfig(enabled=True, dimension=300)
        with pytest.raises(ConfigError, match="matryoshka_dimensions"):
            validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5")

    def test_model_without_matryoshka_metadata(self):
        """A catalog model without matryoshka_dimensions raises ConfigError."""
        cfg = MatryoshkaConfig(enabled=True, dimension=512)
        with pytest.raises(ConfigError):
            validate_against_catalog(cfg, "BAAI/bge-base-en-v1.5")

    def test_unknown_model(self):
        """A model not in EMBEDDING_MODELS raises ConfigError."""
        cfg = MatryoshkaConfig(enabled=True, dimension=512)
        with pytest.raises(ConfigError):
            validate_against_catalog(cfg, "does-not-exist/foo")

    def test_error_message_names_allowed_dims(self):
        """ConfigError for wrong dim should mention the allowed list."""
        cfg = MatryoshkaConfig(enabled=True, dimension=300)
        with pytest.raises(ConfigError, match="64"):
            validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5")

    def test_error_message_names_model(self):
        """ConfigError for wrong dim should mention the model name."""
        cfg = MatryoshkaConfig(enabled=True, dimension=300)
        with pytest.raises(ConfigError, match="nomic"):
            validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5")
