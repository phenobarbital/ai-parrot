"""Compatibility shim — moved to ``parrot.sdd.scripts.select_tests`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import select_tests as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
