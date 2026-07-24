"""Unit tests for the data-splice render mode (FEAT-326, Module 2 / TASK-1883)."""
from __future__ import annotations

import json

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.tools.infographic_toolkit import (
    InfographicToolkit,
    InfographicRenderResult,
    InfographicValidationError,
)
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TINY_TEMPLATE = (
    "<!doctype html><html><head><title>T</title></head><body>"
    "<h1>Report</h1>"
    '<script type="application/json" id="report-data">\n{}\n</script>'
    "<div>footer</div></body></html>"
)

CUSTOM_MARKER_TEMPLATE = (
    "<html><body>"
    '<script type="application/json" id="my-data">\n{}\n</script>'
    "</body></html>"
)

NO_MARKER_TEMPLATE = "<html><body><h1>No marker here</h1></body></html>"


@pytest.fixture
def fake_artifact_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed/x")
    return store


@pytest.fixture
def toolkit(fake_artifact_store):
    tk = InfographicToolkit(
        artifact_store=fake_artifact_store,
        templates={
            "tiny": TINY_TEMPLATE,
            "custom": CUSTOM_MARKER_TEMPLATE,
            "nomarker": NO_MARKER_TEMPLATE,
        },
    )
    bot = MagicMock()
    bot._current_user_id = None
    bot._current_agent_id = None
    bot._current_session_id = None
    bot.user_id = "u"
    bot.agent_id = "agt"
    bot.session_id = "sess"
    tk._bot = bot
    return tk


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRenderDataTemplate:
    async def test_splices_json_into_marker(self, toolkit, fake_artifact_store):
        payload = {"days": {"20260101": [["A", "p", 1, 2, 3, 4]]}}
        result = await toolkit.render_data_template("tiny", payload)
        assert isinstance(result, InfographicRenderResult)
        # The persisted HTML carries the spliced payload.
        artifact = fake_artifact_store.save_artifact.call_args[0][-1]
        html = artifact.definition["html"]
        start = html.index('id="report-data">') + len('id="report-data">')
        end = html.index("</script>", start)
        assert json.loads(html[start:end]) == payload

    async def test_template_otherwise_byte_identical(self, toolkit, fake_artifact_store):
        payload = {"x": 1}
        await toolkit.render_data_template("tiny", payload)
        artifact = fake_artifact_store.save_artifact.call_args[0][-1]
        html = artifact.definition["html"]
        # Everything before the marker's inner content and after </script> is intact.
        marker = '<script type="application/json" id="report-data">'
        assert html[: html.index(marker) + len(marker)] == \
            TINY_TEMPLATE[: TINY_TEMPLATE.index(marker) + len(marker)]
        tail = "</script><div>footer</div></body></html>"
        assert html.endswith(tail)

    async def test_marker_missing_raises_structured_error(self, toolkit):
        with pytest.raises(InfographicValidationError) as exc:
            await toolkit.render_data_template("nomarker", {"x": 1})
        assert exc.value.code == "SPLICE_MARKER_MISSING"
        assert exc.value.detail["marker_id"] == "report-data"

    async def test_custom_marker_id(self, toolkit, fake_artifact_store):
        await toolkit.render_data_template("custom", {"y": 2}, marker_id="my-data")
        artifact = fake_artifact_store.save_artifact.call_args[0][-1]
        html = artifact.definition["html"]
        start = html.index('id="my-data">') + len('id="my-data">')
        end = html.index("</script>", start)
        assert json.loads(html[start:end]) == {"y": 2}

    async def test_nan_rejected_numpy_coerced(self, toolkit, fake_artifact_store):
        # numpy int coerced fine
        await toolkit.render_data_template("tiny", {"count": np.int64(7)})
        artifact = fake_artifact_store.save_artifact.call_args[0][-1]
        html = artifact.definition["html"]
        start = html.index('id="report-data">') + len('id="report-data">')
        end = html.index("</script>", start)
        assert json.loads(html[start:end]) == {"count": 7}

        # NaN rejected loudly
        with pytest.raises(InfographicValidationError) as exc:
            await toolkit.render_data_template("tiny", {"bad": float("nan")})
        assert exc.value.code == "PAYLOAD_NOT_SERIALIZABLE"

    async def test_unknown_template_raises(self, toolkit):
        with pytest.raises(InfographicValidationError) as exc:
            await toolkit.render_data_template("does-not-exist", {"x": 1})
        assert exc.value.code == "TEMPLATE_UNKNOWN"

    async def test_descriptor_gate_runs_first(self, toolkit, fake_artifact_store):
        # Section declares a 'records' shape but payload provides a scalar → the
        # gate must fire BEFORE any splice/persist.
        descriptor = SectionDescriptor(
            template="tiny",
            mode="data-splice",
            sections=[SectionSpec(name="hero", target="hero", shape="records")],
        )
        with pytest.raises(InfographicValidationError) as exc:
            await toolkit.render_data_template(
                "tiny", {"hero": 42}, descriptor=descriptor
            )
        assert exc.value.code == "payload_shape_mismatch"
        assert fake_artifact_store.save_artifact.call_count == 0

    async def test_descriptor_marker_id_overrides(self, toolkit, fake_artifact_store):
        descriptor = SectionDescriptor(
            template="custom",
            mode="data-splice",
            splice_marker_id="my-data",
            sections=[SectionSpec(name="y", target="y", shape="scalar")],
        )
        await toolkit.render_data_template("custom", {"y": 5}, descriptor=descriptor)
        artifact = fake_artifact_store.save_artifact.call_args[0][-1]
        html = artifact.definition["html"]
        assert 'id="my-data">' in html

    async def test_persists_via_artifact_store(self, toolkit, fake_artifact_store):
        await toolkit.render_data_template("tiny", {"x": 1})
        assert fake_artifact_store.save_artifact.call_count == 1

    def test_init_signature_unchanged(self, fake_artifact_store):
        # Constructor still accepts only the documented keyword args.
        tk = InfographicToolkit(artifact_store=fake_artifact_store)
        assert tk is not None

    def test_tool_exposed_with_prefix(self, toolkit):
        names = {t.name for t in toolkit.get_tools()}
        assert "infographic_render_data_template" in names
