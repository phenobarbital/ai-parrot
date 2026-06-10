"""OpenAI model catalog and deprecation registry.

This module defines:
- ``OpenAIModel`` — current upstream catalog (deprecated IDs removed).
- ``DeprecationInfo`` — structured metadata for each deprecated model.
- ``DEPRECATIONS`` — registry of deprecated model IDs.
- Helper functions: ``is_deprecated``, ``get_shutoff_date``, ``resolve_alias``.
"""

from datetime import date
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field


class OpenAIModel(Enum):
    """Current OpenAI model catalog (deprecated IDs removed — see DEPRECATIONS)."""

    # gpt-5 family
    GPT5_5 = "gpt-5.5"
    GPT5_5_PRO = "gpt-5.5-pro"
    GPT5_4 = "gpt-5.4"
    GPT5_4_PRO = "gpt-5.4-pro"
    GPT5_4_MINI = "gpt-5.4-mini"
    GPT5_4_NANO = "gpt-5.4-nano"
    GPT5_3_CODEX = "gpt-5.3-codex"
    GPT5_2 = "gpt-5.2"
    GPT5_2_PRO = "gpt-5.2-pro"
    GPT5_1 = "gpt-5.1"
    GPT5 = "gpt-5"
    GPT5_PRO = "gpt-5-pro"
    GPT5_MINI = "gpt-5-mini"
    GPT5_NANO = "gpt-5-nano"
    CHAT_LATEST = "chat-latest"

    # gpt-4 family (only what the upstream catalog lists as current)
    GPT4_1 = "gpt-4.1"
    GPT4_1_MINI = "gpt-4.1-mini"
    GPT4O_MINI = "gpt-4o-mini"

    # reasoning
    O3 = "o3"
    O3_PRO = "o3-pro"

    # realtime + audio
    GPT_REALTIME_2 = "gpt-realtime-2"
    GPT_REALTIME_TRANSLATE = "gpt-realtime-translate"
    GPT_REALTIME_WHISPER = "gpt-realtime-whisper"
    GPT_REALTIME = "gpt-realtime"
    GPT_REALTIME_1_5 = "gpt-realtime-1.5"
    GPT_AUDIO = "gpt-audio"
    GPT_AUDIO_1_5 = "gpt-audio-1.5"

    # image
    GPT_IMAGE_2 = "gpt-image-2"


class DeprecationInfo(BaseModel):
    """Structured deprecation metadata for a single OpenAI model ID."""

    shutoff: date = Field(..., description="API shutoff date (UTC).")
    ft_shutoff: Optional[date] = Field(
        default=None,
        description="Fine-tuning shutoff date when distinct from API shutoff.",
    )
    alias: Optional[str] = Field(
        default=None,
        description=(
            "Public alias under which this dated model is sold " "(e.g. 'gpt-4-turbo' for 'gpt-4-turbo-2024-04-09')."
        ),
    )


