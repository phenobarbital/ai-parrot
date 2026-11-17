"""Moved to :mod:`parrot.tools.optimizations.inspection_models` (FEAT-633 C35); kept as an alias."""
import sys

from parrot.tools.optimizations import inspection_models as _moved

sys.modules[__name__] = _moved
