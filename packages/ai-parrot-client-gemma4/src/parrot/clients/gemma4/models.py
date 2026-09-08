"""Gemma4 model catalogue (FEAT-523 folder convention, TASK-2845).

``Gemma4Model`` relocated byte-identical from ``clients/gemma4.py:38``.
Pure data — no I/O, no imports from ``client.py``.
"""

from enum import Enum


class Gemma4Model(Enum):
    """Supported Gemma 4 model variants."""

    GEMMA_4_E2B = "google/gemma-4-E2B-it"
    GEMMA_4_E4B = "google/gemma-4-E4B-it"
    GEMMA_4_26B_A4B = "google/gemma-4-26B-A4B-it"


__all__ = ["Gemma4Model"]
