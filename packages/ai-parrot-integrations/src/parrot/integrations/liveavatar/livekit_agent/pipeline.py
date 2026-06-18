"""LiveKit Agents voice pipeline for LiveAvatar Phase C (FEAT-243, Module 1).

``build_session()`` assembles the ``AgentSession`` that keeps the starter's
voice pipeline — STT, VAD (Silero, prewarmed and passed in), turn-detection
(MultilingualModel) and TTS — while the LLM node is replaced by
:class:`LiveAvatarAgent` (bound at ``session.start`` in :mod:`.worker`).

**Provider selection (FEAT-246)** — STT and TTS defaults are now driven by
:func:`~parrot.integrations.liveavatar.livekit_agent.voice_adapters.resolve_stt`
and
:func:`~parrot.integrations.liveavatar.livekit_agent.voice_adapters.resolve_tts`
rather than hard-coded Deepgram/Cartesia.  Set ``LIVEAVATAR_STT_PROVIDER`` /
``LIVEAVATAR_TTS_PROVIDER`` (default ``"whisper"`` / ``"supertonic"``) to
select a different backend.  Deepgram and Cartesia remain available as
opt-in alternatives via those env vars.

The heavy ``livekit-agents`` / ``livekit-plugins-*`` packages (the
``liveavatar-voice`` extra) are imported lazily inside the default component
factories, so this module imports without the extra and ``build_session`` is
unit-testable by injecting fake components and a fake ``session_factory``.

.. note::
   **P5 / Q-plugins** — the exact plugin classes, model names and the
   ``AgentSession`` constructor MUST be validated against the pinned
   ``livekit-agents`` version before production use.
"""

import logging
from typing import Any, Callable, Optional

__all__ = ["build_session"]

logger = logging.getLogger(__name__)

#: Default STT model for the Deepgram provider. Override via ``LIVEAVATAR_STT_MODEL``.
DEFAULT_STT_MODEL = "nova-3"


def _default_turn_detection() -> Any:  # pragma: no cover - requires the extra
    """Construct the default multilingual turn-detection model (lazy import)."""
    try:
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "livekit-plugins-turn-detector is required for turn-detection. "
            "Install the 'liveavatar-voice' extra."
        ) from exc
    return MultilingualModel()


def _default_session_factory() -> Callable[..., Any]:  # pragma: no cover
    """Return the ``AgentSession`` constructor (lazy import of livekit-agents)."""
    try:
        from livekit.agents import AgentSession
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "livekit-agents is required to build an AgentSession. "
            "Install the 'liveavatar-voice' extra."
        ) from exc
    return AgentSession


def build_session(
    vad: Any,
    *,
    stt: Optional[Any] = None,
    tts: Optional[Any] = None,
    turn_detection: Optional[Any] = None,
    session_factory: Optional[Callable[..., Any]] = None,
) -> Any:
    """Build the voice ``AgentSession`` (STT / VAD / turn-detection / TTS).

    STT and TTS defaults are resolved via
    :func:`~parrot.integrations.liveavatar.livekit_agent.voice_adapters.resolve_stt`
    and
    :func:`~parrot.integrations.liveavatar.livekit_agent.voice_adapters.resolve_tts`
    (FEAT-246), which read ``LIVEAVATAR_STT_PROVIDER`` / ``LIVEAVATAR_TTS_PROVIDER``
    from the environment (default: ``"whisper"`` + ``"supertonic"``).  Explicit
    *stt* / *tts* overrides take precedence unchanged.

    Args:
        vad: Voice-activity-detection plugin instance (e.g. Silero), typically
            prewarmed in the worker and passed in.  Forwarded to
            :func:`~.voice_adapters.resolve_stt` for ``StreamAdapter`` wrapping.
        stt: Speech-to-text component.  When ``None`` (default), resolved via
            ``LIVEAVATAR_STT_PROVIDER`` (default ``"whisper"``).
        tts: Text-to-speech component.  When ``None`` (default), resolved via
            ``LIVEAVATAR_TTS_PROVIDER`` (default ``"supertonic"``).
        turn_detection: Turn-detection model; defaults to the multilingual model.
        session_factory: Constructor used to build the session; defaults to
            ``livekit.agents.AgentSession``. Injected in tests.

    Returns:
        The constructed ``AgentSession`` with all four components wired. The
        LLM node (``LiveAvatarAgent``) is bound separately at ``session.start``.
    """
    from parrot.integrations.liveavatar.livekit_agent.voice_adapters import (
        resolve_stt,
        resolve_tts,
    )

    stt = stt if stt is not None else resolve_stt(vad)
    tts = tts if tts is not None else resolve_tts()
    turn_detection = (
        turn_detection if turn_detection is not None else _default_turn_detection()
    )
    make_session = session_factory or _default_session_factory()

    logger.debug(
        "Building AgentSession (stt=%s, vad=%s, tts=%s, turn_detection=%s)",
        type(stt).__name__,
        type(vad).__name__,
        type(tts).__name__,
        type(turn_detection).__name__,
    )
    return make_session(
        stt=stt,
        vad=vad,
        tts=tts,
        turn_detection=turn_detection,
    )
