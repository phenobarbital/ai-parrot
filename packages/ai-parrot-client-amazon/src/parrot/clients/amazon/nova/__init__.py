"""Amazon Nova client subpackage (FEAT-315).

``NovaClient`` unifies all Amazon Nova modalities (text, voice, image,
video) behind a single client — see :mod:`.client` for the full design.
"""
from __future__ import annotations

from .client import NovaClient
from .mantle import BedrockMantleClient

__all__ = ["BedrockMantleClient", "NovaClient"]
