"""Grok (xAI) model catalogue (FEAT-523 folder convention, TASK-2844).

``GrokModel`` relocated byte-identical from ``clients/grok.py:39``. Pure
data — no I/O, no imports from ``client.py``.
"""

from enum import Enum


class GrokModel(str, Enum):
    """Grok model versions (xAI API, July 2026)."""

    GROK_4_3 = "grok-4.3"
    GROK_4_20 = "grok-4.20"
    GROK_4_20_NON_REASONING = "grok-4.20-non-reasoning"
    GROK_4_20_REASONING = "grok-4.20-reasoning"
    GROK_4_20_MULTI_AGENT = "grok-4.20-multi-agent"
    GROK_BUILD_0_1 = "grok-build-0.1"
    GROK_CODE_FAST_1 = "grok-code-fast-1"
    GROK_IMAGINE_IMAGE = "grok-imagine-image"
    GROK_IMAGINE_IMAGE_QUALITY = "grok-imagine-image-quality"
    GROK_IMAGINE_VIDEO = "grok-imagine-video"


__all__ = ["GrokModel"]
