"""Unit tests for ``parrot.e2e.plan.load_plan`` (TASK-3521, M2).

Covers success parsing, typed-error rejection of unsafe/escaping paths,
missing/malformed frontmatter, missing/coerced policy handling, duplicate or
undeclared node/target references, wildcard/bare-directory node selection
and spec/plan cross-consistency — all synthetic, filesystem-isolated via
``tmp_path`` (never the real repository). No target/provider/process is
spawned; every assertion is that ``load_plan`` raises before any subprocess
would even be considered.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from parrot.e2e.errors import EXIT_CONFIG, E2EConfigError
from parrot.e2e.models import E2EPlan
from parrot.e2e.plan import load_plan

# ---------------------------------------------------------------------------
# Frontmatter builders
# ---------------------------------------------------------------------------


def _write_frontmatter(path: Path, data: dict[str, Any] | None, *, body: str = "Rationale.\n") -> None:
    """Write a Markdown file with a YAML frontmatter block (or a broken one).

    Args:
        path: Destination file path; parent directories are created.
        data: Mapping to dump as YAML frontmatter, or ``None`` to write an
            empty frontmatter block.
        body: Markdown body appended after the closing delimiter.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = "" if data is None else yaml.safe_dump(data, sort_keys=False)
    path.write_text(f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")


def _plan_data(**overrides: Any) -> dict[str, Any]:
    """Build a minimal, valid raw ``E2EPlan`` frontmatter mapping."""
    data: dict[str, Any] = {
        "feature_id": "FEAT-581",
        "spec_path": "sdd/specs/agentic-e2e-testing.spec.md",
        "policy": "required",
        "targets": {"stdio": {"kind": "mcp-stdio"}},
        "scenarios": [
            {
                "id": "scn-mcp-stdio",
                "tier": "deterministic",
                "target_ids": ["stdio"],
                "required": True,
                "node_ids": ["tests/e2e/test_mcp_stdio.py::test_roundtrip"],
            }
        ],
    }
    data.update(overrides)
    return data


def _spec_data(**overrides: Any) -> dict[str, Any]:
    """Build a minimal, valid raw spec frontmatter mapping (matches the SDD template)."""
    data: dict[str, Any] = {
        "type": "feature",
        "base_branch": "dev",
        "projects": ["ai-parrot-server"],
        "tags": ["e2e"],
    }
    data.update(overrides)
    return data


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """An isolated synthetic worktree root — never the real repository."""
    root = tmp_path / "worktree"
    root.mkdir()
    return root


def _seed_spec(worktree: Path, *, relative: str = "sdd/specs/agentic-e2e-testing.spec.md", **overrides: Any) -> Path:
    spec_path = worktree / relative
    _write_frontmatter(spec_path, _spec_data(**overrides))
    return spec_path


def _seed_plan(worktree: Path, *, relative: str = "sdd/state/e2e-plan.md", **overrides: Any) -> Path:
    plan_path = worktree / relative
    _write_frontmatter(plan_path, _plan_data(**overrides))
    return plan_path


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


def test_load_plan_parses_valid_frontmatter(worktree: Path) -> None:
    _seed_spec(worktree)
    plan_path = _seed_plan(worktree)

    plan = load_plan(plan_path, worktree=worktree)

    assert isinstance(plan, E2EPlan)
    assert plan.feature_id == "FEAT-581"
    assert plan.policy == "required"
    assert plan.scenarios[0].id == "scn-mcp-stdio"


def test_load_plan_accepts_relative_path_against_worktree(worktree: Path) -> None:
    _seed_spec(worktree)
    _seed_plan(worktree, relative="sdd/state/e2e-plan.md")

    plan = load_plan(Path("sdd/state/e2e-plan.md"), worktree=worktree)

    assert plan.feature_id == "FEAT-581"


# ---------------------------------------------------------------------------
# Missing / unreadable plan file (AC2: "invalid/missing plans ... fail
# before target startup")
# ---------------------------------------------------------------------------


def test_load_plan_missing_file_raises_config_error(worktree: Path) -> None:
    _seed_spec(worktree)
    missing = worktree / "sdd" / "state" / "does-not-exist.md"

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(missing, worktree=worktree)

    assert excinfo.value.exit_code == EXIT_CONFIG
    assert excinfo.value.reason_code == "plan_missing"


def test_load_plan_directory_instead_of_file_raises_config_error(worktree: Path) -> None:
    _seed_spec(worktree)
    directory = worktree / "sdd" / "state"
    directory.mkdir(parents=True)

    with pytest.raises(E2EConfigError):
        load_plan(directory, worktree=worktree)


# ---------------------------------------------------------------------------
# Frontmatter shape failures
# ---------------------------------------------------------------------------


def test_load_plan_rejects_missing_frontmatter_delimiter(worktree: Path) -> None:
    _seed_spec(worktree)
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("# Not a frontmatter document\n", encoding="utf-8")

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "plan_no_frontmatter"


def test_load_plan_rejects_unclosed_frontmatter(worktree: Path) -> None:
    _seed_spec(worktree)
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\nfeature_id: FEAT-581\n", encoding="utf-8")

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "plan_no_frontmatter"


def test_load_plan_rejects_invalid_yaml(worktree: Path) -> None:
    _seed_spec(worktree)
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\nfeature_id: [unterminated\n---\n", encoding="utf-8")

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "plan_invalid_yaml"


def test_load_plan_rejects_non_mapping_frontmatter(worktree: Path) -> None:
    _seed_spec(worktree)
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("---\n- just\n- a\n- list\n---\n", encoding="utf-8")

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "plan_invalid_yaml"


# ---------------------------------------------------------------------------
# Policy handling: missing defaults to optional, explicit none, never coerced
# ---------------------------------------------------------------------------


def test_load_plan_missing_policy_defaults_to_optional(worktree: Path) -> None:
    _seed_spec(worktree)
    data = _plan_data()
    del data["policy"]
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    _write_frontmatter(plan_path, data)

    plan = load_plan(plan_path, worktree=worktree)

    assert plan.policy == "optional"


def test_load_plan_explicit_none_policy_allows_no_scenarios(worktree: Path) -> None:
    _seed_spec(worktree)
    plan_path = _seed_plan(worktree, policy="none", scenarios=[])

    plan = load_plan(plan_path, worktree=worktree)

    assert plan.policy == "none"
    assert plan.scenarios == []


def test_load_plan_does_not_coerce_invalid_policy(worktree: Path) -> None:
    _seed_spec(worktree)
    plan_path = _seed_plan(worktree, policy="sometimes")

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "plan_invalid"


def test_load_plan_required_policy_without_required_scenario_fails(worktree: Path) -> None:
    _seed_spec(worktree)
    data = _plan_data(policy="required")
    data["scenarios"][0]["required"] = False
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    _write_frontmatter(plan_path, data)

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "plan_invalid"


# ---------------------------------------------------------------------------
# Node/target/scenario rejection (delegated to, and surfaced from, E2EPlan)
# ---------------------------------------------------------------------------


def test_load_plan_rejects_wildcard_node_selection(worktree: Path) -> None:
    _seed_spec(worktree)
    data = _plan_data()
    data["scenarios"][0]["node_ids"] = ["tests/e2e/test_mcp_stdio.py::test_*"]
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    _write_frontmatter(plan_path, data)

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "plan_invalid"


def test_load_plan_rejects_bare_directory_node_selection(worktree: Path) -> None:
    _seed_spec(worktree)
    data = _plan_data()
    data["scenarios"][0]["node_ids"] = ["tests/e2e/"]
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    _write_frontmatter(plan_path, data)

    with pytest.raises(E2EConfigError):
        load_plan(plan_path, worktree=worktree)


def test_load_plan_rejects_duplicate_node_ids_across_scenarios(worktree: Path) -> None:
    _seed_spec(worktree)
    data = _plan_data()
    shared_node = "tests/e2e/test_mcp_stdio.py::test_roundtrip"
    data["targets"]["http"] = {"kind": "mcp-toolkit"}
    data["scenarios"].append(
        {
            "id": "scn-mcp-http",
            "tier": "deterministic",
            "target_ids": ["http"],
            "required": False,
            "node_ids": [shared_node],
        }
    )
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    _write_frontmatter(plan_path, data)

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "plan_invalid"


def test_load_plan_rejects_undeclared_target_reference(worktree: Path) -> None:
    _seed_spec(worktree)
    data = _plan_data()
    data["scenarios"][0]["target_ids"] = ["not-declared"]
    plan_path = worktree / "sdd" / "state" / "e2e-plan.md"
    _write_frontmatter(plan_path, data)

    with pytest.raises(E2EConfigError):
        load_plan(plan_path, worktree=worktree)


# ---------------------------------------------------------------------------
# Path safety: traversal and symlink escape, for both the plan path and the
# referenced spec_path
# ---------------------------------------------------------------------------


def test_load_plan_rejects_plan_path_outside_worktree(worktree: Path, tmp_path: Path) -> None:
    _seed_spec(worktree)
    outside = tmp_path / "outside-plan.md"
    _write_frontmatter(outside, _plan_data())

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(outside, worktree=worktree)

    assert excinfo.value.reason_code == "path_escape"


def test_load_plan_rejects_plan_path_escaping_via_symlink(worktree: Path, tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    _seed_spec(worktree)
    real_plan = outside_dir / "real-plan.md"
    _write_frontmatter(real_plan, _plan_data())

    link_path = worktree / "sdd" / "state" / "e2e-plan.md"
    link_path.parent.mkdir(parents=True)
    link_path.symlink_to(real_plan)

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(link_path, worktree=worktree)

    assert excinfo.value.reason_code == "path_escape"


def test_load_plan_rejects_missing_spec_file(worktree: Path) -> None:
    plan_path = _seed_plan(worktree, spec_path="sdd/specs/does-not-exist.spec.md")

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "spec_path_missing"


def test_load_plan_rejects_spec_path_escaping_via_symlink(worktree: Path, tmp_path: Path) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    real_spec = outside_dir / "real.spec.md"
    _write_frontmatter(real_spec, _spec_data())

    link_spec = worktree / "sdd" / "specs" / "linked.spec.md"
    link_spec.parent.mkdir(parents=True)
    link_spec.symlink_to(real_spec)

    plan_path = _seed_plan(worktree, spec_path="sdd/specs/linked.spec.md")

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "path_escape"


def test_load_plan_rejects_nonexistent_worktree(tmp_path: Path) -> None:
    missing_worktree = tmp_path / "does-not-exist"
    plan_path = tmp_path / "e2e-plan.md"
    _write_frontmatter(plan_path, _plan_data())

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=missing_worktree)

    assert excinfo.value.reason_code == "worktree_missing"


# ---------------------------------------------------------------------------
# Spec/plan policy and scenario ID consistency
# ---------------------------------------------------------------------------


def test_load_plan_accepts_matching_spec_declared_policy(worktree: Path) -> None:
    _seed_spec(worktree, e2e={"policy": "required", "scenario_ids": ["scn-mcp-stdio"]})
    plan_path = _seed_plan(worktree)

    plan = load_plan(plan_path, worktree=worktree)

    assert plan.policy == "required"


def test_load_plan_rejects_spec_plan_policy_mismatch(worktree: Path) -> None:
    _seed_spec(worktree, e2e={"policy": "optional"})
    plan_path = _seed_plan(worktree, policy="required")

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "spec_plan_policy_mismatch"


def test_load_plan_rejects_spec_plan_scenario_id_mismatch(worktree: Path) -> None:
    _seed_spec(worktree, e2e={"scenario_ids": ["scn-other"]})
    plan_path = _seed_plan(worktree)

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.reason_code == "spec_plan_scenario_mismatch"


def test_load_plan_ignores_spec_without_e2e_metadata(worktree: Path) -> None:
    _seed_spec(worktree)  # no `e2e` key at all — matches every spec today
    plan_path = _seed_plan(worktree, policy="optional")

    plan = load_plan(plan_path, worktree=worktree)

    assert plan.policy == "optional"


# ---------------------------------------------------------------------------
# AC2 / Scope: typed errors are returned before any subprocess is considered
# ---------------------------------------------------------------------------


def test_load_plan_never_spawns_a_subprocess_on_failure(worktree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_spec(worktree)

    def _fail_if_called(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("load_plan must not spawn a subprocess")

    monkeypatch.setattr(subprocess, "Popen", _fail_if_called)
    monkeypatch.setattr(subprocess, "run", _fail_if_called)

    missing = worktree / "sdd" / "state" / "missing-plan.md"

    with pytest.raises(E2EConfigError):
        load_plan(missing, worktree=worktree)


def test_all_load_plan_failures_are_e2e_config_errors_mapped_to_exit_2(worktree: Path) -> None:
    _seed_spec(worktree)
    plan_path = _seed_plan(worktree, policy="not-a-policy")

    with pytest.raises(E2EConfigError) as excinfo:
        load_plan(plan_path, worktree=worktree)

    assert excinfo.value.exit_code == 2
    assert excinfo.value.exit_code == EXIT_CONFIG
