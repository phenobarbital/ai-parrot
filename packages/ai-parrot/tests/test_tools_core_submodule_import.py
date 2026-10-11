"""``from parrot.tools import <core submodule>`` must work in a fresh interpreter (P4 integration fix).

The package ``__getattr__`` raised ``ImportError`` for a core submodule that had not been imported yet, so a host that
did ``from parrot.tools import exports_mode`` before anything else imported it (the service's G2 boot probe) failed.
"""

import subprocess
import sys


def test_core_submodule_from_import_in_fresh_interpreter():
    code = "from parrot.tools import exports_mode; print(exports_mode.is_enabled())"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip().endswith("False")
