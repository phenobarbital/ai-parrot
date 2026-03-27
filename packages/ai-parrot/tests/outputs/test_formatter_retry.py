"""Tests for OutputFormatter LLM retry functionality."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.outputs.formatter import (
    OutputFormatter,
    OutputRetryConfig,
    OutputRetryResult,
    DEFAULT_RETRY_PROMPTS,
)
from parrot.outputs.formats.base import RenderResult, RenderError
from parrot.models.outputs import OutputMode


class MockAIMessage:
    """Mock AIMessage response for testing."""

    def __init__(self, response: str, output=None):
        self.response = response
        self.output = output
        self.content = response


class MockLLMClient:
    """Mock LLM client for testing retry functionality."""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0
        self.calls = []

    async def ask(
        self,
        prompt: str,
        system_prompt: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        model: str = None,
        **kwargs
    ):
        self.calls.append({
            'prompt': prompt,
            'system_prompt': system_prompt,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'model': model,
        })
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        raise Exception("No more mock responses")


# ============================================================================
# OutputRetryConfig Tests
# ============================================================================


def test_output_retry_config_defaults():
    """Test default values for OutputRetryConfig."""
    config = OutputRetryConfig()

    assert config.max_retries == 2
    assert config.retry_on_parse_error is True
    assert config.retry_model is None
    assert config.retry_temperature == 0.1
    assert config.retry_max_tokens == 4096
    assert config.include_original_prompt is True
    assert config.custom_retry_prompts == {}


def test_output_retry_config_custom_values():
    """Test custom values for OutputRetryConfig."""
    custom_prompts = {
        OutputMode.ECHARTS: "Custom ECharts prompt: {original_output}"
    }
    config = OutputRetryConfig(
        max_retries=5,
        retry_on_parse_error=False,
        retry_model="gpt-4",
        retry_temperature=0.5,
        retry_max_tokens=8192,
        include_original_prompt=False,
        custom_retry_prompts=custom_prompts,
    )

    assert config.max_retries == 5
    assert config.retry_on_parse_error is False
    assert config.retry_model == "gpt-4"
    assert config.retry_temperature == 0.5
    assert config.retry_max_tokens == 8192
    assert config.include_original_prompt is False
    assert OutputMode.ECHARTS in config.custom_retry_prompts


def test_output_retry_config_get_custom_prompt():
    """Test getting custom retry prompt for a mode."""
    custom_prompts = {
        OutputMode.JSON: "Fix this JSON: {original_output}"
    }
    config = OutputRetryConfig(custom_retry_prompts=custom_prompts)

    assert config.get_retry_prompt(OutputMode.JSON) == "Fix this JSON: {original_output}"
    assert config.get_retry_prompt(OutputMode.ECHARTS) is None


# ============================================================================
# OutputRetryResult Tests
# ============================================================================


def test_output_retry_result_success():
    """Test successful retry result."""
    result = OutputRetryResult(
        success=True,
        content="formatted content",
        wrapped_content="<html>wrapped</html>",
        retry_count=1,
        original_error="Initial parse error",
    )

    assert result.success is True
    assert result.content == "formatted content"
    assert result.wrapped_content == "<html>wrapped</html>"
    assert result.retry_count == 1
    assert result.original_error == "Initial parse error"
    assert result.final_error is None


def test_output_retry_result_failure():
    """Test failed retry result."""
    result = OutputRetryResult(
        success=False,
        content="raw output",
        wrapped_content=None,
        retry_count=3,
        original_error="Parse error",
        final_error="Max retries exceeded",
    )

    assert result.success is False
    assert result.retry_count == 3
    assert result.original_error == "Parse error"
    assert result.final_error == "Max retries exceeded"


# ============================================================================
# DEFAULT_RETRY_PROMPTS Tests
# ============================================================================


def test_default_retry_prompts_exist():
    """Test that default retry prompts exist for key modes."""
    assert OutputMode.ECHARTS in DEFAULT_RETRY_PROMPTS
    assert OutputMode.JSON in DEFAULT_RETRY_PROMPTS
    assert OutputMode.PLOTLY in DEFAULT_RETRY_PROMPTS
    assert OutputMode.YAML in DEFAULT_RETRY_PROMPTS


def test_default_retry_prompts_contain_placeholders():
    """Test that prompts contain required placeholders."""
    for mode, prompt in DEFAULT_RETRY_PROMPTS.items():
        assert "{original_output}" in prompt, f"Missing original_output in {mode} prompt"
        assert "{error_message}" in prompt, f"Missing error_message in {mode} prompt"


# ============================================================================
# OutputFormatter Initialization Tests
# ============================================================================


def test_formatter_initialization_without_retry():
    """Test formatter initialization without retry components."""
    formatter = OutputFormatter()

    assert formatter.llm_client is None
    assert formatter.retry_config is not None
    assert isinstance(formatter.retry_config, OutputRetryConfig)


def test_formatter_initialization_with_llm_client():
    """Test formatter initialization with LLM client."""
    mock_client = MockLLMClient()
    formatter = OutputFormatter(llm_client=mock_client)

    assert formatter.llm_client is mock_client


def test_formatter_initialization_with_retry_config():
    """Test formatter initialization with custom retry config."""
    config = OutputRetryConfig(max_retries=5)
    formatter = OutputFormatter(retry_config=config)

    assert formatter.retry_config.max_retries == 5


def test_formatter_set_llm_client():
    """Test setting LLM client after initialization."""
    formatter = OutputFormatter()
    mock_client = MockLLMClient()

    assert formatter.llm_client is None
    formatter.set_llm_client(mock_client)
    assert formatter.llm_client is mock_client


def test_formatter_set_retry_config():
    """Test updating retry config after initialization."""
    formatter = OutputFormatter()
    new_config = OutputRetryConfig(max_retries=10)

    formatter.set_retry_config(new_config)
    assert formatter.retry_config.max_retries == 10


# ============================================================================
# Retry Prompt Generation Tests
# ============================================================================


def test_get_retry_prompt_uses_default():
    """Test that default prompts are used when no custom prompt exists."""
    formatter = OutputFormatter()

    prompt = formatter._get_retry_prompt(
        mode=OutputMode.ECHARTS,
        original_output='{"invalid": json',
        error_message="JSONDecodeError: Expecting value",
    )

    assert '{"invalid": json' in prompt
    assert "JSONDecodeError" in prompt
    assert "ECharts" in prompt or "JSON" in prompt


def test_get_retry_prompt_uses_custom():
    """Test that custom prompts override defaults."""
    custom_prompt = "Custom prompt: {original_output} - Error: {error_message}"
    config = OutputRetryConfig(
        custom_retry_prompts={OutputMode.ECHARTS: custom_prompt}
    )
    formatter = OutputFormatter(retry_config=config)

    prompt = formatter._get_retry_prompt(
        mode=OutputMode.ECHARTS,
        original_output="bad json",
        error_message="parse error",
    )

    assert prompt == "Custom prompt: bad json - Error: parse error"


def test_get_retry_prompt_includes_original_prompt():
    """Test that original user prompt is included when configured."""
    config = OutputRetryConfig(include_original_prompt=True)
    formatter = OutputFormatter(retry_config=config)

    prompt = formatter._get_retry_prompt(
        mode=OutputMode.JSON,
        original_output="invalid",
        error_message="error",
        original_prompt="Create a bar chart",
    )

    assert "Create a bar chart" in prompt
    assert "Original User Request" in prompt


def test_get_retry_prompt_excludes_original_prompt():
    """Test that original prompt is excluded when configured."""
    config = OutputRetryConfig(include_original_prompt=False)
    formatter = OutputFormatter(retry_config=config)

    prompt = formatter._get_retry_prompt(
        mode=OutputMode.JSON,
        original_output="invalid",
        error_message="error",
        original_prompt="Create a bar chart",
    )

    assert "Create a bar chart" not in prompt


def test_get_retry_prompt_fallback_for_unknown_mode():
    """Test fallback prompt for modes without specific prompts."""
    formatter = OutputFormatter()

    prompt = formatter._get_retry_prompt(
        mode=OutputMode.DEFAULT,  # No specific prompt for DEFAULT
        original_output="some output",
        error_message="some error",
    )

    assert "some output" in prompt
    assert "some error" in prompt


# ============================================================================
# Raw Output Extraction Tests
# ============================================================================


def test_extract_raw_output_from_aimessage():
    """Test extracting raw output from AIMessage-like object."""
    formatter = OutputFormatter()
    message = MockAIMessage(response="test response")

    output = formatter._extract_raw_output(message)
    assert output == "test response"


def test_extract_raw_output_from_dict():
    """Test extracting raw output from dictionary."""
    formatter = OutputFormatter()

    output = formatter._extract_raw_output({"response": "dict response"})
    assert output == "dict response"

    output = formatter._extract_raw_output({"content": "dict content"})
    assert output == "dict content"


def test_extract_raw_output_from_string():
    """Test extracting raw output from string."""
    formatter = OutputFormatter()

    output = formatter._extract_raw_output("plain string")
    assert output == "plain string"


# ============================================================================
# Parse Error Detection Tests
# ============================================================================


def test_is_parse_error_result_detects_none_content():
    """Test detection of None content as error."""
    formatter = OutputFormatter()

    is_error, msg = formatter._is_parse_error_result(None, None, OutputMode.JSON)
    assert is_error is True
    assert "None" in msg


def test_is_parse_error_result_detects_error_patterns():
    """Test detection of common error patterns."""
    formatter = OutputFormatter()

    test_cases = [
        ("Error parsing JSON", "Error parsing"),
        ("Invalid JSON: unexpected token", "Invalid JSON"),
        ("JSONDecodeError: Expecting value", "JSONDecodeError"),
        ("class='error'>Error</div>", "class='error'"),
        ("No ECharts configuration found", "No ECharts configuration found"),
    ]

    for content, expected_pattern in test_cases:
        is_error, msg = formatter._is_parse_error_result(
            content, None, OutputMode.JSON
        )
        assert is_error is True, f"Failed to detect: {expected_pattern}"


def test_is_parse_error_result_valid_content():
    """Test that valid content is not marked as error."""
    formatter = OutputFormatter()

    is_error, msg = formatter._is_parse_error_result(
        '{"valid": "json"}',
        '<html>valid</html>',
        OutputMode.JSON
    )
    assert is_error is False
    assert msg is None


# ============================================================================
# Format with Retry Tests
# ============================================================================


@pytest.mark.asyncio
async def test_format_with_retry_success_without_retry():
    """Test successful format that doesn't need retry."""
    # Create a valid ECharts response
    valid_json = json.dumps({
        "title": {"text": "Test Chart"},
        "series": [{"type": "bar", "data": [1, 2, 3]}]
    })

    response = MockAIMessage(response=f"```json\n{valid_json}\n```")
    formatter = OutputFormatter()

    result = await formatter.format_with_retry(
        mode=OutputMode.ECHARTS,
        data=response,
        output_format='html',
    )

    assert result.success is True
    assert result.retry_count == 0
    assert result.original_error is None


