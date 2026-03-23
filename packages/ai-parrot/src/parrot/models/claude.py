from enum import Enum


class ClaudeModel(Enum):
    """Enum for Claude models."""
    OPUS_4_6 = "claude-opus-4-6"
    SONNET_4 = "claude-sonnet-4-20250514"
    SONNET_4_5 = "claude-sonnet-4-5-20250929"
    OPUS_4 = "claude-opus-4-1-20250805"
    OPUS_4_5 = "claude-opus-4-5-20251101"
    OPUS_4_1 = "claude-opus-4-1"
    SONNET_3_7 = "claude-3-7-sonnet-20250219"
    HAIKU_3_5 = "claude-3-5-haiku-20241022"
    HAIKU_4_5 = "claude-haiku-4-5-20251001"
