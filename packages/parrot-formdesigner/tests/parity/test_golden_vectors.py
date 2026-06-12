"""Parity test suite for FEAT-301 golden vectors.

Validates that the Python ``RuleEvaluator`` (the reference implementation) and
the HTML5 renderer's embedded ``data-logic-state`` block produce results
consistent with the statically declared golden vectors in
``tests/parity/vectors/*.json``.

Purpose
-------
These vectors are the **conformance contract** shared between this package and
all external consumers (JS SPA evaluator, native mobile evaluator, etc.).
Adding a new vector does *not* require touching this file — the runner
auto-discovers all ``*.json`` files in ``vectors/``.

Test categories (two assertions per vector)
-------------------------------------------
1. ``RuleEvaluator.evaluate_form()`` == ``vector["expected"]``
2. ``HTML5Renderer.render(..., evaluation_context=...)`` → embedded
   ``data-logic-state`` JSON == ``vector["expected"]``

Internal consistency check
---------------------------
Each vector must declare ``expected`` for every field that carries a
``depends_on`` rule.  Vectors missing an entry are flagged.

Usage
-----
Run from the repo root (worktree):
    source /path/to/.venv/bin/activate
    PYTHONPATH=$PWD/src python -m pytest tests/parity/ -v
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.services.rule_evaluator import (
    EvaluationContext,
    RuleEvaluator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VECTORS_DIR = Path(__file__).parent / "vectors"

_DATA_LOGIC_STATE_RE = re.compile(
    r'<script\s+type="application/json"\s+data-logic-state>(.*?)</script>',
    re.DOTALL,
)


def _load_vector(path: Path) -> dict[str, Any]:
    """Load a single golden vector JSON file.

    Args:
        path: Absolute path to the vector JSON file.

    Returns:
        Parsed vector dictionary.

    Raises:
        ValueError: If required top-level keys are missing.
    """
    data = json.loads(path.read_text())
    required = {"name", "form", "context", "expected"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Vector {path.name} missing keys: {missing}")
    return data


def _all_vectors() -> list[tuple[str, dict[str, Any]]]:
    """Discover and load all golden vectors.

    Returns:
        List of (vector_name, vector_dict) tuples sorted by file name.
    """
    vectors = []
    for path in sorted(VECTORS_DIR.glob("*.json")):
        v = _load_vector(path)
        vectors.append((v["name"], v))
    return vectors


def _parse_form(raw: dict[str, Any]) -> FormSchema:
    """Parse a raw form dict into FormSchema.

    Args:
        raw: Form dict from vector.

    Returns:
        Parsed FormSchema instance.
    """
    return FormSchema.model_validate(raw)


def _parse_context(raw: dict[str, Any]) -> EvaluationContext:
    """Parse a raw context dict into EvaluationContext.

    Args:
        raw: Context dict from vector.

    Returns:
        Parsed EvaluationContext instance.
    """
    return EvaluationContext(
        answers=raw.get("answers", {}),
        location_vars=raw.get("location_vars", {}),
        visit_context=raw.get("visit_context", {}),
    )


def _extract_logic_state_from_html(html: str) -> dict[str, Any]:
    """Extract and parse the ``data-logic-state`` JSON block from HTML.

    Args:
        html: Rendered HTML5 string.

    Returns:
        Parsed logic state dict.

    Raises:
        AssertionError: If the block is missing or not valid JSON.
    """
    match = _DATA_LOGIC_STATE_RE.search(html)
    assert match is not None, "data-logic-state block not found in HTML output"
    raw_json = match.group(1)
    return json.loads(raw_json)


def _fields_with_rules(form: FormSchema) -> set[str]:
    """Return field_ids that carry a DependencyRule.

    Args:
        form: The form schema.

    Returns:
        Set of field_ids with depends_on rules.
    """
    return {f.field_id for f in form.iter_all_fields() if f.depends_on is not None}


# ---------------------------------------------------------------------------
# Parametrized fixtures
# ---------------------------------------------------------------------------

ALL_VECTORS = _all_vectors()


@pytest.mark.parametrize("name,vector", ALL_VECTORS, ids=[v[0] for v in ALL_VECTORS])
class TestGoldenVectors:
    """Parametrized golden vector conformance suite.

    Each test class instance receives one vector. Two assertions:
    1.  ``RuleEvaluator.evaluate_form()`` must match ``expected``.
    2.  ``HTML5Renderer.render(..., evaluation_context=...)`` must embed
        a ``data-logic-state`` block that matches ``expected``.
    """

    def test_rule_evaluator_matches_expected(
        self, name: str, vector: dict[str, Any]
    ) -> None:
        """Assert RuleEvaluator.evaluate_form() result equals expected.

        Args:
            name: Vector name (unused, present for pytest id readability).
            vector: Full vector dict.
        """
        form = _parse_form(vector["form"])
        ctx = _parse_context(vector["context"])
        expected: dict[str, dict[str, Any]] = vector["expected"]

        evaluator = RuleEvaluator()
        results = evaluator.evaluate_form(form, ctx)

        for field_id, exp_entry in expected.items():
            assert field_id in results, (
                f"Vector '{name}': field '{field_id}' not in evaluator results. "
                f"Got: {list(results.keys())}"
            )
            result = results[field_id]
            assert result.effect == exp_entry["effect"], (
                f"Vector '{name}' field '{field_id}': "
                f"expected effect={exp_entry['effect']!r}, got {result.effect!r}"
            )
            assert result.matched == exp_entry["matched"], (
                f"Vector '{name}' field '{field_id}': "
                f"expected matched={exp_entry['matched']}, got {result.matched}"
            )

    def test_internal_consistency(
        self, name: str, vector: dict[str, Any]
    ) -> None:
        """Assert expected covers every field that has a depends_on rule.

        Args:
            name: Vector name.
            vector: Full vector dict.
        """
        form = _parse_form(vector["form"])
        expected: dict[str, dict[str, Any]] = vector["expected"]
        rule_fields = _fields_with_rules(form)

        for field_id in rule_fields:
            assert field_id in expected, (
                f"Vector '{name}': field '{field_id}' has a depends_on rule "
                f"but is not declared in 'expected'."
            )

    async def test_html5_embed_matches_expected(
        self, name: str, vector: dict[str, Any]
    ) -> None:
        """Assert HTML5 pre-resolve embed matches expected.

        Args:
            name: Vector name.
            vector: Full vector dict.
        """
        form = _parse_form(vector["form"])
        ctx = _parse_context(vector["context"])
        expected: dict[str, dict[str, Any]] = vector["expected"]

        renderer = HTML5Renderer()
        rendered = await renderer.render(form, evaluation_context=ctx)
        logic_state = _extract_logic_state_from_html(rendered.content)

        for field_id, exp_entry in expected.items():
            assert field_id in logic_state, (
                f"Vector '{name}': field '{field_id}' not in HTML logic_state. "
                f"Got: {list(logic_state.keys())}"
            )
            state_entry = logic_state[field_id]
            assert state_entry["effect"] == exp_entry["effect"], (
                f"Vector '{name}' field '{field_id}' HTML embed: "
                f"expected effect={exp_entry['effect']!r}, got {state_entry['effect']!r}"
            )
            assert state_entry["matched"] == exp_entry["matched"], (
                f"Vector '{name}' field '{field_id}' HTML embed: "
                f"expected matched={exp_entry['matched']}, got {state_entry['matched']}"
            )
