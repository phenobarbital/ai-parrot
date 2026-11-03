"""Compatibility shim — moved to ``parrot.sdd.scripts.spec_tools`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import spec_tools as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
