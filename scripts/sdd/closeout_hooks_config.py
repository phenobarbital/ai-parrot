"""Compatibility shim — moved to ``parrot.sdd.scripts.closeout_hooks_config`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import closeout_hooks_config as _impl

sys.modules[__name__] = _impl
