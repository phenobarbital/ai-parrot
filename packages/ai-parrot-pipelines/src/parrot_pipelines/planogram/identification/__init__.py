"""Identification stage of the planogram cycle: vision adapter, strategies, fallback detector, verification."""

from .vision import VisionAdapter, VisionError, cache_key, encode_png, normalise_kwargs

__all__ = ["VisionAdapter", "VisionError", "cache_key", "encode_png", "normalise_kwargs"]
