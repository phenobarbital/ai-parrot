"""Compatibility shim — moved to ``parrot.sdd.scripts.finalize_task`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import finalize_task as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
