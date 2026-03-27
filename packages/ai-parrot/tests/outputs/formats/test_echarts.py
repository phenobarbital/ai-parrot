import asyncio
import json

import pytest

from parrot.outputs.formats.echarts import EChartsRenderer


def test_echarts_renderer_unwraps_option_key():
    """Ensure wrapped configurations under `option` are accepted."""

    renderer = EChartsRenderer()
    wrapped_config = {
        "option": {
            "title": {"text": "Wrapped Chart"},
            "series": [
                {
                    "type": "bar",
                    "data": [1, 2, 3],
                }
            ],
        }
    }

    config, error = renderer.execute_code(json.dumps(wrapped_config))

    assert error is None
    assert "series" in config
    assert config["title"]["text"] == "Wrapped Chart"


def test_echarts_renderer_returns_wrapped_error_html_for_invalid_json(caplog):
    """When the JSON is invalid, HTML output should be returned as wrapped content."""

    renderer = EChartsRenderer()

    class DummyResponse:
        output = None
        response = "```json\n{ invalid }\n```"

    with caplog.at_level("ERROR"):
        content, wrapped = asyncio.run(
            renderer.render(
                DummyResponse(),
                output_format="html",
            )
        )

    assert content == "{ invalid }"
    assert wrapped is not None
    assert "Chart Generation Error" in wrapped
    assert any("Failed to parse ECharts JSON" in record.message for record in caplog.records)


def test_echarts_renderer_returns_code_with_html_output_on_success():
    """HTML renders should return the generated JSON code in the output slot."""

    renderer = EChartsRenderer()
    response_json = json.dumps(
        {
            "title": {"text": "Hello"},
            "series": [{"type": "pie", "data": [1, 2, 3]}],
        }
    )

    class DummyResponse:
        output = None
        response = f"```json\n{response_json}\n```"

    content, wrapped = asyncio.run(
        renderer.render(
            DummyResponse(),
            output_format="html",
        )
    )

    assert content == response_json
    assert wrapped is not None
    assert "chart-container" in wrapped
