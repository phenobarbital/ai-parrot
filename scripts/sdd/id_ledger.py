"""Compatibility shim — moved to ``parrot.sdd.scripts.id_ledger`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import id_ledger as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
