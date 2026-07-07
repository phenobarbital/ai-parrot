"""Tests for the shared parse_kwargs utility."""
import pytest

from parrot.integrations.utils import parse_kwargs


class TestParseKwargs:
    def test_empty_string(self):
        assert parse_kwargs("") == {}

    def test_whitespace_only(self):
        assert parse_kwargs("   ") == {}

    def test_none_input(self):
        assert parse_kwargs(None) == {}

    def test_simple_key_value(self):
        result = parse_kwargs("key=val")
        assert result == {"key": "val"}

    def test_multiple_key_values(self):
        result = parse_kwargs("name=Alice age=30")
        assert result == {"name": "Alice", "age": "30"}

    def test_quoted_value(self):
        result = parse_kwargs('report="Read this loudly"')
        assert result == {"report": "Read this loudly"}

    def test_quoted_value_with_nested_single_quotes(self):
        result = parse_kwargs("""report="In a place of 'La-Mancha'" max_lines=2""")
        assert result == {"report": "In a place of 'La-Mancha'", "max_lines": "2"}

    def test_single_quoted_value(self):
        result = parse_kwargs("report='Hello world' num=1")
        assert result == {"report": "Hello world", "num": "1"}

    def test_positional_args(self):
        result = parse_kwargs("hello world")
        assert result == {"arg0": "hello", "arg1": "world"}

    def test_mixed_kwargs_and_positional(self):
        result = parse_kwargs('name=Alice hello key="big value"')
        assert result == {"name": "Alice", "arg0": "hello", "key": "big value"}

    def test_malformed_quotes_fallback(self):
        """Unmatched quotes should fall back to simple split."""
        result = parse_kwargs('key="unclosed value')
        assert "key" in result or "arg0" in result
