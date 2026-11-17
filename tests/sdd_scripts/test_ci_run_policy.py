"""Coverage safeguards for reducing redundant monorepo CI work."""

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from scripts import ci_run_policy

REPOSITORY = "phenobarbital/ai-parrot"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def event() -> dict[str, Any]:
    """Represent one ordinary update to a protected branch."""
    return {"ref": "refs/heads/dev", "before": "previous-tip", "after": "new-tip", "forced": False}


@pytest.fixture
def merged_pull() -> dict[str, Any]:
    """Represent a PR merged into this repository at the pushed tip."""
    return {
        "merged_at": "2026-11-16T12:41:19Z",
        "merge_commit_sha": "new-tip",
        "base": {"ref": "dev", "repo": {"full_name": REPOSITORY}},
    }


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Prevent any network access while controlling GitHub metadata."""
    lookup = Mock()
    monkeypatch.setattr(ci_run_policy, "github_json", lookup)
    return lookup


@pytest.mark.parametrize("event_name", ["pull_request", "workflow_dispatch"])
def test_non_push_always_runs_full_suite(event_name: str, event: dict[str, Any], api: Mock) -> None:
    """PR validation cannot be disabled by associated-commit metadata."""
    assert ci_run_policy.needs_full_suite(event_name, event, REPOSITORY)
    api.assert_not_called()


def test_direct_push_runs_full_suite(event: dict[str, Any], api: Mock) -> None:
    """A direct push without a merged PR retains all build/test jobs."""
    api.return_value = []
    assert ci_run_policy.needs_full_suite("push", event, REPOSITORY)


@pytest.mark.parametrize("branch", ["main", "dev"])
@pytest.mark.parametrize("parent_count", [1, 2])
def test_merge_and_squash_use_post_merge_checks(
    branch: str, parent_count: int, event: dict[str, Any], merged_pull: dict[str, Any], api: Mock
) -> None:
    """Recognize both merge commits and squash merges on either target branch."""
    event["ref"] = f"refs/heads/{branch}"
    merged_pull["base"]["ref"] = branch
    parents = [{"sha": "previous-tip"}, {"sha": "feature-tip"}][:parent_count]
    api.side_effect = [[merged_pull], {"sha": "new-tip", "parents": parents}]
    assert not ci_run_policy.needs_full_suite("push", event, REPOSITORY)


@pytest.mark.parametrize("mismatch", ["open", "tip", "branch", "repository"])
def test_unrelated_pr_does_not_skip_tests(
    mismatch: str, event: dict[str, Any], merged_pull: dict[str, Any], api: Mock
) -> None:
    """Association alone is insufficient: require this exact completed merge."""
    if mismatch == "open":
        merged_pull["merged_at"] = None
    elif mismatch == "tip":
        merged_pull["merge_commit_sha"] = "other-tip"
    elif mismatch == "branch":
        merged_pull["base"]["ref"] = "main"
    else:
        merged_pull["base"]["repo"]["full_name"] = "someone/fork"
    api.return_value = [merged_pull]
    assert ci_run_policy.needs_full_suite("push", event, REPOSITORY)


@pytest.mark.parametrize("parent", ["intermediate-direct-commit", None])
def test_batched_or_unverifiable_push_retains_full_suite(
    parent: str | None, event: dict[str, Any], merged_pull: dict[str, Any], api: Mock
) -> None:
    """Never hide preceding direct changes in a push that ends with a PR merge."""
    parents = [{"sha": parent}] if parent else []
    api.side_effect = [[merged_pull], {"sha": "new-tip", "parents": parents}]
    assert ci_run_policy.needs_full_suite("push", event, REPOSITORY)


def test_force_push_retains_full_suite(event: dict[str, Any], api: Mock) -> None:
    """A rewritten branch must be checked even if it points to an old merge."""
    event["forced"] = True
    assert ci_run_policy.needs_full_suite("push", event, REPOSITORY)
    api.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("gh unavailable"),
        subprocess.CalledProcessError(1, ["gh", "api"]),
        subprocess.TimeoutExpired(["gh", "api"], 30),
        ValueError("invalid JSON"),
    ],
)
def test_api_failure_retains_full_suite(event: dict[str, Any], api: Mock, failure: Exception) -> None:
    """Missing permissions, unavailable APIs, and invalid data cannot disable CI."""
    api.side_effect = failure
    assert ci_run_policy.needs_full_suite("push", event, REPOSITORY)


@pytest.mark.parametrize("metadata", [None, {}, [None], [{"merged_at": "today", "base": None}]])
def test_malformed_metadata_retains_full_suite(event: dict[str, Any], api: Mock, metadata: Any) -> None:
    """Unexpected API response shapes conservatively retain validation."""
    api.return_value = metadata
    assert ci_run_policy.needs_full_suite("push", event, REPOSITORY)


@pytest.mark.parametrize("payload", ["invalid JSON", "{}"])
def test_cli_publishes_full_suite_on_missing_context(
    payload: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: Mock
) -> None:
    """Publish the safe default rather than leaving downstream jobs skipped."""
    event_path = tmp_path / "event.json"
    event_path.write_text(payload, encoding="utf-8")
    output_path = tmp_path / "output"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    ci_run_policy.main()
    assert output_path.read_text(encoding="utf-8") == "full_suite=true\n"
    api.assert_not_called()


def test_cli_publishes_post_merge_selection(
    event: dict[str, Any], merged_pull: dict[str, Any], api: Mock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pass the confirmed merge decision to the actual workflow output file."""
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    output_path = tmp_path / "output"
    api.side_effect = [[merged_pull], {"sha": "new-tip", "parents": [{"sha": "previous-tip"}]}]
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    ci_run_policy.main()
    assert output_path.read_text(encoding="utf-8") == "full_suite=false\n"


def test_workflow_preserves_pr_checks_and_falls_back_if_selection_fails() -> None:
    """Gate all expensive jobs while retaining final-content checks on every event."""
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert workflow["on"] == {"push": {"branches": ["main", "dev"]}, "pull_request": {"branches": ["main", "dev"]}}
    assert workflow["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": "true",
    }
    jobs = workflow["jobs"]
    assert "if" not in jobs["lint-and-registry"]
    assert "needs" not in jobs["lint-and-registry"]
    assert jobs["select-checks"]["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert jobs["select-checks"]["outputs"]["full_suite"] == "${{ steps.policy.outputs.full_suite }}"
    for name, job in jobs.items():
        if name in {"select-checks", "lint-and-registry"}:
            continue
        assert job["needs"] == "select-checks", name
        # An absent output (failed selector/checkout) must enable the jobs too;
        # the explicit status function overrides the default success() gate.
        assert job["if"] == "${{ !cancelled() && needs.select-checks.outputs.full_suite != 'false' }}", name
