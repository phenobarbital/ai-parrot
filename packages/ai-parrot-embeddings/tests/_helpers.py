"""Helpers for tests that simulate the satellite being absent."""
import subprocess
import sys
from pathlib import Path


def run_in_pruned_venv(snippet: str) -> tuple[int, str, str]:
    """Run a Python snippet with PYTHONPATH excluding the satellite's src/.

    Approach: filter out the satellite's workspace src/ directory from
    the current sys.path so that Python cannot find the satellite's modules,
    simulating the state where only ai-parrot (not ai-parrot-embeddings)
    is installed.

    Args:
        snippet: Python source code to run.

    Returns:
        Tuple of (returncode, stdout, stderr).
    """
    satellite_src = (
        Path(__file__).parent.parent / "src"
    ).resolve()

    # Filter out the satellite's src from the current sys.path
    pruned = [
        p for p in sys.path
        if str(satellite_src) not in p and "ai-parrot-embeddings" not in p
    ]
    env_path = ":".join(pruned)

    import os
    env = {**os.environ, "PYTHONPATH": env_path}

    result = subprocess.run(
        [sys.executable, "-c", snippet],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr
