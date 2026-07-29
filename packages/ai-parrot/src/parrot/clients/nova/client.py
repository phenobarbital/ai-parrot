"""NovaClient — unified client for all Amazon Nova models (FEAT-315).

Composes the Bedrock Converse text engine with the voice and generation
mixins, mirroring how :class:`~parrot.clients.google.client.GoogleGenAIClient`
composes ``AbstractClient`` with ``GoogleGeneration``/``GoogleAnalysis``
(spec ``novaclient-amazon-aws`` §2/§3 Module 2)::

    class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
        ...

Text (``ask``/``ask_stream``/``invoke``/``resume``) is INHERITED from
:class:`~parrot.clients.bedrock.BedrockConverseBase` — no delegation
object, no reimplementation (resolved spec §8 U1). Voice
(``stream_voice``) comes from :class:`~parrot.clients.nova.audio.NovaAudio`
(TASK-1807). Generation (``generate_image``/``video_generation``) comes
from :class:`~parrot.clients.nova.generation.NovaGeneration` (TASK-1808).

See ``sdd/specs/novaclient-amazon-aws.spec.md`` (§3 Module 2) for the full
design.
"""
from __future__ import annotations

from typing import Optional

from ..bedrock import BedrockConverseBase
from .audio import NovaAudio
from .generation import NovaGeneration


class NovaClient(BedrockConverseBase, NovaAudio, NovaGeneration):
    """Unified client for all Amazon Nova models on Bedrock.

    Covers every Nova modality through a single client, mirroring
    :class:`~parrot.clients.google.client.GoogleGenAIClient`:

    - **Text** (Nova 2 Lite, Micro, Pro, Premier): ``ask()``/
      ``ask_stream()``/``invoke()``/``resume()``, inherited from
      :class:`~parrot.clients.bedrock.BedrockConverseBase`.
    - **Voice** (Nova Sonic / Nova 2 Sonic): ``stream_voice()``, from
      :class:`~parrot.clients.nova.audio.NovaAudio`. Requires the
      Pre-Alpha ``aws_sdk_bedrock_runtime`` package (Python >= 3.12) —
      only at first call, never for text/generation-only usage.
    - **Generation** (Nova Canvas / Nova Reel): ``generate_image()``/
      ``video_generation()``, from
      :class:`~parrot.clients.nova.generation.NovaGeneration`.

    Credentials (``aws_id``) are resolved by
    :class:`~parrot.clients.bedrock.BedrockConverseBase` from
    ``parrot.conf::AWS_CREDENTIALS`` (correct keys, ``'default'``
    fallback) — see that class for the full resolution order.

    Nova 2 Lite and Nova Premier have NO in-region model access; they
    require a geo/global inference-profile prefix (``us.``/``eu.``/
    ``jp.``/``global.``). ``region_prefix`` therefore DEFAULTS to
    ``"us"`` here (unlike :class:`BedrockConverseClient`, whose default is
    ``None``) so the default model resolves to
    ``us.amazon.nova-2-lite-v1:0`` out of the box. Override
    ``region_prefix`` for EU/JP deployments, or pass ``region_prefix=None``
    to opt out entirely for in-region custom deployments.
    """

    client_type: str = "nova"
    client_name: str = "nova"
    _default_model: str = "nova-2-lite"
    _fallback_model: str = "nova-lite"

    def __init__(
        self,
        aws_id: Optional[str] = None,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        region_prefix: Optional[str] = "us",
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        voice_id: str = "matthew",
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        **kwargs,
    ):
        """Initialise a unified Nova client.

        Args:
            aws_id: Optional ``AWS_CREDENTIALS`` profile name. See
                :class:`~parrot.clients.bedrock.BedrockConverseBase` for
                the full resolution order.
            region: AWS region for the Bedrock Runtime endpoint.
            profile: Optional named AWS profile, passed to
                ``aioboto3.Session``.
            region_prefix: Cross-region inference-profile prefix. Defaults
                to ``"us"`` — Nova 2 Lite/Premier require a geo/global
                prefix; pass ``None`` to opt out for in-region custom
                deployments, or ``"eu"``/``"jp"``/``"global"`` for other
                regions.
            guardrail_id: Bedrock guardrail identifier.
            guardrail_version: Bedrock guardrail version.
            voice_id: Default Nova Sonic synthesis voice (e.g.
                ``"matthew"``, ``"tiffany"``, ``"amy"``). Overridable
                per-call via ``stream_voice(voice_id=...)`` (spec §8
                resolved).
            aws_access_key: AWS access key ID. See ``BedrockConverseBase``.
            aws_secret_key: AWS secret access key. See ``BedrockConverseBase``.
            aws_session_token: Optional STS session token. See
                ``BedrockConverseBase``.
            **kwargs: Forwarded to
                :class:`~parrot.clients.bedrock.BedrockConverseBase`
                (and, through it, :class:`~parrot.clients.base.AbstractClient`).
        """
        self.voice_id = voice_id
        super().__init__(
            aws_id=aws_id,
            region=region,
            profile=profile,
            region_prefix=region_prefix,
            guardrail_id=guardrail_id,
            guardrail_version=guardrail_version,
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key,
            aws_session_token=aws_session_token,
            **kwargs,
        )
