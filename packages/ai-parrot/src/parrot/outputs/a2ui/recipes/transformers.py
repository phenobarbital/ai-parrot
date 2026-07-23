"""Transformer registry + fail-fast validation gate (Module 2, FEAT-324).

Recipes reference transformations by registered name — never stored/executed
code (spec G1). ``@infographic_transformer`` registers pure functions
``(inputs, params) -> dict`` by decorator side effect at import time,
mirroring :func:`parrot.outputs.a2ui.catalog.register_component`. The
:func:`validate_inputs` gate checks a transform step's declared
``requires_columns`` against real DataFrames BEFORE anything executes
(spec G4), producing a list of :class:`~parrot.outputs.a2ui.recipes.models.RecipeRunError`
diagnostics.

Core-side, dependency-free (spec G8): pandas is allowed here (it is not on
the G8 forbidden-import list — only DatasetManager/agents/LLM clients are).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from parrot.outputs.a2ui.recipes.models import (
    RecipeRunError,
    TransformerManifest,
    TransformStep,
)

__all__ = [
    "RegisteredTransformer",
    "TransformerRegistry",
    "infographic_transformer",
    "transformer_registry",
    "validate_inputs",
]

logger = logging.getLogger(__name__)

TransformerFunc = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class RegisteredTransformer:
    """A registered transformer: its callable plus its discoverable manifest.

    Attributes:
        func: The pure function ``(inputs, params) -> dict`` implementing the
            transform.
        manifest: The :class:`TransformerManifest` describing this transformer
            for the fail-fast gate and for LLM discovery.
    """

    func: TransformerFunc
    manifest: TransformerManifest = field(compare=False)

    def __call__(self, inputs: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        return self.func(inputs, params)


class TransformerRegistry:
    """Module-level registry of registered transformers.

    Registration is by decorator side effect (import time) — there is no
    dynamic import of user-supplied dotted paths, which would reopen the G1
    "stored code" hole. Re-registering the SAME function under the same name
    is a no-op (idempotent under pytest re-imports); registering a DIFFERENT
    function under an already-used name raises.
    """

    def __init__(self) -> None:
        self._transformers: dict[str, RegisteredTransformer] = {}

    def register(
        self,
        name: str,
        func: TransformerFunc,
        *,
        requires_columns: dict[str, list[str]] | None = None,
        description: str = "",
        params_schema: dict[str, Any] | None = None,
    ) -> RegisteredTransformer:
        """Register ``func`` under ``name``.

        Args:
            name: Registered transformer name, referenced by
                ``TransformStep.transformer``.
            func: The pure function ``(inputs, params) -> dict``.
            requires_columns: Required input columns keyed by input alias.
            description: Human-readable description (LLM discovery).
            params_schema: JSON schema of accepted params.

        Returns:
            The stored :class:`RegisteredTransformer`.

        Raises:
            ValueError: If ``name`` is already registered to a DIFFERENT
                function.
        """
        existing = self._transformers.get(name)
        if existing is not None and existing.func is not func:
            raise ValueError(
                f"Transformer {name!r} is already registered to a different "
                f"function ({existing.func!r} != {func!r})"
            )
        manifest = TransformerManifest(
            name=name,
            description=description,
            requires_columns=requires_columns or {},
            params_schema=params_schema or {},
        )
        registered = RegisteredTransformer(func=func, manifest=manifest)
        self._transformers[name] = registered
        logger.debug("Registered infographic transformer %r", name)
        return registered

    def get(self, name: str) -> RegisteredTransformer:
        """Look up a registered transformer by name.

        Args:
            name: Registered transformer name.

        Returns:
            The :class:`RegisteredTransformer`.

        Raises:
            KeyError: If ``name`` is not registered; lists available names.
        """
        try:
            return self._transformers[name]
        except KeyError as exc:
            available = sorted(self._transformers)
            raise KeyError(
                f"Unknown transformer {name!r}; registered transformers: {available!r}"
            ) from exc

    def manifest(self, name: str) -> TransformerManifest:
        """Return the :class:`TransformerManifest` for a registered transformer.

        Args:
            name: Registered transformer name.

        Returns:
            The transformer's manifest.

        Raises:
            KeyError: If ``name`` is not registered.
        """
        return self.get(name).manifest

    def list(self) -> list[TransformerManifest]:
        """List manifests for all registered transformers.

        Returns:
            One :class:`TransformerManifest` per registered transformer.
        """
        return [entry.manifest for entry in self._transformers.values()]


#: Process-wide transformer registry (module import side effect populates this).
transformer_registry = TransformerRegistry()


def infographic_transformer(
    name: str,
    *,
    requires_columns: dict[str, list[str]] | None = None,
    description: str = "",
    params_schema: dict[str, Any] | None = None,
) -> Callable[[TransformerFunc], TransformerFunc]:
    """Decorator registering a pure transform function under ``name``.

    Args:
        name: Registered transformer name, referenced by
            ``TransformStep.transformer``.
        requires_columns: Required input columns keyed by input alias (the
            alias names in ``TransformStep.inputs``, NOT dataset names).
        description: Human-readable description (LLM discovery).
        params_schema: JSON schema of accepted params.

    Returns:
        The decorator, which registers and returns the function unchanged.
    """

    def decorator(func: TransformerFunc) -> TransformerFunc:
        transformer_registry.register(
            name,
            func,
            requires_columns=requires_columns,
            description=description,
            params_schema=params_schema,
        )
        return func

    return decorator


def validate_inputs(
    step: TransformStep,
    frames: dict[str, pd.DataFrame],
    *,
    recipe_name: str = "",
) -> list[RecipeRunError]:
    """Validate a transform step's inputs against its registered requirements.

    Checks BEFORE the transform runs (spec G4 fail-fast): every input alias
    the step references must be present in ``frames``, non-empty, and carry
    every column the transformer declares as required for that alias. All
    problems are collected (not just the first) so a ``dry_run`` can report
    everything at once.

    Args:
        step: The :class:`TransformStep` about to be executed.
        frames: Available DataFrames keyed by input alias.
        recipe_name: Owning recipe name, echoed into each diagnostic.

    Returns:
        A list of :class:`RecipeRunError` (empty if the gate passes).
    """
    errors: list[RecipeRunError] = []

    try:
        registered = transformer_registry.get(step.transformer)
    except KeyError as exc:
        errors.append(
            RecipeRunError(
                recipe=recipe_name,
                stage="gate",
                transformer=step.transformer,
                detail=str(exc),
            )
        )
        return errors

    requires_columns = registered.manifest.requires_columns

    for alias in step.inputs:
        frame = frames.get(alias)
        if frame is None:
            errors.append(
                RecipeRunError(
                    recipe=recipe_name,
                    stage="gate",
                    transformer=step.transformer,
                    dataset=alias,
                    detail=f"Input alias {alias!r} not found among available frames.",
                )
            )
            continue

        if frame.empty:
            errors.append(
                RecipeRunError(
                    recipe=recipe_name,
                    stage="gate",
                    transformer=step.transformer,
                    dataset=alias,
                    detail=f"Input {alias!r} is an empty DataFrame.",
                )
            )

        required = requires_columns.get(alias, [])
        missing = [col for col in required if col not in frame.columns]
        if missing:
            errors.append(
                RecipeRunError(
                    recipe=recipe_name,
                    stage="gate",
                    transformer=step.transformer,
                    dataset=alias,
                    missing_columns=missing,
                    detail=(
                        f"Input {alias!r} is missing required column(s) "
                        f"{missing!r} for transformer {step.transformer!r}."
                    ),
                )
            )

    return errors
