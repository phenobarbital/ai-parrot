"""Compatibility shim — moved to ``parrot.sdd.scripts.doc_taxonomy`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import doc_taxonomy as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
