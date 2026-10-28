"""Compatibility shim — moved to ``parrot.sdd.scripts.run_closeout_hooks`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import run_closeout_hooks as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