@pytest.mark.asyncio
async def test_format_with_retry_no_client_returns_error():
    """Test that retry without LLM client returns failure."""
    # Create invalid JSON response
    response = MockAIMessage(response="```json\n{invalid}\n```")
    formatter = OutputFormatter()  # No LLM client

    result = await formatter.format_with_retry(
        mode=OutputMode.ECHARTS,
        data=response,
        output_format='html',
    )

    assert result.success is False
    assert "No LLM client" in result.final_error


@pytest.mark.asyncio
async def test_format_with_retry_success_after_retry():
    """Test successful format after LLM retry."""
    # Create invalid JSON that triggers retry
    invalid_response = MockAIMessage(response="```json\n{invalid}\n```")

    # Create valid JSON that LLM will "fix" to
    valid_json = json.dumps({
        "title": {"text": "Fixed Chart"},
        "series": [{"type": "bar", "data": [1, 2, 3]}]
    })
    fixed_response = MockAIMessage(response=f"```json\n{valid_json}\n```")

    mock_client = MockLLMClient(responses=[fixed_response])
    formatter = OutputFormatter(llm_client=mock_client)

    result = await formatter.format_with_retry(
        mode=OutputMode.ECHARTS,
        data=invalid_response,
        original_prompt="Create a bar chart",
        output_format='html',
    )

    assert result.success is True
    assert result.retry_count == 1
    assert mock_client.call_count == 1
    # Verify original prompt was passed
    assert "bar chart" in mock_client.calls[0]['prompt']


