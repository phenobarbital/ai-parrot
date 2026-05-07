"""Matryoshka Representation Learning (MRL) truncation configuration.

This module provides the operator-facing Pydantic model for the ``matryoshka``
sub-dict inside ``vector_store_config['embedding_model']``, plus a
configure-time validator that rejects unsupported truncation dimensions before
any embedding work is performed.

Usage example::

    from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog

    cfg = MatryoshkaConfig(enabled=True, dimension=512)
    validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5")  # passes silently

Shape inside ``vector_store_config``::

    {
        "embedding_model": {
            "model_name": "nomic-ai/nomic-embed-text-v1.5",
            "model_type": "huggingface",
            "matryoshka": {
                "enabled": true,
                "dimension": 512
            }
        }
    }
"""
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from parrot.embeddings.catalog import EMBEDDING_MODELS
from parrot.exceptions import ConfigError


class MatryoshkaConfig(BaseModel):
    """Operator-supplied Matryoshka truncation configuration.

    Shape::

        {"enabled": True, "dimension": 512}

    Validation lives in :func:`validate_against_catalog`, which checks that
    the chosen ``dimension`` is in the model's ``matryoshka_dimensions`` list.

    Attributes:
        enabled: When ``True``, truncation is active and ``dimension`` is
            required.  Defaults to ``False`` (no truncation).
        dimension: Target truncation dimension.  Must be a positive integer
            and must appear in the catalog's ``matryoshka_dimensions`` list
            for the requested model.  Required when ``enabled`` is ``True``.
    """

    enabled: bool = False
    dimension: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _consistency(self) -> "MatryoshkaConfig":
        """Ensure ``dimension`` is provided when truncation is enabled.

        Returns:
            The validated model instance.

        Raises:
            ValueError: When ``enabled=True`` but ``dimension`` is ``None``.
        """
        if self.enabled and self.dimension is None:
            raise ValueError(
                "matryoshka.enabled=True requires a 'dimension' value."
            )
        return self


def validate_against_catalog(
    cfg: MatryoshkaConfig,
    model_name: str,
) -> None:
    """Raise ``ConfigError`` if ``cfg`` is not satisfiable for ``model_name``.

    Reads ``EMBEDDING_MODELS`` to find the model entry, then checks:

    1. The entry exists in the catalog.
    2. The entry declares a non-empty ``matryoshka_dimensions`` list.
    3. ``cfg.dimension`` is in that list.

    When ``cfg.enabled`` is ``False``, the function returns ``None``
    immediately — no catalog lookup is performed. This preserves backward
    compatibility for bots that do not opt in to truncation.

    Args:
        cfg: Parsed ``MatryoshkaConfig`` instance.
        model_name: Canonical model identifier (e.g.
            ``"nomic-ai/nomic-embed-text-v1.5"``).

    Returns:
        ``None`` on success.

    Raises:
        ConfigError: When Matryoshka is enabled but the model is not in the
            catalog, the model entry has no ``matryoshka_dimensions``, or
            ``cfg.dimension`` is not in the allowed list.
    """
    if not cfg.enabled:
        return None

    # Find the model entry in the catalog (list of plain dicts).
    entry = next(
        (m for m in EMBEDDING_MODELS if m.get("model") == model_name),
        None,
    )
    if entry is None:
        raise ConfigError(
            f"Model '{model_name}' is not in the embeddings catalog. "
            "Matryoshka truncation requires a catalog entry with "
            "'matryoshka_dimensions' declared."
        )

    allowed_dims = entry.get("matryoshka_dimensions")
    if not allowed_dims:
        raise ConfigError(
            f"Model '{model_name}' does not declare 'matryoshka_dimensions' "
            "in the embeddings catalog. Only models explicitly trained with "
            "Matryoshka Representation Learning support truncation."
        )

    if cfg.dimension not in allowed_dims:
        raise ConfigError(
            f"Requested matryoshka_dimensions={cfg.dimension} is not supported "
            f"for model '{model_name}'. Allowed dimensions: {allowed_dims}."
        )

    return None
