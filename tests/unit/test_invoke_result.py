"""Unit tests for InvokeResult model and InvokeError exception (TASK-480)."""
import pytest
from pydantic import BaseModel
from parrot.models.responses import InvokeResult
from parrot.models.basic import CompletionUsage
from parrot.exceptions import InvokeError, ParrotError


class SampleModel(BaseModel):
    """Fixture Pydantic model for structured output tests."""
    name: str
    age: int


class TestInvokeResult:
    """Tests for InvokeResult Pydantic model."""

    def test_structured_output(self):
        """InvokeResult with Pydantic model output stores all fields correctly."""
        usage = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        result = InvokeResult(
            output=SampleModel(name="Alice", age=30),
            output_type=SampleModel,
            model="gpt-4.1",
            usage=usage,
        )
        assert isinstance(result.output, SampleModel)
        assert result.output.name == "Alice"
        assert result.output_type is SampleModel
        assert result.model == "gpt-4.1"
        assert result.usage.total_tokens == 15
        assert result.raw_response is None

    def test_raw_string_output(self):
        """InvokeResult with raw string output and output_type=None."""
        usage = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        result = InvokeResult(
            output="Hello world",
            output_type=None,
            model="claude-haiku-4-5-20251001",
            usage=usage,
        )
        assert result.output == "Hello world"
        assert result.output_type is None

    def test_with_raw_response(self):
        """InvokeResult includes raw_response for debugging."""
        usage = CompletionUsage()
        raw = {"id": "msg_123", "content": [{"type": "text", "text": "hi"}]}
        result = InvokeResult(
            output="hi",
            model="test-model",
            usage=usage,
            raw_response=raw,
        )
        assert result.raw_response == raw

    def test_default_raw_response_is_none(self):
        """raw_response defaults to None when not provided."""
        usage = CompletionUsage()
        result = InvokeResult(output="hi", model="test", usage=usage)
        assert result.raw_response is None

    def test_arbitrary_types_allowed(self):
        """InvokeResult accepts non-serializable types (class references)."""
        usage = CompletionUsage()
        result = InvokeResult(
            output=SampleModel(name="Bob", age=25),
            output_type=SampleModel,
            model="test",
            usage=usage,
        )
        # output_type stores the class itself, not a string
        assert result.output_type is SampleModel
        assert isinstance(result.output_type, type)


class TestInvokeError:
    """Tests for InvokeError exception class."""

    def test_basic_error(self):
        """InvokeError with a message only."""
        err = InvokeError("something failed")
        assert str(err) == "something failed"
        assert err.original is None

    def test_wraps_original(self):
        """InvokeError preserves the original exception."""
        original = ValueError("API rate limit")
        err = InvokeError("invoke failed", original=original)
        assert err.original is original
        assert isinstance(err.original, ValueError)

    def test_is_parrot_error(self):
        """InvokeError inherits from ParrotError."""
        err = InvokeError("test")
        assert isinstance(err, ParrotError)

    def test_is_exception(self):
        """InvokeError can be raised and caught as Exception."""
        with pytest.raises(InvokeError) as exc_info:
            raise InvokeError("test raise")
        assert str(exc_info.value) == "test raise"

    def test_original_preserved_through_raise(self):
        """original attribute is accessible after the error is raised."""
        original = RuntimeError("upstream failure")
        with pytest.raises(InvokeError) as exc_info:
            raise InvokeError("wrapped", original=original)
        assert exc_info.value.original is original
