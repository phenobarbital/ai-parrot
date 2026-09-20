"""Unit tests for the FEAT-580 M5 curated pilot tasks and ground truth.

Every test here works purely offline: it reads ``benchmarks/sdd_lsp/tasks.yaml``,
materializes fixture trees under ``tmp_path``, and runs each fixture's own
bundled ``check.py`` in a disposable subprocess. Nothing spawns Pyright,
touches the network, or depends on which retrieval arm produced a change
(TASK-3510).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

#: tests/lsp -> tests -> ai-parrot-tools -> packages -> repo root
ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.sdd_lsp.fixtures import acceptance  # noqa: E402
from benchmarks.sdd_lsp.fixtures import scenarios  # noqa: E402
from benchmarks.sdd_lsp.fixtures.scenarios import (  # noqa: E402
    CHANGE_SCENARIO_IDS,
    FIX_SCENARIO_IDS,
    INVESTIGATION_SCENARIO_IDS,
    SCENARIO_IDS,
    ScenarioFixture,
    build_fixture,
)

TASKS_YAML_PATH = ROOT / "benchmarks" / "sdd_lsp" / "tasks.yaml"

#: The six named coverage shapes the spec requires across the matrix
#: (spec §3 M5: "include aliases, inherited receivers, namespaces,
#: decorators, registry strings and unavailable-server fallback").
REQUIRED_COVERAGE_TAGS = frozenset(
    {"alias", "inherited_receiver", "namespace", "decorator", "registry", "unavailable_server"}
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _load_manifest() -> dict[str, Any]:
    with TASKS_YAML_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _tasks_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in manifest["tasks"]}


def _validate_manifest(manifest: dict[str, Any]) -> None:
    """Re-validate structural invariants of the pilot task manifest.

    Raises:
        ValueError: If the manifest does not describe exactly the fixed
            four-investigation/four-change/four-fix, twelve-task matrix
            with a resolvable fixture and a pinned hash for every task.
    """
    tasks = manifest["tasks"]
    if len(tasks) != 12:
        raise ValueError(f"expected exactly 12 tasks, got {len(tasks)}")

    ids = [task["id"] for task in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError("task ids must be unique")
    if set(ids) != set(SCENARIO_IDS):
        raise ValueError(f"task ids do not match the approved scenario set: {sorted(set(ids) ^ set(SCENARIO_IDS))}")

    by_category: dict[str, list[str]] = {"investigation": [], "change": [], "fix": []}
    for task in tasks:
        category = task["category"]
        if category not in by_category:
            raise ValueError(f"unknown category: {category!r}")
        by_category[category].append(task["id"])
    for category, expected_ids in (
        ("investigation", INVESTIGATION_SCENARIO_IDS),
        ("change", CHANGE_SCENARIO_IDS),
        ("fix", FIX_SCENARIO_IDS),
    ):
        if len(by_category[category]) != 4:
            raise ValueError(f"expected exactly 4 {category} tasks, got {len(by_category[category])}")
        if set(by_category[category]) != set(expected_ids):
            raise ValueError(f"{category} task ids do not match the approved set")

    for task in tasks:
        fixture = build_fixture(task["fixture"])
        if fixture.content_sha256() != task["fixture_sha256"]:
            raise ValueError(f"{task['id']}: fixture_sha256 does not match its materialized content")
        expected_dynamic = acceptance.requires_supplementary_text_search(task["id"])
        if bool(task["supplementary_text_search"]) != expected_dynamic:
            raise ValueError(f"{task['id']}: supplementary_text_search disagrees with the acceptance policy")


def _materialize(scenario_id: str, tmp_path: Path) -> tuple[ScenarioFixture, Path]:
    fixture = build_fixture(scenario_id)
    root = tmp_path / scenario_id
    root.mkdir()
    fixture.materialize(root)
    return fixture, root


# --------------------------------------------------------------------------- #
# test_twelve_scenarios_cover_approved_matrix
# --------------------------------------------------------------------------- #
def test_twelve_scenarios_cover_approved_matrix():
    """The manifest is exactly the approved 4/4/4 matrix with resolvable fixtures."""
    manifest = _load_manifest()
    assert manifest["task_count"] == 12
    assert set(manifest["categories"]) == {"investigation", "change", "fix"}

    # Successful case: the manifest as authored must validate cleanly.
    _validate_manifest(manifest)

    tasks_by_id = _tasks_by_id(manifest)
    assert set(tasks_by_id) == set(SCENARIO_IDS)
    for scenario_id in INVESTIGATION_SCENARIO_IDS:
        assert tasks_by_id[scenario_id]["category"] == "investigation"
        assert tasks_by_id[scenario_id]["entry_point"] is None
    for scenario_id in CHANGE_SCENARIO_IDS + FIX_SCENARIO_IDS:
        category = tasks_by_id[scenario_id]["category"]
        assert category in ("change", "fix")
        assert tasks_by_id[scenario_id]["entry_point"], f"{scenario_id} must name an editable entry_point"

    # Every named coverage shape from the spec is represented somewhere in
    # the matrix (aliases, inherited receivers, namespaces, decorators,
    # registry strings, unavailable-server fallback).
    covered_tags: set[str] = set()
    for task in manifest["tasks"]:
        covered_tags.update(task["includes"])
    assert REQUIRED_COVERAGE_TAGS <= covered_tags, f"missing coverage tags: {REQUIRED_COVERAGE_TAGS - covered_tags}"

    # Every fixture id referenced by the manifest actually builds.
    for task in manifest["tasks"]:
        fixture = build_fixture(task["fixture"])
        assert fixture.scenario_id == task["id"]
        assert fixture.category == task["category"]

    # Adversarial: a manifest missing an entire category must be rejected,
    # not silently accepted as "11 tasks is close enough".
    mutated = dict(manifest)
    mutated["tasks"] = [t for t in manifest["tasks"] if t["category"] != "fix"]
    with pytest.raises(ValueError, match="expected exactly 12 tasks"):
        _validate_manifest(mutated)

    # Adversarial: duplicating one task id in place of another must also
    # be rejected (the matrix must cover all twelve distinct scenarios).
    duplicated = dict(manifest)
    duplicated["tasks"] = list(manifest["tasks"])
    duplicated["tasks"][-1] = dict(duplicated["tasks"][0])
    with pytest.raises(ValueError, match="unique|do not match"):
        _validate_manifest(duplicated)


# --------------------------------------------------------------------------- #
# test_acceptance_rejects_incorrect_changes
# --------------------------------------------------------------------------- #
def test_acceptance_rejects_incorrect_changes(tmp_path: Path):
    """Every change/fix fixture's check rejects the bug/partial fix and accepts the real one."""
    for scenario_id in CHANGE_SCENARIO_IDS + FIX_SCENARIO_IDS:
        fixture, root = _materialize(scenario_id, tmp_path)

        # The unedited baseline must fail: the bug (fix tasks) or the
        # not-yet-added capability (change tasks) is still present. A
        # fixture whose baseline already satisfies its own check would be
        # a vacuous, un-gradeable task.
        baseline_result = acceptance.run_behavior_check(fixture, root)
        assert not baseline_result.passed, f"{scenario_id}: baseline must not already satisfy its own check"

        # A plausible-but-wrong attempt must also be rejected.
        fixture.apply_variant(root, "counterexample")
        counterexample_result = acceptance.run_behavior_check(fixture, root)
        assert not counterexample_result.passed, f"{scenario_id}: counterexample must be rejected"
        assert counterexample_result.reasons, "a rejected attempt must explain why"

        # The independently authored correct fix must pass.
        fixture.apply_variant(root, "expected_fix")
        fixed_result = acceptance.run_behavior_check(fixture, root)
        assert fixed_result.passed, f"{scenario_id}: expected_fix must pass: {fixed_result.reasons}"

    # Investigation tasks: submitted-answer acceptance, not code changes.
    for scenario_id in INVESTIGATION_SCENARIO_IDS:
        expected_path, expected_line = acceptance.EXPECTED_DEFINITIONS[scenario_id]

        correct = acceptance.check_definition_answer(scenario_id, expected_path, expected_line)
        assert correct.passed

        wrong_line = acceptance.check_definition_answer(scenario_id, expected_path, expected_line + 1)
        assert not wrong_line.passed
        assert wrong_line.reasons

        wrong_path = acceptance.check_definition_answer(scenario_id, "pkg/nonexistent.py", expected_line)
        assert not wrong_path.passed

        # The curated expected answer is itself grounded in real behavior:
        # the fixture's own check.py (which never mentions the expected
        # answer) must pass unedited, proving the ground truth is
        # reviewable and correct before any live measurement.
        fixture, root = _materialize(scenario_id, tmp_path)
        grounding_result = acceptance.run_behavior_check(fixture, root)
        assert grounding_result.passed, f"{scenario_id}: investigation ground truth must be behaviorally grounded"


