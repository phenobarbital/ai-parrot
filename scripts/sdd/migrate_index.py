"""Compatibility shim — moved to ``parrot.sdd.scripts.migrate_index`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import migrate_index as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