@pytest.mark.asyncio
async def test_format_with_retry_max_retries_exceeded():
    """Test that max retries is respected."""
    # Create responses that always produce invalid output
    invalid_response = MockAIMessage(response="```json\n{invalid}\n```")

    mock_client = MockLLMClient(responses=[
        invalid_response,
        invalid_response,
        invalid_response,
    ])
    config = OutputRetryConfig(max_retries=2)
    formatter = OutputFormatter(llm_client=mock_client, retry_config=config)

    result = await formatter.format_with_retry(
        mode=OutputMode.ECHARTS,
        data=invalid_response,
        output_format='html',
    )

    assert result.success is False
    assert result.retry_count == 2  # Stopped at max_retries


@pytest.mark.asyncio
async def test_format_with_retry_disabled():
    """Test that retry can be disabled."""
    invalid_response = MockAIMessage(response="```json\n{invalid}\n```")
    valid_json = json.dumps({"series": [{"type": "bar", "data": [1]}]})
    fixed_response = MockAIMessage(response=f"```json\n{valid_json}\n```")

    mock_client = MockLLMClient(responses=[fixed_response])
    config = OutputRetryConfig(retry_on_parse_error=False)
    formatter = OutputFormatter(llm_client=mock_client, retry_config=config)

    result = await formatter.format_with_retry(
        mode=OutputMode.ECHARTS,
        data=invalid_response,
        output_format='html',
    )

    assert result.success is False
    assert result.retry_count == 0  # No retry attempted
    assert mock_client.call_count == 0  # Client never called


