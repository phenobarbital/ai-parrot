"""Unit tests for GVisorWorkerPool — FEAT-459 / TASK-3170.

ALL tests here use fake_gvisor_absent or otherwise avoid requiring a real
runsc binary — confirmed absent on the reference dev machine (spec §6).
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.services.sandbox.gvisor_pool import (
    GVisorUnavailableError,
    GVisorWorkerPool,
)


@pytest.fixture
def fake_gvisor_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force GVisorWorkerPool.is_available() to return False (spec §4)."""
    monkeypatch.setattr(GVisorWorkerPool, "is_available", classmethod(lambda cls: False))


@pytest.fixture
def fake_gvisor_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force is_available() True WITHOUT requiring a real runsc binary.

    Used only to test the constructor's happy path in isolation; acquire()/
    release() are NOT exercised under this fixture since they would need a
    real container runtime.
    """
    monkeypatch.setattr(GVisorWorkerPool, "is_available", classmethod(lambda cls: True))


def test_gvisor_pool_is_available_probe_reflects_shutil_which(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real (unmocked) is_available() correctly reports a missing runsc."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert GVisorWorkerPool.is_available() is False


def test_constructor_raises_when_gvisor_absent(fake_gvisor_absent: None) -> None:
    """Constructor raises GVisorUnavailableError when runsc is absent."""
    with pytest.raises(GVisorUnavailableError):
        GVisorWorkerPool()


def test_constructor_succeeds_when_gvisor_present(fake_gvisor_present: None) -> None:
    """Constructor succeeds when gVisor is available (mocked)."""
    pool = GVisorWorkerPool()
    assert pool._tier34_pool_size == 2
    assert pool._config.runtime == "runsc"
    assert pool._config.network == "none"


def test_tier34_pool_size_default_is_two(fake_gvisor_present: None) -> None:
    """tier34_pool_size defaults to 2 per spec OQ-6."""
    pool = GVisorWorkerPool()
    assert pool._tier34_pool_size == 2


def test_custom_tier34_pool_size(fake_gvisor_present: None) -> None:
    """Custom tier34_pool_size is respected."""
    pool = GVisorWorkerPool(tier34_pool_size=4)
    assert pool._tier34_pool_size == 4


def test_default_config_network_is_none(fake_gvisor_present: None) -> None:
    """Default SandboxConfig.network is 'none' per spec."""
    pool = GVisorWorkerPool()
    assert pool._config.network == "none"


def test_custom_config_is_used(fake_gvisor_present: None) -> None:
    """Custom SandboxConfig is used when provided."""
    from parrot_tools.sandboxtool import SandboxConfig

    custom_config = SandboxConfig(runtime="runsc", network="none", max_memory="4G")
    pool = GVisorWorkerPool(config=custom_config)
    assert pool._config.max_memory == "4G"


def test_pool_initializes_empty(fake_gvisor_present: None) -> None:
    """Pool initializes with zero workers."""
    pool = GVisorWorkerPool()
    assert pool._total_count == 0
    assert pool._active_count == 0
    assert len(pool._idle_workers) == 0


def test_pool_respects_max_queue_depth(fake_gvisor_present: None) -> None:
    """Pool respects max_queue_depth parameter."""
    pool = GVisorWorkerPool(max_queue_depth=16)
    assert pool._acquire_queue.maxsize == 16