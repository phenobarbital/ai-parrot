"""Pydantic contracts for the LiveAvatar Phase C voice bridge (FEAT-243).

These models are pure Pydantic v2 and intentionally free of any
``livekit-agents`` import so the module loads even when the optional
``liveavatar-voice`` extra is not installed.

- :class:`AvatarJobMetadata` is parsed from ``ctx.job.metadata`` (a JSON
  string) and injects ``tenant_id`` / ``agent_name`` / ``session_id`` into the
  worker (spec section 2, Module 1).

Note: ``StructuredOutputMessage`` has been relocated to
``parrot.integrations.liveavatar.models`` (FEAT-249 §3.4).
"""

from typing import Optional

from pydantic import BaseModel

__all__ = ["AvatarJobMetadata"]


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
