import json

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
