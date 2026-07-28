"""Codec implementations for the tool-result compression pipeline.

Individual codec modules (e.g. ``json_compact``, ``columnar``) register
themselves against :func:`parrot.tools.compression.register_codec` as an
import side effect. Importing this package imports all built-in codecs.
"""
from . import columnar, json_compact  # noqa: F401 — import side effect: registration

__all__: list[str] = []
