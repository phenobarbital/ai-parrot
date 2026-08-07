"""Unit tests for ``PlanFileStore`` — plans_dir loader with load-time
``{params.<name>}`` substitution (TASK-2181).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from parrot.bots.flows.plan import ExecutionPlan
from parrot.tools.execution_plan.store import PlanFileStore, PlanLoadError

_REPO_ROOT = Path(__file__).resolve().parents[5]
_EXAMPLE_PLAN = _REPO_ROOT / "examples" / "plans" / "daily_security_sweep.json"


@pytest.fixture
def plans_dir(tmp_path: Path) -> Path:
    """Writes daily_security_sweep.{yaml,json} with {params.date}."""
    yaml_plan = {
        "name": "daily_security_sweep",
        "objective": "yaml variant",
        "nodes": [
            {
                "id": "listing",
                "tool": "s3_filter_reports",
                "args": {"date": "{params.date}", "note": "sweep on {params.date}"},
                "store_as": "listing",
            }
        ],
    }
    (tmp_path / "daily_security_sweep.yaml").write_text(yaml.safe_dump(yaml_plan))

    json_plan = {
        "name": "json_variant",
        "objective": "json variant",
        "nodes": [
            {
                "id": "n1",
                "tool": "t",
                "args": {"limit": "{params.limit}"},
                "store_as": "k1",
            }
        ],
    }
    (tmp_path / "json_variant.json").write_text(json.dumps(json_plan))

    mixed_plan = {
        "name": "mixed_placeholders",
        "objective": "mixes load-time and runtime placeholders",
        "nodes": [
            {
                "id": "a",
                "tool": "t",
                "args": {"scope": "{params.scope}"},
                "store_as": "ka",
            },
            {
                "id": "b",
                "tool": "t",
                "args": {
                    "prior": "{artifacts.a}",
                    "current": "{item}",
                    "pos": "{index}",
                    "scope": "{params.scope}",
                },
                "store_as": "kb_{index}",
                "depends_on": ["a"],
                "for_each": {"source": "{artifacts.a}"},
            },
        ],
    }
    (tmp_path / "mixed_placeholders.json").write_text(json.dumps(mixed_plan))

    unused_plan = {
        "name": "no_placeholders",
        "objective": "no placeholders at all",
        "nodes": [{"id": "n1", "tool": "t", "store_as": "k1"}],
    }
    (tmp_path / "no_placeholders.json").write_text(json.dumps(unused_plan))

    return tmp_path


class TestPlanFileStore:
    def test_loads_yaml_and_json(self, plans_dir: Path) -> None:
        store = PlanFileStore(plans_dir)

        yaml_result = store.load("daily_security_sweep", params={"date": "2026-08-06"})
        assert isinstance(yaml_result, ExecutionPlan)
        assert yaml_result.name == "daily_security_sweep"

        json_result = store.load("json_variant", params={"limit": 5})
        assert isinstance(json_result, ExecutionPlan)
        assert json_result.name == "json_variant"

    def test_exact_placeholder_native_value(self, plans_dir: Path) -> None:
        store = PlanFileStore(plans_dir)
        plan = store.load("json_variant", params={"limit": 5})
        assert plan.node("n1").args["limit"] == 5  # int, not "5"

    def test_embedded_placeholder_interpolates(self, plans_dir: Path) -> None:
        store = PlanFileStore(plans_dir)
        plan = store.load("daily_security_sweep", params={"date": "2026-08-06"})
        assert plan.node("listing").args["note"] == "sweep on 2026-08-06"
        assert plan.node("listing").args["date"] == "2026-08-06"

    def test_missing_param_raises(self, plans_dir: Path) -> None:
        store = PlanFileStore(plans_dir)
        with pytest.raises(PlanLoadError, match="missing params"):
            store.load("daily_security_sweep", params={})

    def test_unused_param_raises(self, plans_dir: Path) -> None:
        store = PlanFileStore(plans_dir)
        with pytest.raises(PlanLoadError, match="unused params"):
            store.load("no_placeholders", params={"date": "2026-08-06"})

    def test_unknown_plan_lists_available(self, plans_dir: Path) -> None:
        store = PlanFileStore(plans_dir)
        with pytest.raises(PlanLoadError, match="Available"):
            store.load("does_not_exist")

    def test_runtime_placeholders_untouched(self, plans_dir: Path) -> None:
        store = PlanFileStore(plans_dir)
        plan = store.load("mixed_placeholders", params={"scope": "prod"})

        node_b = plan.node("b")
        assert node_b.args["prior"] == "{artifacts.a}"
        assert node_b.args["current"] == "{item}"
        assert node_b.args["pos"] == "{index}"
        assert node_b.args["scope"] == "prod"
        assert plan.node("a").args["scope"] == "prod"

    def test_migrated_example_loads(self) -> None:
        assert _EXAMPLE_PLAN.exists(), f"missing example plan at {_EXAMPLE_PLAN}"
        raw_text = _EXAMPLE_PLAN.read_text()
        assert "{input}" not in raw_text

        store = PlanFileStore(_EXAMPLE_PLAN.parent)
        plan = store.load("daily_security_sweep", params={"date": "2026-08-06"})
        assert plan.name == "daily_security_sweep"
        assert plan.node("listing").args["date"] == "2026-08-06"

    def test_no_params_placeholder_survives_load(self, plans_dir: Path) -> None:
        store = PlanFileStore(plans_dir)
        plan = store.load("mixed_placeholders", params={"scope": "prod"})
        dumped = plan.model_dump_json()
        assert "{params." not in dumped

    def test_nonexistent_plans_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(PlanLoadError):
            PlanFileStore(tmp_path / "does-not-exist")

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """`plan_name` is agent/LLM-controlled — must never escape plans_dir."""
        outside_dir = tmp_path.parent / "outside_dir_for_traversal_test"
        outside_dir.mkdir(exist_ok=True)
        secret_plan = {
            "name": "leaked-plan", "objective": "outside plans_dir",
            "nodes": [{"id": "n1", "tool": "t", "store_as": "k1"}],
        }
        (outside_dir / "secret.json").write_text(json.dumps(secret_plan))

        plans_dir = tmp_path / "plans"
        plans_dir.mkdir()
        store = PlanFileStore(plans_dir)

        for traversal_name in ("../outside_dir_for_traversal_test/secret", "../../etc/passwd", "sub/dir"):
            with pytest.raises(PlanLoadError, match="Invalid plan_name"):
                store.load(traversal_name)

    def test_malformed_json_raises_plan_load_error_not_raw_exception(
        self, tmp_path: Path
    ) -> None:
        """A corrupt plan file must surface as PlanLoadError, never a raw
        JSONDecodeError/YAMLError escaping the store's public API."""
        plans_dir = tmp_path
        (plans_dir / "broken.json").write_text("{ this is not valid json !!")
        store = PlanFileStore(plans_dir)

        with pytest.raises(PlanLoadError, match="not valid"):
            store.load("broken")

    def test_malformed_yaml_raises_plan_load_error(self, tmp_path: Path) -> None:
        plans_dir = tmp_path
        (plans_dir / "broken.yaml").write_text("key: [unterminated\n  - nested: :::")
        store = PlanFileStore(plans_dir)

        with pytest.raises(PlanLoadError, match="not valid"):
            store.load("broken")
