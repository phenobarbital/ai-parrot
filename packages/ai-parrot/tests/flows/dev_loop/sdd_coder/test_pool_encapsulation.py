"""FEAT-599 / issue:700660c7f663: `engine.py` must use `ExecutionPool`'s public API only.

Reaching into the pool's private state let a `str`-for-`RosterSeat` bug through
(commit 84ede6b60). This guard fails the moment a new `pool._<name>` access or a
local `_effective_key` import creeps back into the engine.
"""

from __future__ import annotations

import re
from pathlib import Path

import parrot.flows.dev_loop.sdd_coder.engine as engine_module
from parrot.flows.dev_loop.sdd_coder.pool import ExecutionPool, _effective_key, effective_key


def test_engine_has_no_private_pool_access() -> None:
    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    offenders = [m.group(0) for m in re.finditer(r"\bpool\._[a-z_]+", source)]
    assert offenders == [], offenders
    assert "_effective_key" not in source


def test_public_api_surface_exists() -> None:
    for name in (
        "status",
        "seats",
        "persistence_degraded",
        "resolve_admission",
        "restore_local_exclusions",
        "require_fallback",
        "set_persistence_degraded",
        "mark_exhausted",
        "select_free_seat",
        "close",
        "mark_recovery_required",
    ):
        assert hasattr(ExecutionPool, name), name
    assert _effective_key is effective_key  # compatibility alias kept for older tests
