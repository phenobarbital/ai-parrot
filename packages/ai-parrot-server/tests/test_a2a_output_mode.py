"""A2AServer output-mode plumbing: plain text (OutputMode.TEXT) by default.

Copilot renders A2A TextParts literally, so the server asks the agent for
markdown-free plain text unless configured otherwise.
"""
from unittest.mock import MagicMock

from parrot.a2a.models import Message
from parrot.models.outputs import OutputMode
from parrot.a2a.server import A2AServer


def _server(**kwargs) -> A2AServer:
    agent = MagicMock()
    agent.name = "TestAgent"
    return A2AServer(agent, **kwargs)


def _message() -> Message:
    return Message.user("get me the count of fso orders", context_id="ctx-1")


class TestOutputModeConfig:
    def test_defaults_to_text(self):
        assert _server()._output_mode == OutputMode.TEXT

    def test_accepts_enum_and_string(self):
        assert _server(output_mode=OutputMode.MARKDOWN)._output_mode == (
            OutputMode.MARKDOWN
        )
        assert _server(output_mode="markdown")._output_mode == OutputMode.MARKDOWN
        assert _server(output_mode="text")._output_mode == OutputMode.TEXT

    def test_none_and_default_disable_injection(self):
        assert _server(output_mode=None)._output_mode == OutputMode.DEFAULT
        assert _server(output_mode="default")._output_mode == OutputMode.DEFAULT

    def test_unknown_string_falls_back_to_default(self):
        assert _server(output_mode="not-a-mode")._output_mode == OutputMode.DEFAULT


class TestBuildAskKwargs:
    def test_text_mode_injected_by_default(self):
        kwargs = _server()._build_ask_kwargs(_message())
        assert kwargs["output_mode"] == OutputMode.TEXT
        assert kwargs["session_id"] == "ctx-1"

    def test_configured_mode_injected(self):
        kwargs = _server(output_mode="markdown")._build_ask_kwargs(_message())
        assert kwargs["output_mode"] == OutputMode.MARKDOWN

    def test_default_mode_omits_key(self):
        kwargs = _server(output_mode=None)._build_ask_kwargs(_message())
        assert "output_mode" not in kwargs
