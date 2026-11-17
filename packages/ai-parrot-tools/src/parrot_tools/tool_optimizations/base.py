"""Moved to :mod:`parrot.tools.optimizations.base` (FEAT-633 C35); kept as an alias."""
import sys

from parrot.tools.optimizations import base as _moved

sys.modules[__name__] = _moved
