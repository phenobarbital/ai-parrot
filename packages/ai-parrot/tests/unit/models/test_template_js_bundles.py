"""Unit tests for InfographicTemplate.js_bundles field (FEAT-197, TASK-1319)."""
from __future__ import annotations

import json
import sys
import pytest

# Force real modules (bypass conftest stubs).
for _mod in ("parrot.models.infographic", "parrot.models.infographic_templates"):
    sys.modules.pop(_mod, None)

import parrot.models.infographic as _real_infographic
import parrot.models.infographic_templates as _real_templates

sys.modules["parrot.models.infographic"] = _real_infographic
sys.modules["parrot.models.infographic_templates"] = _real_templates

from parrot.models.infographic import BlockType, JSBundle  # noqa: E402
from parrot.models.infographic_templates import (  # noqa: E402
    BlockSpec,
    InfographicTemplate,
    infographic_registry,
)


def test_template_js_bundles_default_none():
    """js_bundles should default to None when not provided."""
    t = InfographicTemplate(
        name="t_none",
        description="d",
        block_specs=[BlockSpec(block_type=BlockType.TITLE)],
    )
    assert t.js_bundles is None


def test_template_js_bundles_round_trip():
    """js_bundles should survive model_dump / model_validate round trip."""
    t = InfographicTemplate(
        name="t_cdn",
        description="d",
        block_specs=[BlockSpec(block_type=BlockType.CHART)],
        js_bundles=[
            JSBundle(
                name="echarts",
                scope="cdn",
                url="https://cdn/echarts.min.js",
                sri_hash="sha384-AAAA",
            )
        ],
    )
    restored = InfographicTemplate.model_validate(json.loads(t.model_dump_json()))
    assert restored.js_bundles is not None
    assert len(restored.js_bundles) == 1
    assert restored.js_bundles[0].name == "echarts"
    assert restored.js_bundles[0].scope == "cdn"


def test_builtin_templates_still_valid():
    """The seven original built-in templates must survive the new optional field."""
    # These are the seven templates registered by _register_builtins().
    # Check the actual registry — names may vary across versions.
    BUILTIN_NAMES = {"basic", "executive", "dashboard", "comparison",
                     "timeline", "minimal", "multi_tab"}
    names = infographic_registry.list_templates()
    found = {n for n in names if n in BUILTIN_NAMES}
    assert len(found) >= 7 or len(found) == len(BUILTIN_NAMES), (
        f"Expected built-in templates but found only: {found}"
    )
    for n in found:
        tpl = infographic_registry.get(n)
        # Original built-in templates ship without js_bundles
        assert tpl.js_bundles is None, (
            f"Built-in template '{n}' unexpectedly has js_bundles={tpl.js_bundles}"
        )


def test_template_with_inline_bundle():
    """Template with an inline JSBundle should validate."""
    t = InfographicTemplate(
        name="t_inline",
        description="d",
        block_specs=[BlockSpec(block_type=BlockType.TITLE)],
        js_bundles=[
            JSBundle(name="sparkline", scope="inline", inline="/* sparkline */")
        ],
    )
    assert t.js_bundles is not None
    assert t.js_bundles[0].scope == "inline"


def test_template_model_dump_includes_js_bundles():
    """model_dump() must include js_bundles key."""
    t = InfographicTemplate(
        name="t_dump",
        description="d",
        block_specs=[BlockSpec(block_type=BlockType.TITLE)],
    )
    data = t.model_dump()
    assert "js_bundles" in data
    assert data["js_bundles"] is None
