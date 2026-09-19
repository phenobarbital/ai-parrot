"""Default Google credential for handler-built AgentCrews (``CREW_AI_KEY``).

FEAT-575. Crews created and executed through the AgentCrew HTTP handlers bill
their Google traffic to the process-wide ``GOOGLE_API_KEY``, which makes
crew-builder usage impossible to meter or rotate separately. This module
resolves an opt-in ``CREW_AI_KEY`` and classifies an agent's raw LLM
declaration so the crew build paths can inject it.

Nothing here mutates a ``CrewDefinition``, and the key value is never logged.
"""

from __future__ import annotations

from typing import Any, Optional

from navconfig.logging import logging  # verified: crew.py:53

from .... import conf

logger = logging.getLogger(__name__)

#: The three ``parrot.clients`` entry points of ``ai-parrot-client-google``.
#: verified: packages/ai-parrot-client-google/pyproject.toml:36-38
GOOGLE_PROVIDER_KEYS: frozenset[str] = frozenset({"google", "gemini-live", "google-compat"})

#: ``llm_kwargs`` keys that mean "this agent brought its own credential".
_CREDENTIAL_KWARGS: tuple[str, ...] = ("api_key", "credentials_file", "credentials")

#: Module-level warn-once latch (AC6). Reset by tests via monkeypatch.
_warned_unset: bool = False


def get_crew_google_api_key() -> Optional[str]:
    """Return the configured crew Google API key, or ``None``.

    Reads ``parrot.conf.CREW_AI_KEY`` through the module object (never a
    from-import) so a monkeypatched value is honoured. Logs a single warning
    per process when the key is unset; the key value is never logged.

    Returns:
        The configured ``CREW_AI_KEY``, or ``None`` when it is unset/empty.
    """
    global _warned_unset  # noqa: PLW0603 — deliberate process-wide warn-once latch
    key = getattr(conf, "CREW_AI_KEY", None)
    if key:
        return key
    if not _warned_unset:
        _warned_unset = True
        logger.warning("CREW_AI_KEY is not set; crew Google agents fall back to GOOGLE_API_KEY")
    return None


def _google_client_classes() -> tuple[type, ...]:
    """Resolve ``GOOGLE_PROVIDER_KEYS`` to client classes, tolerating absence.

    Returns:
        Every class the Google entry points resolve to. Empty when the
        ``ai-parrot-client-google`` satellite is not installed.
    """
    from ....clients.factory import SUPPORTED_CLIENTS  # noqa: PLC0415 — FEAT-523 lazy import
    from ...abstract import _resolve_supported_client  # noqa: PLC0415 — FEAT-523 lazy import

    classes: list[type] = []
    for key in GOOGLE_PROVIDER_KEYS:
        try:
            entry = SUPPORTED_CLIENTS.get(key)
            if entry is None:
                continue
            resolved = _resolve_supported_client(entry)
            if isinstance(resolved, type):
                classes.append(resolved)
        except Exception:  # noqa: BLE001 — satellite missing / lookup error -> skip
            continue
    return tuple(classes)


def is_google_llm(llm: Any, default_provider: Optional[str] = "google") -> bool:
    """Report whether an agent's raw LLM declaration resolves to a Google provider.

    Args:
        llm: The agent's ``_llm_raw`` value — a ``provider[:model]`` string, an
            ``AbstractClient`` subclass, an ``AbstractClient`` instance, or ``None``.
        default_provider: The provider used when ``llm`` is ``None`` (the bot's
            ``_default_llm``, which is ``"google"``).

    Returns:
        ``True`` only for a Google provider string, a Google client **class**, or
        ``None`` with a Google ``default_provider``. A client *instance* and any
        other callable are always ``False`` — a live instance carries its own
        credentials.
    """
    if llm is None:
        return bool(default_provider) and default_provider.lower() in GOOGLE_PROVIDER_KEYS
    if isinstance(llm, str):
        provider = llm.split(":", 1)[0].strip().lower()
        return provider in GOOGLE_PROVIDER_KEYS
    if isinstance(llm, type):
        return issubclass(llm, _google_client_classes())
    return False


def apply_google_api_key(agent: Any, api_key: Optional[str]) -> bool:
    """Inject ``api_key`` into a constructed, unconfigured agent's LLM kwargs.

    Rebinds ``agent._llm_kwargs`` to a NEW dict rather than mutating it. The
    existing dict is the very object held by ``AgentDefinition.config["llm_kwargs"]``
    (``abstract.py:516`` assigns by reference), which is persisted to Redis and
    returned by ``GET /api/v1/crew`` — mutating it would leak the credential.

    Must be called after the agent is constructed and before ``configure()``.
    An agent that builds its client inside ``__init__``, or that overrides
    ``configure()`` to ignore ``_llm_kwargs``, will not pick the key up.

    Args:
        agent: A constructed, not-yet-configured agent. Non-``AbstractBot``
            objects are a no-op.
        api_key: The credential to inject. Falsy values are a no-op.

    Returns:
        ``True`` when the key was injected, ``False`` otherwise.
    """
    if not api_key:
        return False
    if not hasattr(agent, "_llm_raw") or not hasattr(agent, "_llm_kwargs"):
        return False
    if not is_google_llm(getattr(agent, "_llm_raw", None), getattr(agent, "_default_llm", "google")):
        return False
    llm_kwargs = getattr(agent, "_llm_kwargs", None) or {}
    if any(llm_kwargs.get(key) for key in _CREDENTIAL_KWARGS):
        return False
    if llm_kwargs.get("vertexai"):
        return False
    agent._llm_kwargs = {**llm_kwargs, "api_key": api_key}
    logger.debug("Injected CREW_AI_KEY into agent's Google llm_kwargs")
    return True
