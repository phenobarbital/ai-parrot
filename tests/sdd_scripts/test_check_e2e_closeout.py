"""Unit and CLI contract for the FEAT-703 closeout gate script.

Covers what ``test_e2e_closeout_contract.py`` does not: spec policy parsing, the
CLI boundary, and the optional-install import guard. The decision table itself
is covered there, against real on-disk evidence.
"""

from __future__ import annotations

import builtins
import inspect
import json
from pathlib import Path

import pytest

from scripts.sdd.check_e2e_closeout import (
    GateDecision,
    _verify,
    evaluate_closeout_gate,
    evaluate_closeout_gate_detailed,
    main,
    resolve_policy,
)


def _write_spec(tmp_path: Path, frontmatter: str) -> Path:
    spec = tmp_path / "example.spec.md"
    spec.write_text(f"---\n{frontmatter}\n---\n\n# Example\n", encoding="utf-8")
    return spec


# ---------------------------------------------------------------------------
# AC2 — force is structurally absent
# ---------------------------------------------------------------------------


def test_gate_has_no_force_parameter() -> None:
    """AC9/AC2: force cannot be passed, so nothing can bypass the gate."""
    assert "force" not in inspect.signature(evaluate_closeout_gate).parameters
    assert "force" not in inspect.signature(evaluate_closeout_gate_detailed).parameters


# ---------------------------------------------------------------------------
# resolve_policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("policy", ["required", "optional", "none"])
def test_resolve_policy_round_trips_each_valid_literal(tmp_path: Path, policy: str) -> None:
    spec = _write_spec(tmp_path, f"type: feature\ne2e:\n  policy: {policy}")
    assert resolve_policy(spec) == policy


def test_resolve_policy_missing_e2e_key_defaults_optional(tmp_path: Path) -> None:
    """A legacy spec with no `e2e` key is `optional`, never `required`."""
    spec = _write_spec(tmp_path, "type: feature\nbase_branch: dev")
    assert resolve_policy(spec) == "optional"


def test_resolve_policy_missing_file_defaults_optional(tmp_path: Path) -> None:
    assert resolve_policy(tmp_path / "nope.spec.md") == "optional"


@pytest.mark.parametrize(
    "frontmatter",
    [
        "type: feature\ne2e:\n  policy: REQUIRED",
        "type: feature\ne2e:\n  policy: sometimes",
        "type: feature\ne2e: not-a-mapping",
        "type: feature\ne2e:\n  policy: true",
    ],
)
def test_resolve_policy_malformed_value_is_invalid(tmp_path: Path, frontmatter: str) -> None:
    """AC5: a malformed policy is never coerced to a safe default."""
    spec = _write_spec(tmp_path, frontmatter)
    assert resolve_policy(spec) == "invalid"


def test_resolve_policy_e2e_without_policy_key_defaults_optional(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path, "type: feature\ne2e:\n  scenario_ids: []")
    assert resolve_policy(spec) == "optional"


# ---------------------------------------------------------------------------
# Import guard — ai-parrot-server is an optional install
# ---------------------------------------------------------------------------


async def test_verify_treats_unimportable_parrot_e2e_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4: an absent validator fails closed with a reason code, not a traceback."""
    real_import = builtins.__import__

    def _blocked(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("parrot.e2e"):
            raise ImportError("ai-parrot-server is not installed")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _blocked)

    plan = tmp_path / "e2e-plan.md"
    plan.write_text("# plan\n", encoding="utf-8")

    result = await _verify(plan, tmp_path)

    assert result.status == "MISSING"
    assert result.gate_satisfied is False
    assert result.reason_codes == ["e2e_validator_unavailable"]


async def test_required_policy_blocks_when_validator_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An uninstalled validator must never let a `required` feature through."""
    real_import = builtins.__import__

    def _blocked(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("parrot.e2e"):
            raise ImportError("ai-parrot-server is not installed")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _blocked)

    plan = tmp_path / "e2e-plan.md"
    plan.write_text("# plan\n", encoding="utf-8")

    allowed, reasons = await evaluate_closeout_gate(policy="required", plan_path=plan, worktree=tmp_path)

    assert allowed is False
    assert "e2e_required_not_satisfied:MISSING" in reasons


# ---------------------------------------------------------------------------
# CLI boundary
# ---------------------------------------------------------------------------


def test_cli_exits_zero_and_emits_json_when_gate_allows(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """AC3: policy `none` is exempt — exit 0 with a JSON payload on stdout."""
    spec = _write_spec(tmp_path, "type: feature\ne2e:\n  policy: none")

    exit_code = main(["--spec", str(spec), "--feat-id", "FEAT-703", "--worktree", str(tmp_path)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "policy": "none",
        "status": "NONE",
        "gate_satisfied": False,
        "reason_codes": ["e2e_policy_none"],
        "allowed": True,
    }


def test_cli_exits_nonzero_when_required_gate_blocks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """AC3: `required` with no plan file aborts closeout with exit 1."""
    spec = _write_spec(tmp_path, "type: feature\ne2e:\n  policy: required")

    exit_code = main(["--spec", str(spec), "--feat-id", "FEAT-703", "--worktree", str(tmp_path)])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["allowed"] is False
    assert payload["policy"] == "required"
    assert payload["reason_codes"] == ["e2e_required_missing_plan"]


def test_cli_malformed_policy_is_gated_like_required(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A malformed policy blocks exactly like `required` with missing evidence."""
    spec = _write_spec(tmp_path, "type: feature\ne2e:\n  policy: sometimes")

    exit_code = main(["--spec", str(spec), "--feat-id", "FEAT-703", "--worktree", str(tmp_path)])

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["policy"] == "invalid"


def test_cli_optional_with_no_plan_is_advisory_and_proceeds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = _write_spec(tmp_path, "type: feature\ne2e:\n  policy: optional")

    exit_code = main(["--spec", str(spec), "--feat-id", "FEAT-703", "--worktree", str(tmp_path)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["allowed"] is True
    assert payload["reason_codes"] == ["e2e_optional_no_plan"]


def test_cli_resolves_the_plan_under_the_worktree(tmp_path: Path) -> None:
    """The plan is always worktree-scoped: <worktree>/sdd/state/<FEAT-ID>/e2e-plan.md."""
    spec = _write_spec(tmp_path, "type: feature\ne2e:\n  policy: required")
    plan = tmp_path / "sdd" / "state" / "FEAT-703" / "e2e-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# plan\n", encoding="utf-8")

    # The plan now exists, so the gate advances past `e2e_required_missing_plan`
    # into real validation instead of short-circuiting on the missing file.
    exit_code = main(["--spec", str(spec), "--feat-id", "FEAT-703", "--worktree", str(tmp_path)])

    assert exit_code == 1  # no evidence behind the plan, so still blocked


# ---------------------------------------------------------------------------
# Wrapper parity
# ---------------------------------------------------------------------------


async def test_tuple_wrapper_matches_detailed_decision(tmp_path: Path) -> None:
    detailed = await evaluate_closeout_gate_detailed(policy="none", plan_path=None, worktree=tmp_path)
    allowed, reasons = await evaluate_closeout_gate(policy="none", plan_path=None, worktree=tmp_path)

    assert isinstance(detailed, GateDecision)
    assert (allowed, reasons) == (detailed.allowed, detailed.reason_codes)
