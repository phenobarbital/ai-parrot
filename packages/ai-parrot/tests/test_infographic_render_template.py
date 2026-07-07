"""Unit tests for InfographicToolkit.render_template (Jinja template path).

Covers the template-driven infographic rendering that makes the toolkit usable
by ANY agent (not just PandasAgent): trusted HTML+Jinja templates + explicit
``data``, persisted as an INFOGRAPHIC artifact, and finalized to an HTML
artifact by the generic-agent post-loop branch in ``base.py``.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.tools.infographic_toolkit import (
    InfographicToolkit,
    InfographicRenderResult,
    InfographicValidationError,
)
from parrot.models.outputs import OutputMode
from parrot.storage.models import ArtifactType
from parrot.storage.artifact_signing import get_signing_key, verify_signature
from parrot.bots.base import BaseBot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    return store


def _bot(last_response=None):
    bot = SimpleNamespace(
        user_id="u", agent_id="agt", session_id="sess",
        _current_user_id=None, _current_agent_id=None, _current_session_id=None,
    )
    if last_response is not None:
        bot.last_response = last_response
    return bot


_TEMPLATES = {
    "summary.html.j2": "<!DOCTYPE html><html><body><h1>{{ data.title }}</h1></body></html>",
    "echo.html.j2": "<p>{{ data.x }}</p>",
    "message.html.j2": "<p>{{ message.output }}</p>",
    "missing.html.j2": "<p>{{ data.absent }}</p>",
}


@pytest.fixture
def toolkit(fake_store):
    tk = InfographicToolkit(artifact_store=fake_store, templates=_TEMPLATES)
    tk._bot = _bot()
    return tk


# ---------------------------------------------------------------------------
# Happy path + persistence
# ---------------------------------------------------------------------------

async def test_render_template_persists_and_returns_envelope(toolkit, fake_store):
    result = await toolkit.render_template(
        template_name="summary.html.j2", data={"title": "Hi"}, theme="dark",
    )
    assert isinstance(result, InfographicRenderResult)
    assert result.enhanced is False
    assert result.template_name == "summary.html.j2"
    assert result.theme == "dark"
    assert "Hi" in result.html_inline

    assert fake_store.save_artifact.call_count == 1
    artifact = fake_store.save_artifact.call_args[0][-1]
    assert artifact.artifact_type == ArtifactType.INFOGRAPHIC
    assert "Hi" in artifact.definition["html"]
    assert artifact.definition["template"] == "summary.html.j2"
    assert artifact.definition["theme"] == "dark"
    assert artifact.definition["js_bundles"] == []

    assert result.html_url.startswith("/api/v1/artifacts/public/")
    assert f"/{result.artifact_id}.html" in result.html_url


async def test_render_template_signed_url_roundtrips(toolkit):
    result = await toolkit.render_template(
        template_name="echo.html.j2", data={"x": "ok"},
    )
    segment = result.html_url.split("/api/v1/artifacts/public/")[1].split("/")[0]
    assert verify_signature(result.artifact_id, segment, get_signing_key()) is True


async def test_render_template_autoescapes_data(toolkit):
    result = await toolkit.render_template(
        template_name="echo.html.j2", data={"x": "<script>alert(1)</script>"},
    )
    assert "&lt;script&gt;" in result.html_inline
    assert "<script>alert(1)</script>" not in result.html_inline


async def test_render_template_message_autoinjected(fake_store):
    tk = InfographicToolkit(artifact_store=fake_store, templates=_TEMPLATES)
    last = SimpleNamespace(output="from previous turn", metadata={})
    tk._bot = _bot(last_response=last)
    result = await tk.render_template(template_name="message.html.j2")
    assert "from previous turn" in result.html_inline


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

async def test_render_template_unknown_template(toolkit):
    with pytest.raises(InfographicValidationError) as ei:
        await toolkit.render_template(template_name="nope.html.j2", data={})
    assert ei.value.code == "TEMPLATE_UNKNOWN"


async def test_render_template_strict_undefined_missing_var(toolkit):
    with pytest.raises(InfographicValidationError) as ei:
        await toolkit.render_template(template_name="missing.html.j2", data={})
    assert ei.value.code == "TEMPLATE_RENDER_ERROR"


async def test_render_template_engine_unset(fake_store):
    tk = InfographicToolkit(artifact_store=fake_store)  # no templates configured
    tk._bot = _bot()
    with pytest.raises(InfographicValidationError) as ei:
        await tk.render_template(template_name="whatever", data={})
    assert ei.value.code == "TEMPLATE_ENGINE_UNSET"


async def test_add_template_registers_at_runtime(fake_store):
    tk = InfographicToolkit(artifact_store=fake_store)
    tk._bot = _bot()
    tk.add_template("late.html.j2", "<b>{{ data.v }}</b>")
    result = await tk.render_template(template_name="late.html.j2", data={"v": "z"})
    assert "<b>z</b>" in result.html_inline


# ---------------------------------------------------------------------------
# Tool wiring
# ---------------------------------------------------------------------------

def test_render_template_is_return_direct(toolkit):
    tools = {t.name: t for t in toolkit.get_tools()}
    assert "infographic_render_template" in tools
    assert tools["infographic_render_template"].return_direct is True


# ---------------------------------------------------------------------------
# Generic-agent finalize branch (base.py) — usable by ANY agent
# ---------------------------------------------------------------------------

def _envelope():
    return InfographicRenderResult(
        artifact_id="infographic-abc123",
        html_url="/api/v1/artifacts/public/sig/infographic-abc123.html",
        html_inline="<html>report</html>",
        template_name="summary.html.j2",
        theme="dark",
        data_variables=[],
        enhanced=False,
    )


def test_base_extracts_and_finalizes_infographic_result():
    bot = BaseBot.__new__(BaseBot)  # bypass heavy __init__; methods use only args
    envelope = _envelope()
    tool_calls = [SimpleNamespace(result="not-an-envelope"), SimpleNamespace(result=envelope)]

    extracted = bot._extract_last_infographic_result(tool_calls)
    assert extracted is envelope

    response = SimpleNamespace(
        output="short explanation", response=None, output_mode=OutputMode.DEFAULT,
        artifact_id=None, metadata={},
    )
    explanation = bot._finalize_infographic_response(response, envelope)

    assert explanation == "short explanation"
    assert response.output == "<html>report</html>"
    assert response.output_mode == OutputMode.INFOGRAPHIC
    assert response.artifact_id == "infographic-abc123"
    assert response.response == "short explanation"
    assert response.metadata["html_url"] == envelope.html_url
    assert response.metadata["template_name"] == "summary.html.j2"


def test_base_extract_returns_none_without_envelope():
    bot = BaseBot.__new__(BaseBot)
    assert bot._extract_last_infographic_result(None) is None
    assert bot._extract_last_infographic_result([SimpleNamespace(result=123)]) is None
