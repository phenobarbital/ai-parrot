"""Compatibility shim — moved to ``parrot.sdd.scripts.test_report`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import test_report as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
