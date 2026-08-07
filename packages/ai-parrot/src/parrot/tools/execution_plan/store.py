"""``PlanFileStore`` — versioned ``plans_dir`` loader for ``plan_name`` mode.

A plan file is a git-diffable, versioned document (the daily Security
Advisory pipeline's use case). Per-run parameters use
``{params.<name>}`` placeholders substituted at **load time**, before
``ExecutionPlan.model_validate()`` — the frozen executor
(``PlanToolNode._resolve_args``) resolves exactly three runtime
placeholder families (``{nodes.<id>.output}``, ``{artifacts.<id>}``,
``{item}``/``{item.<field>}``/``{index}``) and must never be extended for
a fourth. See spec §3 Module 3.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml
from pydantic import ValidationError

from parrot.bots.flows.plan import ExecutionPlan

__all__ = ("PlanFileStore", "PlanLoadError")

# ``{params.<name>}`` — load-time-only placeholder, substituted here and
# never seen by the executor.
_PARAMS_RE = re.compile(r"\{params\.([A-Za-z_][A-Za-z0-9_]*)\}")

_EXTENSIONS = ("yaml", "yml", "json")


class PlanLoadError(ValueError):
    """Raised when a plan file cannot be resolved, parsed or parameterised."""


class PlanFileStore:
    """Resolves ``plans_dir/<name>.(yaml|yml|json)`` and applies ``params``.

    Attributes:
        plans_dir: Directory containing versioned plan files.
    """

    def __init__(self, plans_dir: Path) -> None:
        """Bind the store to ``plans_dir``.

        Args:
            plans_dir: Directory to resolve plan names against.

        Raises:
            PlanLoadError: If ``plans_dir`` does not exist or is not a
                directory.
        """
        self.plans_dir = Path(plans_dir)
        if not self.plans_dir.is_dir():
            raise PlanLoadError(
                f"plans_dir {self.plans_dir} does not exist or is not a directory"
            )

    def load(
        self, plan_name: str, params: Optional[Dict[str, Any]] = None
    ) -> ExecutionPlan:
        """Load, parameterise and validate a plan file.

        Args:
            plan_name: Base filename (without extension) under ``plans_dir``.
            params: Values for every ``{params.<name>}`` placeholder in the
                file. Every referenced name must be supplied and every
                supplied name must be referenced — nothing silent.

        Returns:
            The validated :class:`ExecutionPlan`.

        Raises:
            PlanLoadError: Unknown plan name, missing/unused params, or a
                validation failure after substitution.
        """
        path = self._resolve_path(plan_name)
        document = self._parse(path)

        supplied = dict(params or {})
        referenced: Set[str] = set()
        missing: Set[str] = set()

        substituted = self._substitute(document, supplied, referenced, missing)
        unused = set(supplied) - referenced

        if missing or unused:
            problems: List[str] = []
            if missing:
                problems.append(f"missing params: {sorted(missing)}")
            if unused:
                problems.append(f"unused params: {sorted(unused)}")
            raise PlanLoadError(
                f"Plan {plan_name!r} ({path}) parameter mismatch — "
                + "; ".join(problems)
            )

        try:
            return ExecutionPlan.model_validate(substituted)
        except ValidationError as exc:
            raise PlanLoadError(
                f"Plan {plan_name!r} ({path}) failed validation after "
                f"param substitution: {exc}"
            ) from exc

    # ── Path resolution ──────────────────────────────────────────────────

    def _resolve_path(self, plan_name: str) -> Path:
        """Resolve ``plan_name`` to a file, preferring yaml > yml > json."""
        for ext in _EXTENSIONS:
            candidate = self.plans_dir / f"{plan_name}.{ext}"
            if candidate.is_file():
                return candidate

        available = sorted(
            {
                p.stem
                for p in self.plans_dir.iterdir()
                if p.is_file() and p.suffix.lstrip(".") in _EXTENSIONS
            }
        )
        raise PlanLoadError(
            f"Unknown plan {plan_name!r} in {self.plans_dir}. "
            f"Available: {available}"
        )

    def _parse(self, path: Path) -> Any:
        """Parse a YAML or JSON plan document into a plain dict."""
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)

    # ── {params.<name>} substitution ──────────────────────────────────────

    def _substitute(
        self,
        value: Any,
        params: Dict[str, Any],
        referenced: Set[str],
        missing: Set[str],
    ) -> Any:
        """Walk ``value``, substituting every ``{params.<name>}`` string leaf.

        Mirrors the walking pattern in
        ``parrot.bots.flows.plan.models._iter_strings`` but rebuilds the
        structure instead of only yielding leaves. An exact-match
        placeholder (the whole string is one placeholder) resolves to the
        param's native value; an embedded one is interpolated as text —
        the same exact-match convention ``paths.render_key`` uses for
        runtime placeholders. Names referenced but missing from ``params``
        are recorded in ``missing`` rather than raising immediately, so
        every issue in the document is collected in one pass.

        Args:
            value: The (possibly nested) document node.
            params: Supplied parameter values.
            referenced: Accumulator for every ``{params.<name>}`` name seen.
            missing: Accumulator for referenced names absent from ``params``.

        Returns:
            The substituted structure (unchanged in shape otherwise).
        """
        if isinstance(value, dict):
            return {
                key: self._substitute(inner, params, referenced, missing)
                for key, inner in value.items()
            }
        if isinstance(value, list):
            return [
                self._substitute(inner, params, referenced, missing)
                for inner in value
            ]
        if not isinstance(value, str):
            return value

        exact = _PARAMS_RE.fullmatch(value)
        if exact:
            name = exact.group(1)
            referenced.add(name)
            if name not in params:
                missing.add(name)
                return value
            return params[name]

        def _sub(match: "re.Match") -> str:
            name = match.group(1)
            referenced.add(name)
            if name not in params:
                missing.add(name)
                return match.group(0)
            return str(params[name])

        return _PARAMS_RE.sub(_sub, value)
