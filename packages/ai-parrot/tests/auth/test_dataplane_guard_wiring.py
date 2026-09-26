"""Unit tests for parrot.auth.pbac.setup_dataplane_guard() (TASK-3805).

Covers the FEAT-598 default data-plane guard wiring: build a
``DataPlanePolicyGuard`` and register ``app["dataplane_guard"]`` when PBAC
can initialize, and leave the key unset (fail-closed 403 preserved) when it
cannot. ``setup_pbac`` itself is monkeypatched — these tests only exercise
``setup_dataplane_guard``'s own wiring/idempotency logic.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web

from parrot.auth.dataplane_guard import DataPlanePolicyGuard
from parrot.auth.pbac import setup_dataplane_guard


def test_evaluator_available_registers_guard(caplog):
    """setup_pbac yielding an evaluator builds and registers a real guard."""
    app = web.Application()
    mock_pdp = MagicMock()
    mock_evaluator = MagicMock()
    mock_guardian = MagicMock()

    with patch(
        "parrot.auth.pbac.setup_pbac",
        return_value=(mock_pdp, mock_evaluator, mock_guardian),
    ) as mock_setup_pbac:
        with caplog.at_level(logging.INFO, logger="parrot.auth.pbac"):
            guard = setup_dataplane_guard(app, policy_dir="policies", cache_ttl=30)

    mock_setup_pbac.assert_called_once_with(app, policy_dir="policies", cache_ttl=30)
    assert isinstance(guard, DataPlanePolicyGuard)
    assert app["dataplane_guard"] is guard
    # The guard was built with the evaluator returned by setup_pbac.
    assert guard._evaluator is mock_evaluator  # noqa: SLF001


def test_pbac_unavailable_leaves_key_absent_and_logs_info(caplog):
    """setup_pbac returning (None, None, None) sets nothing and returns None."""
    app = web.Application()

    with patch(
        "parrot.auth.pbac.setup_pbac",
        return_value=(None, None, None),
    ):
        with caplog.at_level(logging.INFO, logger="parrot.auth.pbac"):
            guard = setup_dataplane_guard(app, policy_dir="nonexistent-policies")

    assert guard is None
    assert "dataplane_guard" not in app
    info_msgs = [r.message for r in caplog.records if r.levelname == "INFO"]
    assert any(
        "PARROT_PBAC_POLICY_DIR" in msg for msg in info_msgs
    ), f"Expected an INFO log naming PARROT_PBAC_POLICY_DIR. Got: {info_msgs}"


def test_existing_guard_is_respected_and_returned_as_is():
    """A pre-existing app['dataplane_guard'] wins — setup_pbac is never called."""
    app = web.Application()
    sentinel_guard = object()
    app["dataplane_guard"] = sentinel_guard

    with patch("parrot.auth.pbac.setup_pbac") as mock_setup_pbac:
        guard = setup_dataplane_guard(app)

    mock_setup_pbac.assert_not_called()
    assert guard is sentinel_guard
    assert app["dataplane_guard"] is sentinel_guard


def test_saas_mode_init_failure_propagates():
    """PARROT_SAAS_MODE=true + PBAC init failure must raise, not fail open."""
    app = web.Application()

    with patch(
        "parrot.auth.pbac.setup_pbac",
        side_effect=RuntimeError("PBAC initialization failed with PARROT_SAAS_MODE=true"),
    ):
        with pytest.raises(RuntimeError, match="PARROT_SAAS_MODE=true"):
            setup_dataplane_guard(app, policy_dir="policies")

    assert "dataplane_guard" not in app


def test_uses_fresh_rls_registry_per_call():
    """Each successful call builds the guard with its own RlsRegistry."""
    app1 = web.Application()
    app2 = web.Application()
    mock_evaluator = MagicMock()

    with patch(
        "parrot.auth.pbac.setup_pbac",
        return_value=(MagicMock(), mock_evaluator, MagicMock()),
    ):
        guard1 = setup_dataplane_guard(app1)
        guard2 = setup_dataplane_guard(app2)

    assert guard1._rls_registry is not guard2._rls_registry  # noqa: SLF001
