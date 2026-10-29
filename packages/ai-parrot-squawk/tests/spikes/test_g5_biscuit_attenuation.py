"""G5 regression — attenuated token allowed on hr.reports.*, refused on hr.people.* (opt-in)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PARROT_SPIKE") != "1",
    reason="spike: set PARROT_SPIKE=1",
)
pytest.importorskip("biscuit_auth")
SPIKE = Path(__file__).resolve().parents[4] / "sdd/state/FEAT-746/spikes/G5-biscuit-attenuation/spike.py"


def test_issue_attenuate_refuse() -> None:
    """Test that the spike runs and returns 0 (all cases pass)."""
    spec = importlib.util.spec_from_file_location("g5_spike", SPIKE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load spike at {SPIKE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0


def test_prefix_is_derived_from_the_token_glob() -> None:
    """A second glob proves the check follows the token's capability_glob, not a constant."""
    from datetime import datetime, timedelta, timezone

    spec = importlib.util.spec_from_file_location("g5_spike_glob", SPIKE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load spike at {SPIKE}")
    g5 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g5)

    kp = g5.KeyPair()
    token = g5.issue_root(kp, caller="ext", glob="finance.ledger.*")
    now = int(datetime.now(timezone.utc).timestamp())
    exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    raw = token.to_bytes()

    def allowed(cap_id: str) -> bool:
        return g5.authorize(raw, kp.public_key, cap_id=cap_id, caller="ext", now=now, exp=exp)

    assert allowed("finance.ledger.balance") is True
    assert allowed("hr.reports.headcount_by_dept") is False
    assert allowed("finance.ledgerx.balance") is False
