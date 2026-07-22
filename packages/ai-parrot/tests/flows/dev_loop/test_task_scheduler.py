"""Unit tests for the deterministic dev-agent pool scheduler (FEAT-323 TASK-1858)."""

from __future__ import annotations

import json

import pytest

from parrot.flows.dev_loop.task_scheduler import TaskScheduler


@pytest.fixture
def index_file(tmp_path):
    def _make(tasks):
        p = tmp_path / "feature.json"
        p.write_text(
            json.dumps({"feature": "f", "feature_id": "FEAT-999", "tasks": tasks})
        )
        return p

    return _make


class TestWaves:
    def test_two_waves(self, index_file):
        p = index_file(
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
                {"id": "TASK-3", "status": "pending", "depends_on": ["TASK-1"]},
            ]
        )
        s = TaskScheduler.from_index_file(p)
        assert [t.id for t in s.next_wave()] == ["TASK-1"]
        s.mark_done("TASK-1")
        assert {t.id for t in s.next_wave()} == {"TASK-2", "TASK-3"}

    def test_wave_empty_when_nothing_dispatchable(self, index_file):
        p = index_file([{"id": "TASK-1", "status": "done", "depends_on": []}])
        s = TaskScheduler.from_index_file(p)
        assert s.next_wave() == []

    def test_cycle_raises(self, index_file):
        p = index_file(
            [
                {"id": "TASK-1", "status": "pending", "depends_on": ["TASK-2"]},
                {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
            ]
        )
        with pytest.raises(ValueError):
            TaskScheduler.from_index_file(p)

    def test_missing_index_returns_none(self, tmp_path):
        assert TaskScheduler.from_index_file(tmp_path / "nope.json") is None

    def test_corrupt_json_returns_none(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json")
        assert TaskScheduler.from_index_file(p) is None

    def test_done_status_counts_as_complete_at_construction(self, index_file):
        p = index_file(
            [
                {"id": "TASK-1", "status": "done", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
            ]
        )
        s = TaskScheduler.from_index_file(p)
        assert [t.id for t in s.next_wave()] == ["TASK-2"]

    def test_unknown_dependency_blocks_forever(self, index_file):
        p = index_file(
            [
                {"id": "TASK-1", "status": "pending", "depends_on": ["TASK-999"]},
            ]
        )
        s = TaskScheduler.from_index_file(p)
        assert s.next_wave() == []

    def test_mark_failed_skips_dependents_transitively(self, index_file):
        p = index_file(
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
                {"id": "TASK-3", "status": "pending", "depends_on": ["TASK-2"]},
            ]
        )
        s = TaskScheduler.from_index_file(p)
        s.mark_failed("TASK-1")
        assert {t.id for t in s.skipped()} == {"TASK-2", "TASK-3"}
        assert s.next_wave() == []
        assert [t.id for t in s.failed()] == ["TASK-1"]

    def test_pending_done_views(self, index_file):
        p = index_file(
            [
                {"id": "TASK-1", "status": "pending", "depends_on": []},
                {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
            ]
        )
        s = TaskScheduler.from_index_file(p)
        assert {t.id for t in s.pending()} == {"TASK-1", "TASK-2"}
        s.mark_done("TASK-1")
        assert {t.id for t in s.done()} == {"TASK-1"}
        assert {t.id for t in s.pending()} == {"TASK-2"}


class TestFromWorktree:
    def test_resolves_index_path(self, tmp_path):
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        index_dir.mkdir(parents=True)
        (index_dir / "my-feature.json").write_text(
            json.dumps(
                {
                    "feature": "my-feature",
                    "feature_id": "FEAT-1",
                    "tasks": [{"id": "TASK-1", "status": "pending", "depends_on": []}],
                }
            )
        )
        s = TaskScheduler.from_worktree(str(tmp_path), "my-feature")
        assert s is not None
        assert [t.id for t in s.next_wave()] == ["TASK-1"]

    def test_missing_worktree_index_returns_none(self, tmp_path):
        assert TaskScheduler.from_worktree(str(tmp_path), "nope") is None
