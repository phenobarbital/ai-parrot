"""Compatibility shim — moved to ``parrot.sdd.scripts.worktree_status`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import worktree_status as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
