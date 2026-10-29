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
