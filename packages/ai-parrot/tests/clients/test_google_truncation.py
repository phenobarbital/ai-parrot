"""Unit tests for the Google client's truncation-as-last-line-of-defense
(TASK-1961).
"""
import subprocess

import pytest

from parrot.clients.google.client import GoogleGenAIClient


@pytest.fixture
def google_client():
    return GoogleGenAIClient(api_key="fake_key")


class TestGoogleTruncation:
    def test_truncation_logs_a_warning(self, google_client, caplog):
        huge = "x" * (google_client.MAX_TOOL_RESULT_CHARS + 1000)
        with caplog.at_level("WARNING"):
            google_client._process_tool_result_for_api(huge, tool_name="huge_tool")
        assert any("trunc" in r.message.lower() for r in caplog.records)

    def test_truncation_warning_names_the_tool_and_sizes(self, google_client, caplog):
        huge = "x" * (google_client.MAX_TOOL_RESULT_CHARS + 1000)
        with caplog.at_level("WARNING"):
            google_client._process_tool_result_for_api(huge, tool_name="huge_tool")
        matches = [r.message for r in caplog.records if "trunc" in r.message.lower()]
        assert matches
        assert "huge_tool" in matches[0]
        assert str(google_client.MAX_TOOL_RESULT_CHARS) in matches[0]

    def test_truncation_warning_degrades_without_tool_name(self, google_client, caplog):
        huge = "x" * (google_client.MAX_TOOL_RESULT_CHARS + 1000)
        with caplog.at_level("WARNING"):
            google_client._process_tool_result_for_api(huge)  # no tool_name
        assert any("trunc" in r.message.lower() for r in caplog.records)

    def test_no_truncation_for_typical_compressed_payload(self, google_client, caplog):
        payload = {"columns": ["a", "b"], "rows": [[1, 2]] * 500,
                   "constants": {"c": 1}}
        with caplog.at_level("WARNING"):
            out = google_client._process_tool_result_for_api(payload, tool_name="dq_tool")
        assert "[TRUNCATED]" not in str(out)
        assert not any("trunc" in r.message.lower() for r in caplog.records)

    def test_no_double_reduction_on_serialized_path(self, google_client, caplog):
        """A payload that already went through the compression pipeline
        (columnar-shaped, well under the limit) must pass through
        unchanged — no second, unprincipled truncation on top."""
        payload = {
            "columns": ["store_id", "revenue"],
            "rows": [[f"S{i:04d}", 1000.0 + i] for i in range(200)],
            "constants": {"region": "south"},
        }
        with caplog.at_level("WARNING"):
            out = google_client._process_tool_result_for_api(payload, tool_name="dq_tool")
        assert out["result"]["columns"] == payload["columns"]
        assert out["result"]["rows"] == payload["rows"]
        assert not any("trunc" in r.message.lower() for r in caplog.records)

    def test_threshold_is_overridable_class_attribute(self, google_client):
        assert isinstance(type(google_client).MAX_TOOL_RESULT_CHARS, int)
        google_client.MAX_TOOL_RESULT_CHARS = 10
        assert google_client.MAX_TOOL_RESULT_CHARS == 10

    def test_threshold_kept_at_200000_with_documented_rationale(self):
        # TASK-1961 decision: kept at 200,000 pending TASK-1959's empirical
        # benchmark data — see the class attribute's docstring/comment.
        assert GoogleGenAIClient.MAX_TOOL_RESULT_CHARS == 200_000

    def test_fallback_path_logs_truncation_warning(self, google_client, caplog):
        """Non-JSON-serializable object whose str() representation exceeds
        the limit still logs the warning (the third truncation site)."""
        class Weird:
            def __repr__(self):
                return "x" * (google_client.MAX_TOOL_RESULT_CHARS + 500)

        with caplog.at_level("WARNING"):
            out = google_client._process_tool_result_for_api(Weird(), tool_name="weird_tool")
        # Exception objects short-circuit earlier; a plain unserializable
        # object with no model_dump/dict falls through to the fallback
        # string-representation path.
        assert isinstance(out, dict)


def test_no_compression_import_in_clients():
    """G1: compression logic exists in exactly one place."""
    out = subprocess.run(
        ["grep", "-rn", "--include=*.py", "parrot.tools.compression",
         "packages/ai-parrot/src/parrot/clients/"],
        capture_output=True, text=True,
    ).stdout
    assert out == "", out


def test_no_filterlevel_or_codec_reference_in_google_client():
    """G1 (stronger form): not even indirect references to the pipeline's
    vocabulary (FilterLevel, codec dispatch) belong in this client."""
    import inspect
    from parrot.clients.google import client as google_client_module
    src = inspect.getsource(google_client_module)
    assert "FilterLevel" not in src
    assert "CompressionStage" not in src
    assert "CompressorRegistry" not in src
