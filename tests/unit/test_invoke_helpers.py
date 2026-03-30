"""Unit tests for AbstractClient invoke() shared helper methods (TASK-481)."""
import pytest
from unittest.mock import MagicMock, AsyncMock
from pydantic import BaseModel

from parrot.models.responses import InvokeResult
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import StructuredOutputConfig, OutputFormat
from parrot.exceptions import InvokeError


class SampleOutput(BaseModel):
    """Fixture Pydantic model for helper tests."""
    value: str


def _make_client():
    """Create a concrete AbstractClient subclass without network setup."""
    from parrot.clients.base import AbstractClient

    class _TestClient(AbstractClient):
        """Minimal concrete subclass for testing helpers."""
        _default_model = "test-model"
        model = "test-model"

        async def ask(self, *args, **kwargs):
            raise NotImplementedError

        async def ask_stream(self, *args, **kwargs):
            raise NotImplementedError

        async def resume(self, *args, **kwargs):
            raise NotImplementedError

        async def invoke(self, *args, **kwargs):
            raise NotImplementedError

        async def get_client(self):
            return None

    client = _TestClient.__new__(_TestClient)
    client.model = "test-model"
    client._lightweight_model = None
    client._fallback_model = None
    client.logger = MagicMock()
    return client


@pytest.fixture
def client():
    """AbstractClient test instance."""
    return _make_client()


class TestResolveInvokeSystemPrompt:
    """Tests for _resolve_invoke_system_prompt()."""

    def test_custom_prompt_passthrough(self, client):
        """Custom system_prompt returned as-is without modification."""
        result = client._resolve_invoke_system_prompt("Custom instructions")
        assert result == "Custom instructions"

    def test_default_template_rendering(self, client):
        """BASIC_SYSTEM_PROMPT rendered with instance attributes."""
        client.name = "TestBot"
        client.capabilities = "search, analyze"
        result = client._resolve_invoke_system_prompt(None)
        assert "TestBot" in result
        assert "search, analyze" in result

    def test_missing_attrs_safe_defaults(self, client):
        """Missing attributes use safe defaults — no KeyError raised."""
        # client has no name/role/capabilities/goal/backstory set
        result = client._resolve_invoke_system_prompt(None)
        assert "AI" in result  # default name fallback

    def test_empty_string_not_treated_as_falsy(self, client):
        """Empty string system_prompt should be passed through, not replaced."""
        result = client._resolve_invoke_system_prompt("")
        # Empty string is a valid override (caller intentionally wants no system prompt)
        assert result == ""

    def test_none_triggers_template(self, client):
        """None triggers template rendering."""
        client.name = "MyAgent"
        result = client._resolve_invoke_system_prompt(None)
        assert "MyAgent" in result


class TestBuildInvokeStructuredConfig:
    """Tests for _build_invoke_structured_config()."""

    def test_output_type_wrapped_in_config(self, client):
        """output_type wrapped into StructuredOutputConfig with JSON format."""
        config = client._build_invoke_structured_config(SampleOutput, None)
        assert isinstance(config, StructuredOutputConfig)
        assert config.output_type is SampleOutput
        assert config.format == OutputFormat.JSON

    def test_structured_output_takes_precedence(self, client):
        """structured_output param takes precedence over output_type."""
        explicit = StructuredOutputConfig(output_type=SampleOutput, format=OutputFormat.YAML)
        config = client._build_invoke_structured_config(str, explicit)
        assert config is explicit

    def test_none_when_no_output(self, client):
        """Returns None when neither output_type nor structured_output provided."""
        config = client._build_invoke_structured_config(None, None)
        assert config is None

    def test_structured_output_returned_unchanged(self, client):
        """structured_output with custom_parser is returned unchanged."""
        def my_parser(text):
            return SampleOutput(value=text)

        config = StructuredOutputConfig(
            output_type=SampleOutput,
            format=OutputFormat.JSON,
            custom_parser=my_parser,
        )
        result = client._build_invoke_structured_config(SampleOutput, config)
        assert result is config
        assert result.custom_parser is my_parser


class TestResolveInvokeModel:
    """Tests for _resolve_invoke_model()."""

    def test_explicit_model_returned(self, client):
        """Explicit model param is returned directly."""
        result = client._resolve_invoke_model("gpt-4o")
        assert result == "gpt-4o"

    def test_lightweight_model_fallback(self, client):
        """Falls back to _lightweight_model when no explicit model."""
        client._lightweight_model = "claude-haiku-4-5-20251001"
        result = client._resolve_invoke_model(None)
        assert result == "claude-haiku-4-5-20251001"

    def test_default_model_fallback(self, client):
        """Falls back to self.model when no _lightweight_model."""
        client._lightweight_model = None
        client.model = "gpt-4o-mini"
        result = client._resolve_invoke_model(None)
        assert result == "gpt-4o-mini"

    def test_explicit_overrides_lightweight(self, client):
        """Explicit model overrides _lightweight_model."""
        client._lightweight_model = "cheap-model"
        result = client._resolve_invoke_model("expensive-model")
        assert result == "expensive-model"


class TestBuildInvokeResult:
    """Tests for _build_invoke_result()."""

    def test_constructs_result_correctly(self, client):
        """Correct InvokeResult construction from all fields."""
        usage = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        result = client._build_invoke_result(
            output="hello",
            output_type=None,
            model="test-model",
            usage=usage,
        )
        assert isinstance(result, InvokeResult)
        assert result.output == "hello"
        assert result.output_type is None
        assert result.model == "test-model"
        assert result.usage.total_tokens == 15
        assert result.raw_response is None

    def test_constructs_with_structured_output(self, client):
        """InvokeResult with Pydantic model output and output_type."""
        usage = CompletionUsage()
        sample = SampleOutput(value="test")
        result = client._build_invoke_result(
            output=sample,
            output_type=SampleOutput,
            model="gpt-4.1",
            usage=usage,
            raw_response={"raw": True},
        )
        assert result.output is sample
        assert result.output_type is SampleOutput
        assert result.raw_response == {"raw": True}


class TestHandleInvokeError:
    """Tests for _handle_invoke_error()."""

    def test_wraps_exception(self, client):
        """Provider exception wrapped as InvokeError with original preserved."""
        original = RuntimeError("API failed")
        error = client._handle_invoke_error(original)
        assert isinstance(error, InvokeError)
        assert error.original is original

    def test_message_from_exception(self, client):
        """InvokeError message is the str() of the original exception."""
        original = ValueError("connection timeout")
        error = client._handle_invoke_error(original)
        assert "connection timeout" in str(error)

    def test_returns_error_not_raises(self, client):
        """_handle_invoke_error returns the error, does not raise it."""
        original = Exception("test")
        result = client._handle_invoke_error(original)
        assert isinstance(result, InvokeError)
