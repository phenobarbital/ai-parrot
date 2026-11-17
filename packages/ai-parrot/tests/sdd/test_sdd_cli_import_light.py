"""Regression for issue:223ed66c9482 — ``parrot.sdd.cli`` must stay import-light (no navconfig bootstrap)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from click.testing import CliRunner

from parrot.sdd.cli import sdd


def test_importing_sdd_cli_does_not_load_parrot_bots_or_experts(tmp_path: Path) -> None:
    """A fresh interpreter importing ``parrot.sdd.cli`` must not pull in ``parrot.bots``/``parrot.experts``."""
    code = textwrap.dedent("""
        import sys
        import parrot.sdd.cli  # noqa: F401
        bad = sorted(m for m in ("parrot.bots", "parrot.experts", "navconfig") if m in sys.modules)
        print("LOADED:" + ",".join(bad))
        """)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "LOADED:", proc.stdout


def test_experts_group_still_resolves_lazily() -> None:
    """The lazily mounted ``experts`` group still exposes its subcommands."""
    result = CliRunner().invoke(sdd, ["experts", "--help"])
    assert result.exit_code == 0, result.output
    for name in ("consult", "triage", "promote"):
        assert name in result.output
