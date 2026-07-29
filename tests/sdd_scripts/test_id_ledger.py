from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdd.id_ledger import IdLedger, bootstrap_ledger, load_ledger, save_ledger


class TestIdLedgerModel:
    def test_ledger_roundtrip(self, tmp_path: Path) -> None:
        """save_ledger -> load_ledger is byte-for-byte stable."""
        ledger = IdLedger(
            next_task_id=2000,
            next_feature_id=400,
            updated_at="2026-07-28T00:00:00+00:00",
            updated_by="test",
        )
        path = tmp_path / "ledger.json"
        save_ledger(path, ledger)
        first_bytes = path.read_bytes()
        save_ledger(path, load_ledger(path))
        assert path.read_bytes() == first_bytes

    def test_ledger_rejects_non_positive_ids(self) -> None:
        with pytest.raises(Exception):
            IdLedger(next_task_id=0, next_feature_id=1, updated_at="x", updated_by="x")


class TestBootstrap:
    def test_bootstrap_seeds_ahead_of_existing_ids(self, tmp_path: Path) -> None:
        """Bootstrapping on a fixture repo with known max IDs seeds strictly ahead."""
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        specs_dir = tmp_path / "sdd" / "specs"
        index_dir.mkdir(parents=True)
        specs_dir.mkdir(parents=True)
        (index_dir / "example.json").write_text(
            '{"feature_id": "FEAT-042", "tasks": [{"id": "TASK-100"}, {"id": "TASK-101"}]}'
        )
        (specs_dir / "example.spec.md").write_text("**Feature ID**: FEAT-042\n")
        ledger = bootstrap_ledger(index_dir=index_dir, specs_dir=specs_dir)
        assert ledger.next_task_id >= 102
        assert ledger.next_feature_id >= 43

    def test_bootstrap_excludes_orphans_header_from_feature_scan(self, tmp_path: Path) -> None:
        """_orphans.json has no meaningful feature_id header and must not skew the FEAT max."""
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        specs_dir = tmp_path / "sdd" / "specs"
        index_dir.mkdir(parents=True)
        specs_dir.mkdir(parents=True)
        (index_dir / "example.json").write_text(
            '{"feature_id": "FEAT-010", "tasks": [{"id": "TASK-050"}]}'
        )
        (index_dir / "_orphans.json").write_text(
            '{"feature": "_orphans", "feature_id": null, "tasks": [{"id": "TASK-999"}]}'
        )
        ledger = bootstrap_ledger(index_dir=index_dir, specs_dir=specs_dir)
        # TASK counter must still see the orphan's TASK-999 (real task IDs).
        assert ledger.next_task_id >= 1000
        # FEAT counter must not be tripped up by the orphans' null feature_id.
        assert ledger.next_feature_id >= 11

    def test_bootstrap_on_live_repo_tree(self) -> None:
        """Bootstrapping against the real sdd/ tree seeds ahead of every real ID in use."""
        index_dir = Path("sdd/tasks/index")
        specs_dir = Path("sdd/specs")

        # Compute our own floor directly from the live tree instead of
        # hardcoding numbers that will drift as more features land.
        import json
        import re

        max_task = 0
        for f in index_dir.glob("*.json"):
            doc = json.loads(f.read_text(encoding="utf-8"))
            for t in doc.get("tasks", []) or []:
                m = re.match(r"TASK-(\d+)", t.get("id", ""))
                if m:
                    max_task = max(max_task, int(m.group(1)))

        max_feature = 0
        for f in index_dir.glob("*.json"):
            if f.name == "_orphans.json":
                continue
            doc = json.loads(f.read_text(encoding="utf-8"))
            fid = doc.get("feature_id")
            if isinstance(fid, str):
                m = re.match(r"FEAT-(\d+)", fid)
                if m:
                    max_feature = max(max_feature, int(m.group(1)))
        for f in specs_dir.glob("*.md"):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"\*\*Feature ID\*\*:\s*FEAT-(\d+)", text):
                max_feature = max(max_feature, int(m.group(1)))

        ledger = bootstrap_ledger(index_dir=index_dir, specs_dir=specs_dir)
        assert ledger.next_task_id >= max_task + 1
        assert ledger.next_feature_id >= max_feature + 1
