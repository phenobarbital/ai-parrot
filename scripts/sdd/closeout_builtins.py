"""Compatibility shim — moved to ``parrot.sdd.scripts.closeout_builtins`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import closeout_builtins as _impl

sys.modules[__name__] = _impl
