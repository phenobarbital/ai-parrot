"""Deterministic experience-memory launcher regression tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

from parrot.sdd.scripts import experience_hook


def test_launcher_fast_path_stdlib_only(tmp_path: Path) -> None:
    """Verify launcher fast path stdlib only."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    source_root = Path(__file__).resolve().parents[2] / "src"
    script = (
        "import json, sys; "
        f"sys.path.insert(0, {str(source_root)!r}); "
        "from parrot.launcher import main_parrot; "
        "sys.argv = ['parrot', 'sdd', 'experience', 'hook', '--host', 'claude', '--event', 'post']; "
        "main_parrot(); "
        "print(json.dumps({'click': 'click' in sys.modules, 'pydantic': 'pydantic' in sys.modules}))"
    )
    environment = dict(os.environ)
    environment["PARROT_LAUNCHER_RESOLVED"] = "1"
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=root,
        env=environment,
        input="{}",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout.splitlines()[-1]) == {"click": False, "pydantic": False}


def test_success_hook_under_latency_budget(tmp_path: Path) -> None:
    """Verify success hook under latency budget."""
    plane = tmp_path / "plane"
    plane.mkdir()
    payload = {
        "session_id": "latency",
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr list"},
        "tool_use_id": "call-latency",
    }
    elapsed: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        assert experience_hook.handle_post(payload, host="claude", event="post", plane_dir=plane) is None
        elapsed.append(time.perf_counter() - started)

    assert statistics.median(elapsed) < 0.05
