"""Compatibility shim — moved to ``parrot.sdd.scripts.remove_worktree`` (FEAT-795); use ``parrot sdd worktree``."""

import sys

from parrot.sdd.scripts import remove_worktree as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
