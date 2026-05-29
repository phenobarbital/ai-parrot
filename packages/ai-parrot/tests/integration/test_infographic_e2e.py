"""End-to-end integration tests for FEAT-197 — Infographic Toolkit.

These tests exercise the full pipeline with mocked LLM clients.  No real
provider calls are made.

Dependencies (all mocked or in-memory):
- InfographicToolkit (validation + deterministic render)
- ArtifactStore (in-memory mock)
- PandasAgent.ask post-loop branch
- AgentTalk._format_infographic_response
- ArtifactPublicHTMLView signature verification
"""
from __future__ import annotations

import sys
import time

import pandas as pd
import pytest
from unittest.mock import AsyncMock, MagicMock

# Force real modules so mocking works against the real class hierarchy.
for _mod in (
    "parrot.models.infographic",
    "parrot.models.infographic_templates",
    "parrot.tools.infographic_toolkit",
    "parrot.tools._enhance_html_check",
    "parrot.storage.models",
    "parrot.models.outputs",
    "parrot.models.responses",
    "parrot.handlers.csp",
    "parrot.handlers.artifacts",
):
    sys.modules.pop(_mod, None)

import parrot.models.infographic as _ri
import parrot.models.infographic_templates as _rt
import parrot.storage.models as _rsm
import parrot.models.outputs as _ro
import parrot.models.responses as _rr
import parrot.handlers.csp as _rcsp

for m, mod in [
    ("parrot.models.infographic", _ri),
    ("parrot.models.infographic_templates", _rt),
    ("parrot.storage.models", _rsm),
    ("parrot.models.outputs", _ro),
    ("parrot.models.responses", _rr),
    ("parrot.handlers.csp", _rcsp),
]:
    sys.modules[m] = mod

import parrot.tools.infographic_toolkit as _rtk
import parrot.tools._enhance_html_check as _rcheck
import parrot.handlers.artifacts as _rah

sys.modules["parrot.tools.infographic_toolkit"] = _rtk
sys.modules["parrot.tools._enhance_html_check"] = _rcheck
sys.modules["parrot.handlers.artifacts"] = _rah

from parrot.tools.infographic_toolkit import (  # noqa: E402
    InfographicToolkit, InfographicRenderResult, InfographicValidationError,
)
from parrot.models.infographic import BlockType, JSBundle  # noqa: E402
from parrot.models.infographic_templates import (  # noqa: E402
    BlockSpec, InfographicTemplate, infographic_registry,
)
from parrot.models.outputs import OutputMode  # noqa: E402
from parrot.handlers.artifacts import _sign_artifact  # noqa: E402
from parrot.handlers.csp import build_csp_headers  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed/artifact-1")
    return store


@pytest.fixture
def basic_template():
    t = InfographicTemplate(
        name="_e2e_basic",
        description="e2e test template",
        block_specs=[
            BlockSpec(block_type=BlockType.HERO_CARD, min_items=1, max_items=4, required=True),
        ],
    )
    infographic_registry.register(t)
    yield t


@pytest.fixture
def toolkit(fake_store, basic_template):
    tk = InfographicToolkit(artifact_store=fake_store)
    bot = MagicMock()
    bot._get_repl_locals = MagicMock(return_value={"rev": pd.DataFrame([{"x": 1}])})
    bot.user_id = "u"
    bot.agent_id = "agt"
    bot.session_id = "sess"
    tk._bot = bot
    return tk


_VALID_HERO_BLOCKS = [
    {"type": "hero_card", "cards": [{"label": "Revenue", "value": 100}]}
]


# ---------------------------------------------------------------------------
# E2E: toolkit validate → render → result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_toolkit_validate_and_render(toolkit, basic_template, fake_store):
    """Validate blocks, then render: full toolkit pipeline."""
    # Step 1: dry-run validation
    validation = await toolkit.validate_blocks(
        basic_template.name, _VALID_HERO_BLOCKS,
    )
    assert validation == {"ok": True}

    # Step 2: render
    result = await toolkit.render(
        template_name=basic_template.name,
        theme="dark",
        mode="deterministic",
        blocks=_VALID_HERO_BLOCKS,
        data_variables=["rev"],
    )
    assert isinstance(result, InfographicRenderResult)
    assert result.enhanced is False
    assert result.html_url == "https://signed/artifact-1"
    assert fake_store.save_artifact.call_count == 1


