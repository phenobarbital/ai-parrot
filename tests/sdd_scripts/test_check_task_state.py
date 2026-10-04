from __future__ import annotations

import json
from pathlib import Path

from scripts.sdd.check_task_state import find_violations, main


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    index_dir, active_dir, completed_dir = (tmp_path / d for d in ("index", "active", "completed"))
    for d in (index_dir, active_dir, completed_dir):
        d.mkdir()
    return index_dir, active_dir, completed_dir


def _write_index(index_dir: Path, feature: str, tasks: list[dict[str, str]]) -> None:
    (index_dir / f"{feature}.json").write_text(json.dumps({"feature": feature, "tasks": tasks}))


def _scan(tmp_path: Path):
    return find_violations(
        index_dir=tmp_path / "index", active_dir=tmp_path / "active", completed_dir=tmp_path / "completed"
    )


class TestFindViolations:
    def test_detects_twin(self, tmp_path: Path) -> None:
        _, active_dir, completed_dir = _layout(tmp_path)
        (active_dir / "TASK-100-foo.md").write_text("x")
        (completed_dir / "TASK-100-foo.md").write_text("x")
        violations = _scan(tmp_path)
        assert [(v.task_id, v.kind) for v in violations] == [("TASK-100", "twin")]

    def test_detects_closed_but_active(self, tmp_path: Path) -> None:
        index_dir, active_dir, _ = _layout(tmp_path)
        (active_dir / "TASK-101-bar.md").write_text("x")
        _write_index(
            index_dir,
            "feat-a",
            [{"id": "TASK-101", "status": "done", "file": "sdd/tasks/completed/TASK-101-bar.md"}],
        )
        violations = _scan(tmp_path)
        assert [(v.task_id, v.kind) for v in violations] == [("TASK-101", "closed-but-active")]

    def test_done_with_issues_counts_as_closed(self, tmp_path: Path) -> None:
        index_dir, active_dir, _ = _layout(tmp_path)
        (active_dir / "TASK-102-baz.md").write_text("x")
        _write_index(
            index_dir,
            "feat-a",
            [{"id": "TASK-102", "status": "done-with-issues", "file": "sdd/tasks/active/TASK-102-baz.md"}],
        )
        assert [v.kind for v in _scan(tmp_path)] == ["closed-but-active"]

    def test_pending_and_in_progress_are_not_flagged(self, tmp_path: Path) -> None:
        index_dir, active_dir, _ = _layout(tmp_path)
        (active_dir / "TASK-103-a.md").write_text("x")
        (active_dir / "TASK-104-b.md").write_text("x")
        _write_index(
            index_dir,
            "feat-a",
            [
                {"id": "TASK-103", "status": "pending", "file": "sdd/tasks/active/TASK-103-a.md"},
                {"id": "TASK-104", "status": "in-progress", "file": "sdd/tasks/active/TASK-104-b.md"},
            ],
        )
        assert _scan(tmp_path) == []

    def test_cross_feature_id_reuse_is_not_a_false_positive(self, tmp_path: Path) -> None:
        """A done TASK-105 of another feature with a different file must not flag this one."""
        index_dir, active_dir, _ = _layout(tmp_path)
        (active_dir / "TASK-105-new.md").write_text("x")
        _write_index(
            index_dir,
            "old-feature",
            [{"id": "TASK-105", "status": "done", "file": "sdd/tasks/completed/TASK-105-old.md"}],
        )
        assert _scan(tmp_path) == []


class TestMain:
    def test_fails_on_violation_and_honours_baseline(self, tmp_path: Path) -> None:
        _, active_dir, completed_dir = _layout(tmp_path)
        (active_dir / "TASK-200-x.md").write_text("x")
        (completed_dir / "TASK-200-x.md").write_text("x")
        dirs = [
            "--index-dir", str(tmp_path / "index"),
            "--active-dir", str(active_dir),
            "--completed-dir", str(completed_dir),
        ]  # fmt: skip
        assert main(dirs) == 1
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(["TASK-200-x.md"]))
        assert main([*dirs, "--baseline", str(baseline)]) == 0

    def test_baseline_does_not_hide_same_id_in_another_file(self, tmp_path: Path) -> None:
        """A baselined basename must not silence a new violation that reuses its TASK-ID."""
        _, active_dir, completed_dir = _layout(tmp_path)
        for name in ("TASK-300-old.md", "TASK-300-new.md"):
            (active_dir / name).write_text("x")
            (completed_dir / name).write_text("x")
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(["TASK-300-old.md"]))
        dirs = [
            "--index-dir", str(tmp_path / "index"),
            "--active-dir", str(active_dir),
            "--completed-dir", str(completed_dir),
        ]  # fmt: skip
        assert main([*dirs, "--baseline", str(baseline)]) == 1

    def test_clean_tree_passes(self, tmp_path: Path) -> None:
        _layout(tmp_path)
        assert main(
            ["--index-dir", str(tmp_path / "index"), "--active-dir", str(tmp_path / "active"),
             "--completed-dir", str(tmp_path / "completed")]
        ) == 0  # fmt: skip
