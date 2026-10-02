"""Opt-in fixtures for the planogram live E2E cases (FEAT-612, spec Module 14 / §4 Live E2E behavior).

Nothing here runs without ``PARROT_TEST_REAL_LLM=1`` and ``PLANOGRAM_E2E_MANIFEST``; every missing
prerequisite is an explicit skip taken before any provider client is created.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from os.path import expanduser
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from models import LiveCase  # annotation only; runtime loading goes through conftest

_HERE = Path(__file__).resolve().parent
HARNESS_MODULE = "planogram_e2e_runner"
LIVE_CASE_IDS = ("shelves", "ink-wall", "backlit-endcap")


def _load_runner() -> ModuleType:
    """Load ``runner.py`` by path under a unique module name (reused if already loaded)."""
    if HARNESS_MODULE in sys.modules:
        return sys.modules[HARNESS_MODULE]
    path = _HERE / "runner.py"
    spec = importlib.util.spec_from_file_location(HARNESS_MODULE, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[HARNESS_MODULE] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def harness() -> Iterator[ModuleType]:
    """The runner module; popped from sys.modules at session end."""
    module = _load_runner()
    try:
        yield module
    finally:
        sys.modules.pop(HARNESS_MODULE, None)


@pytest.fixture(scope="session")
def live_manifest(harness: ModuleType) -> Any:
    """Validated manifest, or an explicit skip when the run is not opted in / not configured."""
    if not harness.opt_in_enabled(os.environ):
        pytest.skip("Set PARROT_TEST_REAL_LLM=1 to run live planogram E2E tests")
    manifest_path = os.environ.get(harness.MANIFEST_ENV, "").strip()
    if not manifest_path:
        pytest.skip(f"Set {harness.MANIFEST_ENV} to point to a manifest JSON file")
    manifest_path = Path(expanduser(manifest_path))
    if not manifest_path.is_file():
        pytest.skip(f"Manifest file not found: {manifest_path}")
    return harness.load_manifest(manifest_path)


@pytest.fixture(params=LIVE_CASE_IDS)
def case(request: pytest.FixtureRequest, harness: ModuleType, live_manifest: Any) -> Any:
    """The configured LiveCase for this case id, or a skip naming what is missing."""
    manifest_case = None
    for c in live_manifest.cases:
        if c.case_id == request.param:
            manifest_case = c
            break
    if manifest_case is None:
        pytest.skip(f"case {request.param!r} is not configured in the manifest")
    reasons = harness.missing_prerequisites(manifest_case, live_manifest, os.environ)
    if reasons:
        pytest.skip("; ".join(reasons))
    return manifest_case
