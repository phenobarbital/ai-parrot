"""Pydantic contracts for the LiveAvatar Phase C voice bridge (FEAT-243).

These models are pure Pydantic v2 and intentionally free of any
``livekit-agents`` import so the module loads even when the optional
``liveavatar-voice`` extra is not installed.

- :class:`AvatarJobMetadata` is parsed from ``ctx.job.metadata`` (a JSON
  string) and injects ``tenant_id`` / ``agent_name`` / ``session_id`` into the
  worker (spec section 2, Module 1).
- :class:`StructuredOutputMessage` is the output-bridge contract (Open
  Question P4): structured ai-parrot outputs are published to the AgentChat UI
  WebSocket channel keyed by ``session_id`` (spec section 2, Module 3).
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

__all__ = ["AvatarJobMetadata", "StructuredOutputMessage"]


class AvatarJobMetadata(BaseModel):
    """LiveKit job metadata parsed from ``ctx.job.metadata`` (JSON).

    Attributes:
        ws_url: LiveKit room WebSocket URL carried in the job metadata
            (informational / diagnostics). The worker connects via
            ``ctx.connect()`` and the avatar joins through the API-returned
            config, so this value is not used to establish the connection.
        session_id: AgentChat conversation id shared with the avatar turn.
        agent_name: Name of the ai-parrot agent that acts as the brain.
        tenant_id: Optional tenant/program identifier (avatar is opt-in per
            tenant). ``None`` when the deployment is single-tenant.
    """

    ws_url: str
    session_id: str
    agent_name: str
    tenant_id: Optional[str] = None


class StructuredOutputMessage(BaseModel):
    """Output-bridge contract (P4) for structured ai-parrot outputs.

    Structured outputs (charts, data, canvas updates, tool calls) produced
    during a voice turn are published to the AgentChat UI WebSocket channel
    keyed by :attr:`session_id` — the same conversation the avatar is speaking.

    Attributes:
        type: Output kind, e.g. ``"chart"`` | ``"data"`` | ``"canvas"`` |
            ``"tool_call"``.
        session_id: Conversation id used as the WebSocket channel key.
        payload: Arbitrary structured payload the AgentChat UI renders.
        turn_id: Optional identifier of the voice turn that produced the output.
    """

    type: str = Field(
        ...,
        description='Output kind, e.g. "chart" | "data" | "canvas" | "tool_call".',
    )
    session_id: str = Field(
        ...,
        description="Conversation id used as the WebSocket channel key.",
    )
    payload: Dict[str, Any] = Field(
        ...,
        description="Structured payload rendered by the AgentChat UI.",
    )
    turn_id: Optional[str] = Field(
        default=None,
        description="Optional id of the voice turn that produced this output.",
    )
