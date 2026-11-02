"""Compatibility shim — moved to ``parrot.sdd.scripts.prune_intake`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import prune_intake as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
