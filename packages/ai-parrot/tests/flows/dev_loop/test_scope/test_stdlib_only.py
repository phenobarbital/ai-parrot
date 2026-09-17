"""AC3: the test-scope kernel core imports with the standard library only."""

import subprocess
import sys
from pathlib import Path

import parrot.flows.dev_loop as dev_loop


def test_core_is_stdlib_only():
    """AC3: importable by path under an isolated interpreter without site-packages."""
    dl = str(Path(dev_loop.__file__).parent)
    code = (
        "import sys; sys.path.insert(0, %r); import test_scope; "
        "assert 'pydantic' not in sys.modules; assert 'parrot' not in sys.modules" % dl
    )
    proc = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
