"""FEAT-633 R9: the dev_loop and sdd_coder packages resolve their public names lazily (PEP 562).

The shipped SDD helpers (``finalize_task``, ``review_checkpoint``) import a few ``sdd_coder`` submodules. With eager
package ``__init__`` files those imports pulled in the runner and the roster, and with them navconfig, which aborts in
any repository without navconfig's ``env/<env>/.env`` tree (credentials live there; a foreign repo has none).
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGES = ("parrot.flows.dev_loop", "parrot.flows.dev_loop.sdd_coder")
HEAVY = ("parrot.flows.dev_loop.runner", "parrot.flows.dev_loop.commands", "parrot.flows.dev_loop.sdd_coder.roster",
         "parrot.flows.dev_loop.sdd_coder.engine", "parrot.conf")
HELPERS = ("parrot.sdd.scripts.finalize_task", "parrot.sdd.scripts.review_checkpoint")


@pytest.mark.parametrize("package", PACKAGES)
def test_every_public_name_resolves(package: str) -> None:
    module = importlib.import_module(package)
    for name in module.__all__:
        assert getattr(module, name) is not None, name
        assert name in dir(module), name


@pytest.mark.parametrize("package", PACKAGES)
def test_unknown_name_raises_attribute_error(package: str) -> None:
    with pytest.raises(AttributeError):
        getattr(importlib.import_module(package), "NoSuchExport")


def test_helpers_import_without_navconfig_env(tmp_path: Path) -> None:
    """In a fresh interpreter whose navconfig root has no ``env/`` tree, the helpers import and stay light."""
    probe = (
        "import sys\n"
        f"for m in {HELPERS!r}: __import__(m)\n"
        f"loaded = [m for m in {HEAVY!r} if m in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    env = {**os.environ, "SITE_ROOT": str(tmp_path)}
    result = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]


def test_export_sets_are_pinned() -> None:
    """The lazy tables keep exactly the names the eager ``__init__`` files exported (72 + 31)."""
    dev_loop = importlib.import_module("parrot.flows.dev_loop")
    sdd_coder = importlib.import_module("parrot.flows.dev_loop.sdd_coder")
    assert len(dev_loop.__all__) == len(set(dev_loop.__all__)) == 72
    assert len(sdd_coder.__all__) == len(set(sdd_coder.__all__)) == 31
    assert set(dev_loop.__all__) == set(dev_loop._LAZY_EXPORTS)
    assert set(sdd_coder.__all__) == set(sdd_coder._LAZY_EXPORTS)


#: Modules on known import cycles. The eager ``__init__`` always entered ``dispatchers`` first, which masked
#: the ``code_review`` <-> ``dispatchers.mantle`` cycle; each must import cleanly as the FIRST dev_loop import.
#: (A full scan of all 115 dev_loop submodules passed when the packages went lazy; too slow for every run.)
FIRST_IMPORTS = (
    "parrot.flows.dev_loop.code_review",
    "parrot.flows.dev_loop.nodes.qa",
    "parrot.flows.dev_loop.dispatchers",
    "parrot.flows.dev_loop.dispatchers.mantle",
    "parrot.flows.dev_loop.runner",
    "parrot.flows.dev_loop.commands",
    "parrot.flows.dev_loop.flow",
    "parrot.flows.dev_loop.factories",
    "parrot.flows.dev_loop.sdd_coder.engine",
    "parrot.flows.dev_loop.sdd_coder.toolkit",
)


def test_cycle_modules_import_first_in_a_fresh_interpreter() -> None:
    from concurrent.futures import ThreadPoolExecutor

    def probe(module: str) -> tuple[str, int, str]:
        result = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, timeout=120)
        return module, result.returncode, (result.stderr.strip().splitlines() or [""])[-1]

    with ThreadPoolExecutor(max_workers=5) as pool:
        failures = [r for r in pool.map(probe, FIRST_IMPORTS) if r[1] != 0]
    assert not failures, failures
