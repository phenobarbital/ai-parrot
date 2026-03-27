from enum import Enum


class ClaudeModel(Enum):
    """Enum for Claude models.

    Aliases (no date suffix) always resolve to the latest version of that
    model family and may change as Anthropic releases updates.  Dated
    variants are pinned and will never change behaviour.
    """

    # ── Claude 4.6 (Feb 2026) ────────────────────────────────────────────────
    OPUS_4_6 = "claude-opus-4-6"           # alias → latest Opus 4.6
    SONNET_4_6 = "claude-sonnet-4-6"       # alias → latest Sonnet 4.6

    # ── Claude 4.5 (Oct–Nov 2025) ────────────────────────────────────────────
    OPUS_4_5 = "claude-opus-4-5-20251101"
    HAIKU_4_5 = "claude-haiku-4-5-20251001"
    SONNET_4_5 = "claude-sonnet-4-5-20250929"

    # ── Claude 4.1 / 4.0 (May–Aug 2025) ─────────────────────────────────────
    OPUS_4_1 = "claude-opus-4-1-20250805"
    OPUS_4_1_ALIAS = "claude-opus-4-1"     # alias → latest Opus 4.1
    SONNET_4 = "claude-sonnet-4-20250514"

    # ── Claude 3.x (still valid) ─────────────────────────────────────────────
    SONNET_3_7 = "claude-3-7-sonnet-20250219"
    HAIKU_3_5 = "claude-3-5-haiku-20241022"