DEPRECATIONS: dict[str, DeprecationInfo] = {
    # shutoff 2026-10-23
    "gpt-3.5-turbo-0125": DeprecationInfo(shutoff=date(2026, 10, 23), ft_shutoff=date(2026, 10, 23)),
    "gpt-4-0613": DeprecationInfo(shutoff=date(2026, 10, 23), ft_shutoff=date(2026, 10, 23), alias="gpt-4"),
    "gpt-4-1106-preview": DeprecationInfo(shutoff=date(2026, 10, 23), ft_shutoff=date(2026, 10, 23)),
    "gpt-4-turbo-2024-04-09": DeprecationInfo(shutoff=date(2026, 10, 23), alias="gpt-4-turbo"),
    "gpt-4.1-nano-2025-04-14": DeprecationInfo(
        shutoff=date(2026, 10, 23), ft_shutoff=date(2026, 10, 23), alias="gpt-4.1-nano"
    ),
    "gpt-4o-2024-05-13": DeprecationInfo(shutoff=date(2026, 10, 23), alias="gpt-4o"),
    "gpt-image-1": DeprecationInfo(shutoff=date(2026, 10, 23)),
    "o1-2024-12-17": DeprecationInfo(shutoff=date(2026, 10, 23)),
    "o1-pro-2025-03-19": DeprecationInfo(shutoff=date(2026, 10, 23)),
    "o3-mini-2025-01-31": DeprecationInfo(shutoff=date(2026, 10, 23)),
    "o4-mini-2025-04-16": DeprecationInfo(shutoff=date(2026, 10, 23), ft_shutoff=date(2026, 10, 23)),
    # shutoff 2026-09-28
    "gpt-3.5-turbo-instruct": DeprecationInfo(shutoff=date(2026, 9, 28)),
    "babbage-002": DeprecationInfo(shutoff=date(2026, 9, 28), ft_shutoff=date(2026, 10, 23)),
    "davinci-002": DeprecationInfo(shutoff=date(2026, 9, 28), ft_shutoff=date(2026, 10, 23)),
    "gpt-3.5-turbo-1106": DeprecationInfo(shutoff=date(2026, 9, 28), ft_shutoff=date(2026, 10, 23)),
    # shutoff 2026-07-23
    "computer-use-preview-2025-03-11": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-4o-audio-preview-2024-12-17": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-4o-mini-audio-preview-2024-12-17": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-4o-mini-realtime-preview-2024-12-17": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-4o-mini-search-preview-2025-03-11": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-4o-mini-tts-2025-03-20": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-4o-search-preview-2025-03-11": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-5-chat-latest": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-5-codex": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-5.1-chat-latest": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-5.1-codex": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-5.1-codex-max": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-5.1-codex-mini": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-5.2-codex": DeprecationInfo(shutoff=date(2026, 7, 23)),
    # shutoff 2026-08-10
    "gpt-5.2-chat-latest": DeprecationInfo(shutoff=date(2026, 8, 10)),
    "gpt-5.3-chat-latest": DeprecationInfo(shutoff=date(2026, 8, 10)),
    # shutoff 2026-12-01
    "gpt-image-1.5": DeprecationInfo(shutoff=date(2026, 12, 1), alias="gpt-image-1.5"),
    "gpt-image-1-mini": DeprecationInfo(shutoff=date(2026, 12, 1), alias="gpt-image-1-mini"),
    "chatgpt-image-latest": DeprecationInfo(shutoff=date(2026, 12, 1)),
    "gpt-audio-mini-2025-10-06": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "gpt-realtime-mini-2025-10-06": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "o3-deep-research-2025-06-26": DeprecationInfo(shutoff=date(2026, 7, 23)),
    "o4-mini-deep-research-2025-06-26": DeprecationInfo(shutoff=date(2026, 7, 23)),
    # shutoff 2026-03-26
    "gpt-4-0314": DeprecationInfo(shutoff=date(2026, 3, 26)),
    "gpt-4-0125-preview": DeprecationInfo(shutoff=date(2026, 3, 26), alias="gpt-4-turbo-preview"),
    # shutoff 2026-03-24
    "gpt-4o-audio-preview-2025-06-03": DeprecationInfo(shutoff=date(2026, 3, 24)),
    "gpt-4o-mini-audio-preview": DeprecationInfo(shutoff=date(2026, 3, 24)),
    # shutoff 2026-02-17
    "chatgpt-4o-latest": DeprecationInfo(shutoff=date(2026, 2, 17)),
    # shutoff 2026-01-16
    "codex-mini-latest": DeprecationInfo(shutoff=date(2026, 1, 16)),
    # shutoff 2025-10-27
    "o1-mini-2024-09-12": DeprecationInfo(shutoff=date(2025, 10, 27), alias="o1-mini"),
    # shutoff 2025-10-10
    "gpt-4o-audio-preview-2024-10-01": DeprecationInfo(shutoff=date(2025, 10, 10)),
    # shutoff 2025-07-28
    "o1-preview-2024-09-12": DeprecationInfo(shutoff=date(2025, 7, 28), alias="o1-preview"),
    # shutoff 2025-07-14
    "gpt-4.5-preview": DeprecationInfo(shutoff=date(2025, 7, 14)),
    # shutoff 2025-06-06
    "gpt-4-32k-0613": DeprecationInfo(shutoff=date(2025, 6, 6), alias="gpt-4-32k"),
    "gpt-4-32k-0314": DeprecationInfo(shutoff=date(2025, 6, 6)),
    # shutoff 2024-12-06
    "gpt-4-1106-vision-preview": DeprecationInfo(shutoff=date(2024, 12, 6), alias="gpt-4-vision-preview"),
    # shutoff 2024-09-13
    "gpt-3.5-turbo-0613": DeprecationInfo(shutoff=date(2024, 9, 13), ft_shutoff=date(2026, 10, 23)),
    "gpt-3.5-turbo-16k-0613": DeprecationInfo(shutoff=date(2024, 9, 13), ft_shutoff=date(2026, 10, 23)),
    "gpt-3.5-turbo-0301": DeprecationInfo(shutoff=date(2024, 9, 13)),
    # bare alias — shutoff matches the most-recent dated source (2026-10-23)
    "gpt-3.5-turbo": DeprecationInfo(shutoff=date(2026, 10, 23)),
}


