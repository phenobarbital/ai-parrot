"""Compatibility shim — moved to ``parrot.sdd.scripts.close_resolved_issues`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import close_resolved_issues as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
