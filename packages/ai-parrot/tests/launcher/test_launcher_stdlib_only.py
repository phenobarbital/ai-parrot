"""parrot.launcher must import only the stdlib (spec §3 M1 hard rule, §5 AC3)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

ALLOWED_PARROT = {"parrot", "parrot.version", "parrot.launcher"}
PROBE = (
    "import sys, json\n"
    "before = set(sys.modules)\n"
    "import parrot.launcher\n"
    "print(json.dumps(sorted(set(sys.modules) - before)))\n"
)


def test_launcher_stdlib_only():
    out = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True,
                         env=dict(os.environ), check=True, timeout=60).stdout
    loaded = json.loads(out)
    parrot_mods = {m for m in loaded if m == "parrot" or m.startswith("parrot.")}
    assert parrot_mods <= ALLOWED_PARROT, parrot_mods - ALLOWED_PARROT
    foreign = {m.split(".")[0] for m in loaded} - set(sys.stdlib_module_names) - {"parrot"}
    assert not foreign, foreign
