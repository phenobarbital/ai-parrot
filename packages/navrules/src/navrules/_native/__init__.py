"""Native (Rust) backend shim.

Follows the querysource ``qs_parsers`` pattern: try the packaged extension,
then a top-level module (``maturin develop`` layout), else fall back to pure
Python with ``HAS_RUST = False``. The environment variable
``NAVRULES_DISABLE_RUST=1`` forces the fallback (used by the parity suite).
"""
from __future__ import annotations

import os

HAS_RUST = False

if os.environ.get("NAVRULES_DISABLE_RUST", "") != "1":
    try:
        from ._navrules import *  # noqa: F401,F403 - wheel layout
        from ._navrules import compile_ruleset  # noqa: F401

        HAS_RUST = True
    except ImportError:
        try:
            from _navrules import *  # noqa: F401,F403 - maturin develop layout
            from _navrules import compile_ruleset  # noqa: F401

            HAS_RUST = True
        except ImportError:
            HAS_RUST = False
