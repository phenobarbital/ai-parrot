"""Moved to :mod:`parrot.tools.optimizations.policy` (FEAT-633 C35); kept as an alias."""
import sys

from parrot.tools.optimizations import policy as _moved

sys.modules[__name__] = _moved
