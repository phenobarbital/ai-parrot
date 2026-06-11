"""Backward-compatibility shim.

The text splitters now live in ai-parrot **core**
(:mod:`parrot.loaders.splitters`) to break the circular dependency:
``ai-parrot-loaders`` depends on ``ai-parrot``, so core must not import
from ``parrot_loaders``. This module re-exports the core implementations
so existing imports keep working:

    from parrot_loaders.splitters import TokenTextSplitter        # ok
    from parrot_loaders.splitters.base import BaseTextSplitter    # ok
"""
import sys as _sys

from parrot.loaders.splitters import (
    base as _base,
    md as _md,
    token as _token,
    semantic as _semantic,
)
from parrot.loaders.splitters import (
    BaseTextSplitter,
    MarkdownTextSplitter,
    TokenTextSplitter,
    SemanticTextSplitter,
)

# Alias the submodules so ``parrot_loaders.splitters.<name>`` resolves to the
# real core modules (same module objects, not copies).
_sys.modules[__name__ + '.base'] = _base
_sys.modules[__name__ + '.md'] = _md
_sys.modules[__name__ + '.token'] = _token
_sys.modules[__name__ + '.semantic'] = _semantic

__all__ = (
    'BaseTextSplitter',
    'MarkdownTextSplitter',
    'TokenTextSplitter',
    'SemanticTextSplitter',
)
