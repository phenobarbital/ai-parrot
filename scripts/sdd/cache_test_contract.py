"""Compatibility shim — moved to ``parrot.sdd.scripts.cache_test_contract`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import cache_test_contract as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
