"""Make the repository-root ``artifacts`` namespace importable for the Laya evaluation tests."""
from __future__ import annotations

import sys
from pathlib import Path

# conftest.py -> laya_eval -> unit -> tests -> ai-parrot -> packages -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
