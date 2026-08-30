"""Contract tests for the AgentChat envelope Pydantic models.

Feeds representative dicts shaped like both ``AgentTalk`` envelope
builders (stream finaliser ``agent.py:2556-2600`` and JSON formatter
``agent.py:2777-2823``) through ``AgentChatResponse.model_validate`` so
drift in either direction fails CI, and asserts the three models are
registered in the TS codegen pipeline with schemas matching the committed
files (FEAT-476, TASK-2590).
"""

import json
from pathlib import Path

from parrot.server.ui.chat_models import AgentChatResponse

STREAM_ENVELOPE = {  # mirrors handlers/agent.py:2556-2600
    "input": "hi",
    "output": "hello",
    "metadata": {
        "model": "m",
        "provider": "p",
        "session_id": "s",
        "turn_id": "t",
        "user_id": None,
        "response_time": 12,
        "usage": None,
        "finish_reason": None,
        "stop_reason": None,
    },
    "sources": [],
    "tool_calls": [{"name": "x", "status": "completed", "output": None, "arguments": None}],
}
JSON_ENVELOPE = {
    **STREAM_ENVELOPE,
    "data": None,
    "response": "hello",
    "output_mode": "json",
    "code": None,
    "metadata": {**STREAM_ENVELOPE["metadata"], "created_at": "2026-08-30T00:00:00"},
    "a2ui_envelope": {"version": "v1.0"},
}


def test_stream_envelope_validates():
    m = AgentChatResponse.model_validate(STREAM_ENVELOPE)
    assert m.response is None and m.tool_calls[0].name == "x"


def test_json_envelope_validates():
    m = AgentChatResponse.model_validate(JSON_ENVELOPE)
    assert m.metadata.created_at and m.a2ui_envelope == {"version": "v1.0"}


def test_voice_fields_and_extras():
    m = AgentChatResponse.model_validate(
        {
            **JSON_ENVELOPE,
            "audio_base64": "AAA",
            "audio_format": "audio/wav",
            "metadata": {**JSON_ENVELOPE["metadata"], "explanation": "e", "html_url": "u"},
        }
    )
    assert m.audio_format == "audio/wav" and m.metadata.model_extra["html_url"] == "u"


def test_codegen_registry(tmp_path: Path):
    import importlib
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    gen = importlib.import_module("scripts.generate_ts_types")
    names = set(gen._models())
    assert {"AgentChatResponse", "AgentChatMetadata", "AgentToolCall"} <= names
    written = gen.export_schemas(tmp_path)
    committed = Path(gen.SCHEMAS_DIR)
    for name in ("AgentChatResponse", "AgentChatMetadata", "AgentToolCall"):
        assert json.loads(written[name].read_text()) == json.loads((committed / f"{name}.json").read_text())
