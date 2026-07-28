from __future__ import annotations

import json
from pathlib import Path

from scripts.sdd.check_id_collisions import find_collisions, main


def _write_index(path: Path, feature: str, feature_id: str, task_ids: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "feature": feature,
                "feature_id": feature_id,
                "tasks": [{"id": t, "feature": feature, "feature_id": feature_id} for t in task_ids],
            }
        )
    )


class TestFindCollisions:
    def test_detects_task_id_reuse(self, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        index_dir.mkdir()
        _write_index(index_dir / "feature-a.json", "feature-a", "FEAT-001", ["TASK-100"])
        _write_index(index_dir / "feature-b.json", "feature-b", "FEAT-002", ["TASK-100"])
        collisions = find_collisions(
            index_dir=index_dir,
            active_dir=tmp_path / "active",
            completed_dir=tmp_path / "completed",
            specs_dir=tmp_path / "specs",
        )
        task_collisions = [c for c in collisions if c.kind == "task"]
        assert len(task_collisions) == 1
        assert task_collisions[0].id == "TASK-100"
        assert set(task_collisions[0].slugs) == {"feature-a", "feature-b"}

    def test_tolerates_feature_id_reuse(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "a.spec.md").write_text("**Feature ID**: FEAT-380\n")
        (specs_dir / "b.spec.md").write_text("**Feature ID**: FEAT-380\n")
        collisions = find_collisions(
            index_dir=tmp_path / "index",
            active_dir=tmp_path / "active",
            completed_dir=tmp_path / "completed",
            specs_dir=specs_dir,
        )
        assert not any(c.kind == "task" for c in collisions)
        feature_reports = [c for c in collisions if c.kind == "feature"]
        assert len(feature_reports) == 1
        assert feature_reports[0].id == "FEAT-380"
        assert set(feature_reports[0].slugs) == {"a", "b"}

    def test_clean_repo_exits_zero(self, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        index_dir.mkdir()
        _write_index(index_dir / "feature-a.json", "feature-a", "FEAT-001", ["TASK-100"])
        _write_index(index_dir / "feature-b.json", "feature-b", "FEAT-002", ["TASK-200"])
        collisions = find_collisions(
            index_dir=index_dir,
            active_dir=tmp_path / "active",
            completed_dir=tmp_path / "completed",
            specs_dir=tmp_path / "specs",
        )
        assert not any(c.kind == "task" for c in collisions)

    def test_detects_collision_from_filenames_when_no_index(self, tmp_path: Path) -> None:
        """Collision detectable purely from active/ filenames, no index entries."""
        active_dir = tmp_path / "active"
        active_dir.mkdir()
        (active_dir / "TASK-500-feature-a-thing.md").write_text("# TASK-500\n")
        (active_dir / "TASK-500-feature-b-other-thing.md").write_text("# TASK-500\n")
        collisions = find_collisions(
            index_dir=tmp_path / "index",
            active_dir=active_dir,
            completed_dir=tmp_path / "completed",
            specs_dir=tmp_path / "specs",
        )
        task_collisions = [c for c in collisions if c.kind == "task"]
        assert len(task_collisions) == 1
        assert task_collisions[0].id == "TASK-500"

    def test_orphans_json_excluded_from_feature_header_but_tasks_still_scanned(
        self, tmp_path: Path
    ) -> None:
        index_dir = tmp_path / "index"
        index_dir.mkdir()
        (index_dir / "_orphans.json").write_text(
            json.dumps(
                {
                    "feature": "_orphans",
                    "feature_id": None,
                    "tasks": [{"id": "TASK-777", "feature": "orphan-feature"}],
                }
            )
        )
        _write_index(index_dir / "feature-a.json", "feature-a", "FEAT-001", ["TASK-777"])
        collisions = find_collisions(
            index_dir=index_dir,
            active_dir=tmp_path / "active",
            completed_dir=tmp_path / "completed",
            specs_dir=tmp_path / "specs",
        )
        task_collisions = [c for c in collisions if c.kind == "task"]
        assert len(task_collisions) == 1
        assert task_collisions[0].id == "TASK-777"
        assert set(task_collisions[0].slugs) == {"feature-a", "orphan-feature"}


class TestCli:
    def test_cli_exits_nonzero_on_collision(self, tmp_path: Path, capsys) -> None:
        index_dir = tmp_path / "index"
        index_dir.mkdir()
        _write_index(index_dir / "feature-a.json", "feature-a", "FEAT-001", ["TASK-100"])
        _write_index(index_dir / "feature-b.json", "feature-b", "FEAT-002", ["TASK-100"])

        exit_code = main(
            [
                "--index-dir",
                str(index_dir),
                "--active-dir",
                str(tmp_path / "active"),
                "--completed-dir",
                str(tmp_path / "completed"),
                "--specs-dir",
                str(tmp_path / "specs"),
            ]
        )
        assert exit_code == 1
        out = capsys.readouterr().out
        assert "TASK-100" in out
        assert "feature-a" in out
        assert "feature-b" in out

    def test_cli_exits_zero_on_clean_tree(self, tmp_path: Path, capsys) -> None:
        index_dir = tmp_path / "index"
        index_dir.mkdir()
        _write_index(index_dir / "feature-a.json", "feature-a", "FEAT-001", ["TASK-100"])

        exit_code = main(
            [
                "--index-dir",
                str(index_dir),
                "--active-dir",
                str(tmp_path / "active"),
                "--completed-dir",
                str(tmp_path / "completed"),
                "--specs-dir",
                str(tmp_path / "specs"),
            ]
        )
        assert exit_code == 0
