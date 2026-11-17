"""Compatibility shim — moved to ``parrot.sdd.scripts.brief_meta`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import brief_meta as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