# --------------------------------------------------------------------------- #
# test_dynamic_cases_require_additional_evidence
# --------------------------------------------------------------------------- #
def test_dynamic_cases_require_additional_evidence():
    """Exactly the dynamic/registry-shaped scenarios require a supplementary text search."""
    manifest = _load_manifest()
    tasks_by_id = _tasks_by_id(manifest)

    expected_dynamic = {
        "inv-namespace-import",
        "chg-decorator-wrapper",
        "chg-registry-dispatch",
        "fix-unavailable-server",
    }
    assert acceptance.SUPPLEMENTARY_TEXT_SEARCH_SCENARIOS == expected_dynamic
    assert set(manifest["policy"]["supplementary_text_search_required_for"]) == expected_dynamic

    for scenario_id in SCENARIO_IDS:
        expected = scenario_id in expected_dynamic
        assert acceptance.requires_supplementary_text_search(scenario_id) is expected
        assert bool(tasks_by_id[scenario_id]["supplementary_text_search"]) is expected

    # Adversarial: a static, unambiguous scenario must not be misclassified
    # as requiring a supplementary text search.
    assert acceptance.requires_supplementary_text_search("inv-duplicate-names") is False
    assert acceptance.requires_supplementary_text_search("chg-signature-callers") is False

    # Adversarial: an unrecognized id is not spuriously treated as dynamic.
    assert acceptance.requires_supplementary_text_search("not-a-real-scenario") is False

    # Only the one fixture that simulates the LSP server itself being
    # unavailable carries the fallback flag; it is also always dynamic.
    fallback_ids = {task["id"] for task in manifest["tasks"] if task["fallback_required"]}
    assert fallback_ids == {"fix-unavailable-server"}
    assert fallback_ids <= expected_dynamic


