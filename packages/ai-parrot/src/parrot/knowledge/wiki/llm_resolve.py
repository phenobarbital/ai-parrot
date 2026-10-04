"""Lazy optional wiki model resolution without CLI/store import dependencies."""

from collections.abc import Sequence
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter


def _env_setting(name: str) -> str | None:
    """Read a setting from navconfig (honours ``.env``), falling back to ``os.environ``.

    Args:
        name: Setting name.

    Returns:
        The non-empty value, or ``None``.
    """
    try:
        from navconfig import config as _nav

        value = _nav.get(name, fallback=None)
    except Exception:  # noqa: BLE001 — navconfig optional; env is enough
        import os

        value = os.environ.get(name)
    return value or None


def resolve_optional_llm(
    env_names: Sequence[str],
    *,
    purpose: str,
    logger: logging.Logger,
) -> "PageIndexLLMAdapter | None":
    """Resolve explicit environment settings or allowed CLI detection, fail safely.

    The first non-empty setting in ``env_names`` wins. Otherwise a coding-agent CLI
    is auto-detected unless ``PARROT_NO_AUTO_LLM`` is set. Heavy imports happen lazily
    inside this function. Any failure returns ``None`` after a logged diagnostic that
    never includes the raw exception text (it may carry credentials).

    Args:
        env_names: Setting names to consult in order.
        purpose: Short description used in diagnostics.
        logger: Logger receiving diagnostics.

    Returns:
        A ready adapter, or ``None`` when no model is available.
    """
    spec: str | None = None
    for name in env_names:
        spec = _env_setting(name)
        if spec:
            break
    if not spec and not _env_setting("PARROT_NO_AUTO_LLM"):
        try:
            from parrot.clients.detection import detect_coding_agent_llm

            spec = detect_coding_agent_llm()
        except Exception as exc:  # noqa: BLE001 — detection is best-effort
            logger.warning("LLM auto-detection failed for %s (%s)", purpose, type(exc).__name__)
            spec = None
    if not spec:
        logger.info("No model configured for %s; running without one", purpose)
        return None
    try:
        from parrot.clients.factory import LLMFactory
        from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

        _, model_id = LLMFactory.parse_llm_string(spec)
        client = LLMFactory.create(spec, model_args={"temperature": 0.0})
        return PageIndexLLMAdapter(client, model=model_id)
    except Exception as exc:  # noqa: BLE001 — degrade, never crash
        logger.warning("Could not build model for %s (%s)", purpose, type(exc).__name__)
        return None
