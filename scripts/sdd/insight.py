#!/usr/bin/env python3
"""Compatibility shim — moved to ``parrot.sdd.scripts.insight`` (FEAT-633).

Still runnable as ``python3 scripts/sdd/insight.py`` with a bare interpreter: the module is stdlib-only, so when
``parrot`` is not importable the shim retries with this checkout's ``packages/ai-parrot/src`` on ``sys.path``.
"""
import sys
from pathlib import Path

try:
    from parrot.sdd.scripts import insight as _impl
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "ai-parrot" / "src"))
    from parrot.sdd.scripts import insight as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
