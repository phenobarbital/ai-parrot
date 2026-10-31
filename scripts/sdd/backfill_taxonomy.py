"""Compatibility shim — moved to ``parrot.sdd.scripts.backfill_taxonomy`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import backfill_taxonomy as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
