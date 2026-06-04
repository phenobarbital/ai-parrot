"""TemplatePlan & ParamSpec — parameterized scraping plan templates.

A :class:`TemplatePlan` is a reusable, parameterized template that produces a
concrete :class:`ScrapingPlan` via :meth:`TemplatePlan.bind`.  Parameters are
declared with typed :class:`ParamSpec` entries; ``{{param}}`` placeholders in
the URL, objective, and step templates are rendered at bind time (FEAT-222,
Module 1).

Placeholder convention:
    - ``{{param}}`` (double braces) — rendered by ``bind()``.
    - ``{index}`` / ``{i}`` (single braces) — Loop's convention; passed
      through unchanged so the two layers never collide.

Rendering uses ``re.sub`` rather than ``str.format()`` so unrelated braces
(CSS selectors, JSON) never raise ``KeyError``.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, computed_field, model_validator

from .plan import ScrapingPlan, _compute_fingerprint

# Matches a double-brace placeholder containing a single identifier.
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


class ParamSpec(BaseModel):
    """Typed parameter definition for a :class:`TemplatePlan`.

    Attributes:
        name: Parameter name, referenced as ``{{name}}`` in templates.
        type: One of ``string``, ``int``, ``date``, ``enum``, ``url``.
        required: Whether the parameter must be supplied to ``bind()``.
        default: Default value used when the parameter is omitted.
        choices: Allowed values (required when ``type == "enum"``).
        description: Human-readable description.
    """

    name: str
    type: Literal["string", "int", "date", "enum", "url"] = "string"
    required: bool = True
    default: Optional[Any] = None
    choices: Optional[List[Any]] = None
    description: str = ""

    @model_validator(mode="after")
    def _validate_enum_choices(self) -> "ParamSpec":
        """An ``enum`` parameter must declare a non-empty ``choices`` list."""
        if self.type == "enum" and not self.choices:
            raise ValueError(
                f"ParamSpec '{self.name}' has type 'enum' but no 'choices' provided"
            )
        return self


class TemplatePlan(BaseModel):
    """Parameterized plan template that produces ``ScrapingPlan``s via ``bind()``.

    Attributes:
        name: Template name (also used for the produced plan's fingerprint).
        objective_template: Objective string with ``{{param}}`` placeholders.
        url_template: Target URL with ``{{param}}`` placeholders.
        params: Declared parameters.
        steps_template: Step dicts; string values are rendered recursively.
        selectors: Optional selector dicts (rendered recursively).
        tags: Tags carried into the produced plan.
        browser_config: Optional browser configuration carried into the plan.
        version: Template version.
        source: Provenance marker (``"llm"`` by default).
        created_at: Creation timestamp.
    """

    name: str
    objective_template: str
    url_template: str
    params: List[ParamSpec] = Field(default_factory=list)
    steps_template: List[Dict[str, Any]] = Field(default_factory=list)
    selectors: Optional[List[Dict[str, Any]]] = None
    tags: List[str] = Field(default_factory=list)
    browser_config: Optional[Dict[str, Any]] = None
    version: str = "1.0"
    source: str = "llm"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @computed_field
    @property
    def fingerprint(self) -> str:
        """Template-level fingerprint derived from the template name."""
        return _compute_fingerprint(f"template::{self.name}")

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _render_str(text: str, values: Dict[str, Any]) -> str:
        """Render ``{{param}}`` placeholders in *text* using *values*.

        Unknown placeholders are left untouched; single-brace tokens
        (``{i}``) never match and pass through unchanged.
        """
        def _repl(match: "re.Match[str]") -> str:
            key = match.group(1)
            if key in values:
                return str(values[key])
            return match.group(0)

        return _PLACEHOLDER_RE.sub(_repl, text)

    @classmethod
    def _render(cls, value: Any, values: Dict[str, Any]) -> Any:
        """Recursively render placeholders in strings, dicts, and lists."""
        if isinstance(value, str):
            return cls._render_str(value, values)
        if isinstance(value, dict):
            return {k: cls._render(v, values) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._render(item, values) for item in value]
        return value

    def _resolve_params(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Validate *kwargs* against the declared params and return values.

        Raises:
            ValueError: For missing required params, type mismatches, or
                enum/choice violations.
        """
        resolved: Dict[str, Any] = {}
        for spec in self.params:
            if spec.name in kwargs:
                value = kwargs[spec.name]
            elif spec.required:
                raise ValueError(
                    f"Missing required parameter: '{spec.name}'"
                )
            else:
                value = spec.default

            if value is not None:
                self._validate_type(spec, value)

            resolved[spec.name] = value
        return resolved

    @staticmethod
    def _validate_type(spec: ParamSpec, value: Any) -> None:
        """Validate *value* against *spec*'s declared type / choices."""
        if spec.type == "string":
            if not isinstance(value, str):
                raise ValueError(
                    f"Parameter '{spec.name}' expects a string, got "
                    f"{type(value).__name__}"
                )
        elif spec.type == "int":
            # bool is a subclass of int — reject it explicitly.
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(
                    f"Parameter '{spec.name}' expects an int, got "
                    f"{type(value).__name__}"
                )
        elif spec.type == "date":
            try:
                datetime.fromisoformat(str(value))
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"Parameter '{spec.name}' expects an ISO date string, "
                    f"got {value!r}"
                ) from exc
        elif spec.type == "url":
            if not (isinstance(value, str) and value.startswith(("http://", "https://"))):
                raise ValueError(
                    f"Parameter '{spec.name}' expects an http(s) URL, got {value!r}"
                )
        elif spec.type == "enum":
            if spec.choices is None or value not in spec.choices:
                raise ValueError(
                    f"Parameter '{spec.name}' must be one of {spec.choices}, "
                    f"got {value!r}"
                )

    def _param_fingerprint(self, resolved: Dict[str, Any]) -> str:
        """Compute ``hash(template_name + sorted(params))`` for the plan."""
        param_items = sorted((k, str(v)) for k, v in resolved.items())
        param_str = self.name + "::" + "&".join(
            f"{k}={v}" for k, v in param_items
        )
        return _compute_fingerprint(param_str)

    # ── Public API ────────────────────────────────────────────────────

    def bind(self, **kwargs: Any) -> ScrapingPlan:
        """Bind parameters and produce a concrete :class:`ScrapingPlan`.

        Validates *kwargs* against the declared :class:`ParamSpec` list, fills
        defaults for omitted optional params, renders ``{{param}}``
        placeholders in the URL, objective, steps, and selectors, and returns
        a ``ScrapingPlan`` whose fingerprint is derived from
        ``template_name + sorted(params)`` (so different parameter sets never
        collide on the same URL fingerprint).

        The rendered URL is also exposed as the implicit ``{{url}}``
        placeholder available inside ``steps_template`` / ``selectors``.

        Args:
            **kwargs: Parameter values keyed by ``ParamSpec.name``.

        Returns:
            A concrete ``ScrapingPlan``.

        Raises:
            ValueError: For missing required params, type mismatches, or
                enum/choice violations.
        """
        resolved = self._resolve_params(kwargs)

        # Fingerprint is computed from the declared params only (not the
        # implicit url) so it is stable and collision-free per parameter set.
        fingerprint = self._param_fingerprint(resolved)

        rendered_url = self._render_str(self.url_template, resolved)
        rendered_objective = self._render_str(self.objective_template, resolved)

        # Expose the rendered URL as the implicit {{url}} placeholder for steps.
        render_values = dict(resolved)
        render_values["url"] = rendered_url

        rendered_steps = self._render(self.steps_template, render_values)
        rendered_selectors = (
            self._render(self.selectors, render_values)
            if self.selectors is not None else None
        )

        return ScrapingPlan(
            name=self.name,
            version=self.version,
            tags=list(self.tags),
            url=rendered_url,
            objective=rendered_objective,
            steps=rendered_steps,
            selectors=rendered_selectors,
            browser_config=self.browser_config,
            source=self.source,
            fingerprint=fingerprint,
        )