# --------------------------------------------------------------------------- #
# test_fixture_hashes_and_prompts_are_stable
# --------------------------------------------------------------------------- #
def test_fixture_hashes_and_prompts_are_stable():
    """Fixture content hashes are deterministic and pinned; prompts are stable text."""
    manifest = _load_manifest()
    tasks_by_id = _tasks_by_id(manifest)

    for scenario_id in SCENARIO_IDS:
        first = build_fixture(scenario_id)
        second = build_fixture(scenario_id)

        # Determinism: two independent builds hash identically.
        assert first.content_sha256() == second.content_sha256()

        # Pinned: the manifest's recorded hash matches the live builder.
        pinned = tasks_by_id[scenario_id]["fixture_sha256"]
        assert first.content_sha256() == pinned, f"{scenario_id}: pinned fixture_sha256 is stale"
        assert len(pinned) == 64 and all(c in "0123456789abcdef" for c in pinned)

        # Prompts are non-empty, stable strings across repeated loads.
        prompt = tasks_by_id[scenario_id]["prompt"]
        assert isinstance(prompt, str) and prompt.strip()
        assert _load_manifest()["tasks"][SCENARIO_IDS.index(scenario_id)]["prompt"] == prompt

    # Adversarial/sensitivity: the hash must actually depend on file
    # content, not merely on file names -- mutating one byte of one file
    # must change the hash.
    reference = build_fixture("fix-type-mismatch")
    mutated_files = tuple(
        f if f.relative_path != "pkg9/calc.py" else scenarios.FixtureFile(f.relative_path, f.content + "\n")
        for f in reference.files
    )
    mutated = scenarios.ScenarioFixture(
        scenario_id=reference.scenario_id,
        category=reference.category,
        files=mutated_files,
        entry_point=reference.entry_point,
        expected_fix=reference.expected_fix,
        counterexample=reference.counterexample,
        includes=reference.includes,
    )
    assert mutated.content_sha256() != reference.content_sha256()

    # Adversarial: an unpinned/incorrect hash must be detectable, not
    # silently tolerated by a validator that only checks presence.
    with pytest.raises(ValueError, match="fixture_sha256"):
        _validate_manifest(
            {
                **manifest,
                "tasks": [
                    {**task, "fixture_sha256": "0" * 64} if task["id"] == "fix-type-mismatch" else task
                    for task in manifest["tasks"]
                ],
            }
        )
