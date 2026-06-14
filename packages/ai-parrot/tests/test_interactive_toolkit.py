"""Unit tests for InteractiveToolkit (render pipeline + security fallback)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.tools.interactive_toolkit import (
    InteractiveToolkit,
    InteractiveValidationError,
)
from parrot.models.interactive import InteractiveRenderResult
from parrot.storage.artifact_signing import get_signing_key, verify_signature


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    return store


def _bot(enhance_return=None):
    bot = SimpleNamespace(
        user_id="u", agent_id="agt", session_id="sess",
        _current_user_id=None, _current_agent_id=None, _current_session_id=None,
    )
    if enhance_return is not None:
        bot.enhance_interactive = AsyncMock(return_value=enhance_return)
    return bot


@pytest.fixture
def toolkit(fake_store):
    tk = InteractiveToolkit(artifact_store=fake_store)
    tk._bot = _bot()
    return tk


# ---------------------------------------------------------------------------
# Discovery tools
# ---------------------------------------------------------------------------

async def test_list_templates_and_libraries(toolkit):
    templates = await toolkit.list_templates()
    names = {t["name"] for t in templates}
    assert {"dashboard", "wizard", "diagram", "grid", "report"} <= names

    libs = await toolkit.list_libraries()
    lib_names = {l["name"] for l in libs}
    assert {"echarts", "mermaid", "gridjs", "stepper"} <= lib_names


async def test_get_scaffold_returns_skeleton_and_allowed_libraries(toolkit):
    scaffold = await toolkit.get_scaffold("dashboard")
    assert "<!--HEAD-->" in scaffold["html_skeleton"]
    assert "kpis" in scaffold["slots"]
    allowed = {lib["name"] for lib in scaffold["allowed_libraries"]}
    assert allowed == {"echarts", "gridjs"}


async def test_get_scaffold_unknown_template_raises(toolkit):
    with pytest.raises(InteractiveValidationError) as ei:
        await toolkit.get_scaffold("nope")
    assert ei.value.code == "TEMPLATE_UNKNOWN"


# ---------------------------------------------------------------------------
# Deterministic render
# ---------------------------------------------------------------------------

async def test_deterministic_render_strips_slots_and_persists(toolkit, fake_store):
    result = await toolkit.render(
        template_name="dashboard", brief="metrics", mode="deterministic",
    )
    assert isinstance(result, InteractiveRenderResult)
    assert result.enhanced is False
    assert result.libraries_used == ["echarts", "gridjs"]
    # Persisted once with a definition carrying html + js_bundles.
    assert fake_store.save_artifact.call_count == 1
    artifact = fake_store.save_artifact.call_args[0][-1]
    html = artifact.definition["html"]
    assert "<!-- SLOT:" not in html          # all slot markers stripped
    assert "<!--HEAD-->" not in html         # head marker replaced
    assert "echarts.min.js" in html          # allowed bundle injected with integrity
    assert artifact.definition["js_bundles"]
    # Signed public URL targets the generic public HTML route.
    assert result.html_url.startswith("/api/v1/artifacts/public/")
    assert f"/{result.artifact_id}.html" in result.html_url


async def test_render_signed_url_roundtrips(toolkit):
    result = await toolkit.render(
        template_name="grid", brief="table", mode="deterministic",
    )
    segment = result.html_url.split("/api/v1/artifacts/public/")[1].split("/")[0]
    assert verify_signature(result.artifact_id, segment, get_signing_key()) is True


# ---------------------------------------------------------------------------
# Enhance pass
# ---------------------------------------------------------------------------

async def test_enhance_success_marks_enhanced(fake_store):
    # A valid enhanced doc: inline script only (no disallowed external resources).
    good_html = (
        "<!DOCTYPE html><html><head></head><body>"
        "<div id='chart'></div><script>/* inline ok */</script>"
        "</body></html>"
    )
    tk = InteractiveToolkit(artifact_store=fake_store)
    tk._bot = _bot(enhance_return=good_html)
    result = await tk.render(
        template_name="dashboard", brief="make it live", mode="enhance",
        libraries=["echarts"],
    )
    assert result.enhanced is True
    persisted = fake_store.save_artifact.call_args[0][-1]
    assert persisted.definition["html"] == good_html


async def test_enhance_malicious_falls_back_to_skeleton(fake_store, caplog):
    evil = '<script src="https://evil.example/x.js"></script>'
    tk = InteractiveToolkit(artifact_store=fake_store)
    tk._bot = _bot(enhance_return=evil)
    with caplog.at_level("WARNING"):
        result = await tk.render(
            template_name="dashboard", brief="add interactivity", mode="enhance",
            libraries=["echarts"],
        )
    assert result.enhanced is False
    assert any("ENHANCE_OUTPUT_INVALID" in r.message for r in caplog.records)
    persisted = fake_store.save_artifact.call_args[0][-1]
    assert "evil.example" not in persisted.definition["html"]  # malicious dropped


async def test_enhance_without_bound_bot_falls_back(fake_store, caplog):
    tk = InteractiveToolkit(artifact_store=fake_store)
    # No _bot bound and no enhance_interactive available.
    with caplog.at_level("WARNING"):
        result = await tk.render(
            template_name="diagram", brief="a flowchart", mode="enhance",
        )
    assert result.enhanced is False


# ---------------------------------------------------------------------------
# Validation / error paths
# ---------------------------------------------------------------------------

async def test_unknown_template_raises(toolkit):
    with pytest.raises(InteractiveValidationError) as ei:
        await toolkit.render(template_name="ghost", brief="x", mode="deterministic")
    assert ei.value.code == "TEMPLATE_UNKNOWN"


async def test_library_not_allowed_for_template_raises(toolkit):
    # 'diagram' only allows mermaid; requesting echarts must be rejected.
    with pytest.raises(InteractiveValidationError) as ei:
        await toolkit.render(
            template_name="diagram", brief="x", mode="deterministic",
            libraries=["echarts"],
        )
    assert ei.value.code == "LIBRARY_NOT_ALLOWED"


async def test_enhance_requires_brief(toolkit):
    with pytest.raises(InteractiveValidationError) as ei:
        await toolkit.render(template_name="dashboard", brief="", mode="enhance")
    assert ei.value.code == "ENHANCE_BRIEF_MISSING"


# ---------------------------------------------------------------------------
# Tool wiring
# ---------------------------------------------------------------------------

def test_only_render_is_return_direct(toolkit):
    tools = toolkit.get_tools()
    by_name = {t.name: t for t in tools}
    assert by_name["interactive_render"].return_direct is True
    assert by_name["interactive_list_templates"].return_direct is False
    assert by_name["interactive_get_scaffold"].return_direct is False
