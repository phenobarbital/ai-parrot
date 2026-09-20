"""Deterministic perception building blocks of the planogram cycle (FEAT-574)."""

from .profiles import PRICE_TAG_PROFILE, ShapeCandidate, ShapeProfile
from .shapes import propose_shapes

__all__ = ["PRICE_TAG_PROFILE", "ShapeCandidate", "ShapeProfile", "propose_shapes"]
