"""Compatibility shim — moved to ``parrot.sdd.scripts.review_checkpoint`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import review_checkpoint as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
