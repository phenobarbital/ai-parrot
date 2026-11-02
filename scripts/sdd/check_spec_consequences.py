"""Compatibility shim — moved to ``parrot.sdd.scripts.check_spec_consequences`` (FEAT-633, C30)."""
import sys

from parrot.sdd.scripts import check_spec_consequences as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
