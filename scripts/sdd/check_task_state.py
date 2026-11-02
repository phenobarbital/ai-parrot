"""Compatibility shim — moved to ``parrot.sdd.scripts.check_task_state`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import check_task_state as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