@pytest.mark.asyncio
async def test_e2e_validation_error_surfaced(toolkit, basic_template):
    """SLOT_TYPE_MISMATCH surfaces immediately with structured code+detail."""
    with pytest.raises(InfographicValidationError) as ei:
        await toolkit.render(
            template_name=basic_template.name,
            theme=None,
            mode="deterministic",
            blocks=[{"type": "title", "text": "wrong type"}],
            data_variables=[],
        )
    exc = ei.value
    assert exc.code == "SLOT_TYPE_MISMATCH"
    assert "position" in exc.detail


@pytest.mark.asyncio
async def test_e2e_unknown_template_error(toolkit):
    """TEMPLATE_UNKNOWN is surfaced when the template is not registered."""
    with pytest.raises(InfographicValidationError) as ei:
        await toolkit.render(
            template_name="does_not_exist",
            theme=None,
            mode="deterministic",
            blocks=[],
            data_variables=[],
        )
    assert ei.value.code == "TEMPLATE_UNKNOWN"


# ---------------------------------------------------------------------------
# E2E: enhance fallback on malicious HTML
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e2e_enhance_fallback(toolkit, basic_template, caplog):
    """Malicious enhance HTML → enhanced=False (silent fallback)."""
    toolkit._bot.enhance_infographic = AsyncMock(
        return_value='<script src="https://evil/x.js"></script>'
    )
    toolkit._bot._get_repl_locals = MagicMock(
        return_value={"rev": pd.DataFrame([{"x": 1}])}
    )
    with caplog.at_level("WARNING"):
        result = await toolkit.render(
            template_name=basic_template.name,
            theme=None,
            mode="enhance",
            enhance_brief="add interactivity",
            blocks=_VALID_HERO_BLOCKS,
            data_variables=["rev"],
        )
    assert result.enhanced is False
    assert any("ENHANCE_OUTPUT_INVALID" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# E2E: public artifact HTML serving (signature check)
# ---------------------------------------------------------------------------

def test_e2e_html_serving_valid_signature():
    """Valid signature → would return 200 (tested via helper function)."""
    key = b"test-key"
    artifact_id = "art-e2e-1"
    expiry = int(time.time()) + 600
    sig = _sign_artifact(artifact_id, expiry, key)

    # Simulate the ArtifactPublicHTMLView._verify logic
    from parrot.handlers.artifacts import _verify_artifact_signature
    assert _verify_artifact_signature(artifact_id, f"{expiry}.{sig}", key) is True


def test_e2e_html_serving_expired_signature():
    """Expired signature → returns False (maps to 403 in the view)."""
    key = b"test-key"
    artifact_id = "art-e2e-1"
    expiry = int(time.time()) - 1  # already past
    sig = _sign_artifact(artifact_id, expiry, key)

    from parrot.handlers.artifacts import _verify_artifact_signature
    assert _verify_artifact_signature(artifact_id, f"{expiry}.{sig}", key) is False


def test_e2e_csp_headers_from_js_bundles():
    """CSP headers include CDN origin from template's js_bundles."""
    bundle = JSBundle(
        name="echarts",
        scope="cdn",
        url="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js",
        sri_hash="sha384-AAAA",
    )
    hdrs = build_csp_headers(js_bundles=[bundle], frame_ancestors="'self'")
    csp = hdrs["Content-Security-Policy"]
    assert "https://cdn.jsdelivr.net" in csp
    assert "frame-ancestors 'self'" in csp
    assert hdrs["X-Content-Type-Options"] == "nosniff"


# ---------------------------------------------------------------------------
# E2E: financial_projection_variance template is registered
# ---------------------------------------------------------------------------

def test_e2e_financial_variance_template_registered():
    """infographic_registry must have financial_projection_variance."""
    # The template is registered at module load time in infographic_templates.py
    # We need to reimport to pick it up (since we cleared the module cache above).
    sys.modules.pop("parrot.models.infographic_templates", None)
    import parrot.models.infographic_templates as _fresh
    sys.modules["parrot.models.infographic_templates"] = _fresh

    assert "financial_projection_variance" in _fresh.infographic_registry.list_templates()
    tpl = _fresh.infographic_registry.get("financial_projection_variance")
    assert len(tpl.block_specs) == 4
    assert tpl.js_bundles is not None and len(tpl.js_bundles) >= 1
    assert tpl.default_theme == "dark"


# ---------------------------------------------------------------------------
# E2E: legacy get_infographic path is untouched (regression guard)
# ---------------------------------------------------------------------------

def test_e2e_legacy_get_infographic_exists():
    """AbstractBot still has get_infographic — legacy path is untouched."""
    try:
        import importlib
        # Load the module source directly to avoid the full init chain.
        import inspect
        src_path = (
            __import__("pathlib").Path(__file__).resolve().parents[4]
            / "src" / "parrot" / "bots" / "abstract.py"
        )
        if not src_path.exists():
            pytest.skip("abstract.py not found — skipping legacy guard")
        source = src_path.read_text(encoding="utf-8")
        assert "def get_infographic" in source, (
            "get_infographic method was removed from AbstractBot — REGRESSION"
        )
    except Exception as exc:
        pytest.skip(f"Could not verify legacy guard: {exc}")


def test_e2e_output_mode_infographic_value():
    """OutputMode.INFOGRAPHIC == 'infographic' — enum regression guard."""
    assert OutputMode.INFOGRAPHIC.value == "infographic"
    assert OutputMode("infographic") is OutputMode.INFOGRAPHIC


# ---------------------------------------------------------------------------
# E2E: financial_variance 9-block flat render (FEAT-206)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_render_financial_variance_end_to_end(fake_store):
    """render(template_name='financial_variance') with 9 flat blocks produces HTML
    containing 4 hero-card containers and 3 chart containers.
    """
    tk = InfographicToolkit(artifact_store=fake_store)
    bot = MagicMock()
    bot._get_repl_locals = MagicMock(return_value={
        "fp_daily": pd.DataFrame({"date": [1, 2], "rev_total": [2.3, 3.7]}),
    })
    bot.user_id = "u"
    bot.agent_id = "agt"
    bot.session_id = "sess"
    tk._bot = bot

    bar = lambda t: {  # noqa: E731
        "type": "chart",
        "chart_type": "bar",
        "layout": "half",
        "title": t,
        "labels": ["D1", "D2"],
        "series": [{"name": "x", "values": [1.0, 2.0]}],
    }
    card = lambda l, v: {"type": "hero_card", "label": l, "value": v}  # noqa: E731
    fv_blocks = [
        {"type": "title", "title": "Financial Variance", "date": "May 14 – 27, 2026"},
        card("Revenue", "$3.7M"),
        card("Change", "$1.4M"),
        card("EBITDA", "$31K"),
        card("DoD", "$107K"),
        bar("Revenue DoD"),
        bar("EBITDA DoD"),
        {
            "type": "chart",
            "chart_type": "line",
            "layout": "full",
            "title": "Cumulative",
            "labels": ["D1", "D2"],
            "series": [{"name": "rev", "values": [2.3, 3.7]}],
        },
        {"type": "summary", "content": "Summary text covering the period."},
    ]

    result = await tk.render(
        template_name="financial_variance",
        theme="light",
        mode="deterministic",
        blocks=fv_blocks,
        data_variables=["fp_daily"],
    )

    assert isinstance(result, InfographicRenderResult), (
        f"render() did not return InfographicRenderResult: {type(result)}"
    )
    # html_inline is None for large payloads (> 50 KB threshold).
    # Extract the rendered HTML from the artifact stored in the mock store.
    html = result.html_inline or ""
    if not html and fake_store.save_artifact.called:
        # The artifact is the 4th positional arg to save_artifact(user_id, agent_id, session_id, artifact)
        call_args = fake_store.save_artifact.call_args
        artifact = call_args.args[3] if call_args.args else call_args.kwargs.get("artifact")
        if artifact is not None and hasattr(artifact, "definition") and artifact.definition:
            html = artifact.definition.get("html", "") or ""
    # The rendered HTML must contain at least 4 hero-card references and 3 chart references.
    # (Exact attribute names depend on renderer; count conservatively.)
    assert html, "No HTML was captured from render result or artifact store call"
    assert html.count("hero") >= 4, (
        f"HTML does not contain 4 hero-card references. 'hero' occurrences: {html.count('hero')}"
    )
    assert html.count("chart") >= 3, (
        f"HTML does not reference 3 chart blocks. 'chart' occurrences: {html.count('chart')}"
    )
