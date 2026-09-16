"""`parrot.bots.flows` must import when tqdm is unavailable (FEAT-562 Module 1).

`crew/crew.py` used to do a module-level `from tqdm.asyncio import tqdm`, so an
environment without tqdm could not import `parrot.bots.flows` — nor anything
that transitively imports it, which is most of the package. tqdm is a declared
dependency again, but the guard is what keeps a stripped or partially-installed
environment degrading to the plain iterator instead of failing at import time.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

#: Run in a child interpreter so the blocked module never leaks into this
#: session, and no module reload re-runs crew.py's registration side effects.
#: Only `tqdm.asyncio` is blocked (a `None` entry in ``sys.modules`` makes the
#: `from` import raise, exactly as an absent tqdm does): blocking the whole
#: `tqdm` package would also break unrelated third-party imports in the same
#: chain, which would test the wrong thing.
_CHILD = textwrap.dedent(
    """
    import sys

    sys.modules["tqdm.asyncio"] = None

    from parrot.bots.flows.crew import crew

    assert crew.async_tqdm is None, f"expected the guard to bind None, got {crew.async_tqdm!r}"

    from parrot.bots.flows import AgentCrew  # the import that used to explode

    assert AgentCrew is not None
    print("OK")
    """
)


def test_flows_import_without_tqdm_asyncio() -> None:
    """The package imports and `async_tqdm` degrades to None."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(path for path in sys.path if path)}
    result = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "OK" in result.stdout


def test_progress_bar_call_site_is_guarded() -> None:
    """The one `async_tqdm(...)` call site never runs with the None sentinel.

    A source-level check on purpose: reaching the real call site means driving
    `_generate_executive_summary` through live LLM calls, and the invariant that
    actually matters is narrow — every use of the sentinel is gated on it.
    """
    #: tests/bots/flows/crew -> tests/bots/flows -> tests/bots -> tests -> ai-parrot
    crew_py = Path(__file__).resolve().parents[4] / "src" / "parrot" / "bots" / "flows" / "crew" / "crew.py"
    lines = crew_py.read_text(encoding="utf-8").splitlines()

    call_sites = [i for i, line in enumerate(lines) if "async_tqdm(" in line]
    assert call_sites, "no async_tqdm call site found — has the progress bar moved?"
    for i in call_sites:
        preceding = lines[i - 1]
        assert "async_tqdm is not None" in preceding, f"unguarded async_tqdm call site at crew.py:{i + 1}"
