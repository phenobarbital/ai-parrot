"""Codegen-side response models for the AgentChat conversation envelope.

``AgentTalk`` (``parrot.handlers.agent``) builds its response envelope as a
plain ``dict`` in two places — the stream finaliser
(``agent.py:2556-2600``, written after the ``b"\\n\\x00"`` separator) and
the JSON formatter (``_format_response``, ``agent.py:2777-2823``). Neither
builder is refactored to construct a Pydantic model directly: the models
below are a **contract + codegen source only**, mirroring both dict shapes
so the Admin UI can consume a generated TypeScript type
(``ui/src/lib/types/generated/AgentChatResponse.d.ts``) instead of a
hand-copied one. ``packages/ai-parrot-server/tests/test_chat_models.py``
feeds representative dicts from both builders through
``AgentChatResponse.model_validate`` so drift in either direction fails CI.

See ``sdd/specs/agentchat-migration.spec.md`` §2 "Envelope codegen" / §2
Data Models / §3 Module 0 (FEAT-476).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentToolCall(BaseModel):
    """A single tool invocation as emitted by either envelope builder.

    Mirrors the ``tool_calls`` list entries built in
    ``agent.py:2574-2583`` (stream finaliser) and ``agent.py:2807-2816``
    (JSON formatter).
    """

    model_config = ConfigDict(extra="allow")

    name: str = "unknown"
    status: str = "completed"
    output: Any = None
    arguments: Any = None


class AgentChatMetadata(BaseModel):
    """The ``metadata`` sub-envelope shared by both builders.

    ``created_at`` is only ever populated by the JSON path
    (``agent.py:2777-2818``); the stream path never sets it. Additional
    keys (e.g. infographic extras — ``explanation``, ``html_url``,
    ``artifact_id``, ``template_name``, ``theme``) arrive via
    ``extra="allow"``.
    """

    model_config = ConfigDict(extra="allow")

    model: str | None = None
    provider: str | None = None
    session_id: str = ""
    turn_id: str = ""
    user_id: str | None = None
    response_time: int | None = None  # milliseconds
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    stop_reason: str | None = None
    created_at: str | None = None  # JSON path only
    is_error: bool | None = None


class AgentChatResponse(BaseModel):
    """The ``AgentTalk`` response envelope (stream finaliser + JSON path).

    ``data``, ``response``, ``output_mode`` and ``code`` are populated
    only by the JSON formatter (``agent.py:2777-2823``); the stream
    finaliser (``agent.py:2556-2600``) never sets them. ``audio_base64``/
    ``audio_format`` are set only on the voice path
    (``parrot.handlers.agent_voice.AgentVoiceTalk``).
    """

    model_config = ConfigDict(extra="allow")

    input: str | None = None
    output: Any = None  # str | dict | list (DataFrame records / model_dump)
    data: Any = None  # JSON path only
    response: str | None = None  # JSON path only
    output_mode: str | None = None  # JSON path only
    code: str | None = None  # JSON path only
    metadata: AgentChatMetadata
    sources: list[dict[str, Any]] = []
    tool_calls: list[AgentToolCall] = []
    a2ui_envelope: dict[str, Any] | list[dict[str, Any]] | None = None
    audio_base64: str | None = None  # voice path
    audio_format: str | None = None