@pytest.mark.asyncio
async def test_format_with_retry_override_client():
    """Test overriding LLM client for specific call."""
    invalid_response = MockAIMessage(response="```json\n{invalid}\n```")
    valid_json = json.dumps({"series": [{"type": "bar", "data": [1]}]})
    fixed_response = MockAIMessage(response=f"```json\n{valid_json}\n```")

    default_client = MockLLMClient(responses=[])
    override_client = MockLLMClient(responses=[fixed_response])

    formatter = OutputFormatter(llm_client=default_client)

    result = await formatter.format_with_retry(
        mode=OutputMode.ECHARTS,
        data=invalid_response,
        llm_client=override_client,  # Override for this call
        output_format='html',
    )

    assert result.success is True
    assert override_client.call_count == 1
    assert default_client.call_count == 0


@pytest.mark.asyncio
async def test_format_with_retry_override_config():
    """Test overriding retry config for specific call."""
    invalid_response = MockAIMessage(response="```json\n{invalid}\n```")

    mock_client = MockLLMClient(responses=[
        invalid_response,
        invalid_response,
        invalid_response,
    ])

    default_config = OutputRetryConfig(max_retries=5)
    override_config = OutputRetryConfig(max_retries=1)

    formatter = OutputFormatter(llm_client=mock_client, retry_config=default_config)

    result = await formatter.format_with_retry(
        mode=OutputMode.ECHARTS,
        data=invalid_response,
        retry_config=override_config,  # Override for this call
        output_format='html',
    )

    assert result.success is False
    assert result.retry_count == 1  # Used override config's max_retries


@pytest.mark.asyncio
async def test_format_with_retry_llm_request_params():
    """Test that LLM request uses correct parameters from config."""
    invalid_response = MockAIMessage(response="```json\n{invalid}\n```")
    valid_json = json.dumps({"series": [{"type": "bar", "data": [1]}]})
    fixed_response = MockAIMessage(response=f"```json\n{valid_json}\n```")

    mock_client = MockLLMClient(responses=[fixed_response])
    config = OutputRetryConfig(
        retry_temperature=0.5,
        retry_max_tokens=2048,
        retry_model="gpt-4",
    )
    formatter = OutputFormatter(llm_client=mock_client, retry_config=config)

    await formatter.format_with_retry(
        mode=OutputMode.ECHARTS,
        data=invalid_response,
        output_format='html',
    )

    assert mock_client.call_count == 1
    call = mock_client.calls[0]
    assert call['temperature'] == 0.5
    assert call['max_tokens'] == 2048
    assert call['model'] == "gpt-4"


# ============================================================================
# RenderResult and RenderError Tests
# ============================================================================


def test_render_error_creation():
    """Test RenderError dataclass creation."""
    error = RenderError(
        message="Parse failed",
        error_type="json_parse",
        raw_output='{"invalid',
        details={"line": 1, "column": 10}
    )

    assert error.message == "Parse failed"
    assert error.error_type == "json_parse"
    assert error.raw_output == '{"invalid'
    assert error.details["line"] == 1


def test_render_result_success():
    """Test successful RenderResult creation."""
    result = RenderResult(
        success=True,
        content="formatted",
        wrapped_content="<html>",
    )

    assert result.success is True
    assert result.content == "formatted"
    assert result.wrapped_content == "<html>"
    assert result.error is None


def test_render_result_with_error():
    """Test RenderResult with error."""
    error = RenderError(message="Failed", error_type="validation")
    result = RenderResult(
        success=False,
        content="raw",
        error=error,
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.message == "Failed"
