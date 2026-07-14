"""Regression tests for Gemini function-name sanitization.

Google Gemini rejects tool/function names that are not identifier-like with a
``400 INVALID_ARGUMENT`` that fails the *entire* request::

    GenerateContentRequest.tools[0].function_declarations[N].name:
    Invalid function name. Must start with a letter or an underscore...

``GoogleGenAIClient`` normalises every declaration name and keeps a reverse
map so the model's tool calls resolve back to the real tool.
"""
import re

import pytest

from parrot.clients.google.client import GoogleGenAIClient


# start with a letter/underscore, then only [a-zA-Z0-9_.:-], max length 128.
_GEMINI_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_.:-]{0,127}\Z")


def _bare_client() -> GoogleGenAIClient:
    """A GoogleGenAIClient instance without the heavy __init__."""
    return GoogleGenAIClient.__new__(GoogleGenAIClient)


class TestSanitizeFunctionName:
    def test_valid_name_passthrough(self):
        assert GoogleGenAIClient._sanitize_function_name("execution_context_tool") == "execution_context_tool"

    def test_allowed_symbols_preserved(self):
        assert (
            GoogleGenAIClient._sanitize_function_name("with-dash.and:colon")
            == "with-dash.and:colon"
        )

    def test_space_replaced(self):
        assert GoogleGenAIClient._sanitize_function_name("agent_Company Research") == "agent_Company_Research"

    def test_leading_non_letter_prefixed(self):
        out = GoogleGenAIClient._sanitize_function_name("123abc")
        assert out.startswith("_")
        assert _GEMINI_NAME_RE.fullmatch(out)

    def test_empty_name(self):
        assert _GEMINI_NAME_RE.fullmatch(GoogleGenAIClient._sanitize_function_name(""))

    def test_length_capped_at_128(self):
        assert len(GoogleGenAIClient._sanitize_function_name("x" * 300)) == 128

    @pytest.mark.parametrize(
        "raw",
        [
            "agent_Company Research",
            "news & rss",
            "site (news) editor",
            "naïve/name",
            "tool@host",
        ],
    )
    def test_output_always_gemini_valid(self, raw):
        assert _GEMINI_NAME_RE.fullmatch(GoogleGenAIClient._sanitize_function_name(raw))


class TestRegisterSanitizedName:
    def test_records_reverse_mapping(self):
        client = _bare_client()
        alias = client._register_sanitized_name("agent_Company Research")
        assert alias == "agent_Company_Research"
        assert client._sanitized_name_map[alias] == "agent_Company Research"

    def test_valid_name_maps_to_itself(self):
        client = _bare_client()
        alias = client._register_sanitized_name("valid_tool")
        assert alias == "valid_tool"
        assert client._sanitized_name_map["valid_tool"] == "valid_tool"

    def test_collision_disambiguated(self):
        """Two distinct originals collapsing to the same alias stay distinct."""
        client = _bare_client()
        a = client._register_sanitized_name("a b")  # -> a_b
        b = client._register_sanitized_name("a/b")  # would also be a_b
        assert a != b
        assert client._sanitized_name_map[a] == "a b"
        assert client._sanitized_name_map[b] == "a/b"

    def test_idempotent_for_same_original(self):
        client = _bare_client()
        first = client._register_sanitized_name("a b")
        second = client._register_sanitized_name("a b")
        assert first == second
        # No spurious collision aliases were created.
        assert list(client._sanitized_name_map.values()).count("a b") == 1