def _coerce(model: Union[str, OpenAIModel]) -> str:
    """Coerce an OpenAIModel or str to a plain string."""
    return model.value if isinstance(model, OpenAIModel) else model


_CURRENT_VALUES: frozenset[str] = frozenset(m.value for m in OpenAIModel)


def is_deprecated(model: Union[str, OpenAIModel]) -> bool:
    """Return True if ``model`` is in DEPRECATIONS or matches an alias entry.

    An alias-match only counts as deprecated when the alias itself is NOT a
    current ``OpenAIModel`` value.

    Examples::

        is_deprecated("gpt-4-turbo-2024-04-09")  # True — direct key
        is_deprecated("gpt-4-turbo")              # True — alias of dead family
        is_deprecated("gpt-4.1-nano")             # True — deprecated alias
        is_deprecated("gpt-5-mini")               # False
        is_deprecated(OpenAIModel.GPT5_MINI)      # False
    """
    s = _coerce(model)
    if s in DEPRECATIONS:
        return True
    if s in _CURRENT_VALUES:
        return False
    return any(info.alias == s for info in DEPRECATIONS.values())


def get_shutoff_date(model: Union[str, OpenAIModel]) -> Optional[date]:
    """Return the API shutoff date for ``model``, or None if not deprecated.

    Resolves direct keys and alias strings, but ignores aliases that are
    themselves current ``OpenAIModel`` values.
    """
    s = _coerce(model)
    if s in DEPRECATIONS:
        return DEPRECATIONS[s].shutoff
    if s in _CURRENT_VALUES:
        return None
    for info in DEPRECATIONS.values():
        if info.alias == s:
            return info.shutoff
    return None


# Migration target per spec §8 Q3 — using interpretation (b).
# TODO(spec §8 Q3): contract may switch to canonical-alias semantics.
_MIGRATION_TARGET = "gpt-5-mini"


def resolve_alias(model: Union[str, OpenAIModel]) -> str:
    """Map a deprecated model ID to the recommended migration target.

    Per spec §8 Q3 — currently using interpretation (b): deprecated IDs
    are mapped to the new client-wide default ``gpt-5-mini``.
    Pass-through for non-deprecated IDs.

    TODO(spec §8 Q3): revisit if interpretation (a) (canonical-alias) is preferred.
    """
    s = _coerce(model)
    if is_deprecated(s):
        return _MIGRATION_TARGET
    return s


__all__ = [
    "OpenAIModel",
    "DeprecationInfo",
    "DEPRECATIONS",
    "is_deprecated",
    "get_shutoff_date",
    "resolve_alias",
]
