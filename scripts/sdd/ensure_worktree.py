"""Compatibility shim — moved to ``parrot.sdd.scripts.ensure_worktree`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import ensure_worktree as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
