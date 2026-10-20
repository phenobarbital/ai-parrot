"""Tests for the ledger snapshot removal guard (FEAT-712)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.sdd.check_ledger_snapshot import (
    SnapshotRow,
    allowed_removals,
    find_violations,
    load_snapshot,
    main,
    read_base_snapshot,
)

SNAPSHOT = Path("sdd/ledger/issues.jsonl")


def _row(issue_id: str, status: str, title: str = "t") -> dict:
    """Build one snapshot row payload."""
    return {"issue_id": issue_id, "status": status, "title": title}


def _jsonl(*rows: dict) -> str:
    """Render rows the way export_snapshot does: sorted keys, one object per line."""
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _parsed(*rows: dict) -> dict[str, SnapshotRow]:
    return load_snapshot(_jsonl(*rows))


class TestFindViolations:
    """The decision table from spec §4 (U1-U7)."""

    def test_open_row_removed_is_a_violation(self) -> None:
        base = _parsed(_row("issue:a", "open", "leaky thing"))
        assert [v.issue_id for v in find_violations(base, {}, set())] == ["issue:a"]

    def test_claimed_row_removed_is_a_violation(self) -> None:
        base = _parsed(_row("issue:a", "claimed"))
        assert [v.issue_id for v in find_violations(base, {}, set())] == ["issue:a"]

    def test_closed_row_removed_is_legal_compaction(self) -> None:
        base = _parsed(_row("issue:a", "closed"))
        assert find_violations(base, {}, set()) == []

    def test_open_to_closed_transition_is_not_a_removal(self) -> None:
        base = _parsed(_row("issue:a", "open"))
        head = _parsed(_row("issue:a", "closed"))
        assert find_violations(base, head, set()) == []

    def test_allowed_id_is_not_a_violation(self) -> None:
        base = _parsed(_row("issue:a", "open"))
        assert find_violations(base, {}, {"issue:a"}) == []

    def test_added_rows_only_is_clean(self) -> None:
        base = _parsed(_row("issue:a", "open"))
        head = _parsed(_row("issue:a", "open"), _row("issue:b", "open"))
        assert find_violations(base, head, set()) == []

    def test_every_violation_is_reported_not_just_the_first(self) -> None:
        base = _parsed(
            _row("issue:c", "open"),
            _row("issue:a", "claimed"),
            _row("issue:b", "open"),
            _row("issue:d", "closed"),
        )
        assert [v.issue_id for v in find_violations(base, {}, set())] == [
            "issue:a",
            "issue:b",
            "issue:c",
        ]

    def test_violation_carries_status_and_title(self) -> None:
        base = _parsed(_row("issue:a", "claimed", "sl_run_sql leaks columns"))
        violation = find_violations(base, {}, set())[0]
        assert violation.status == "claimed"
        assert violation.title == "sl_run_sql leaks columns"


class TestLoadSnapshot:
    """Parsing rules (U8, U9)."""

    def test_blank_lines_are_ignored(self) -> None:
        text = _jsonl(_row("issue:a", "open")) + "\n   \n" + _jsonl(_row("issue:b", "open"))
        assert sorted(load_snapshot(text)) == ["issue:a", "issue:b"]

    def test_trailing_newline_is_fine(self) -> None:
        assert list(load_snapshot(_jsonl(_row("issue:a", "open")))) == ["issue:a"]

    def test_empty_text_is_an_empty_snapshot(self) -> None:
        assert load_snapshot("") == {}

    def test_malformed_json_names_the_line_number(self) -> None:
        text = _jsonl(_row("issue:a", "open")) + "{not json\n"
        with pytest.raises(ValueError, match="line 2"):
            load_snapshot(text)

    def test_row_without_issue_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="line 1"):
            load_snapshot(json.dumps({"status": "open"}) + "\n")

    def test_non_object_line_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="line 1"):
            load_snapshot("[1, 2]\n")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo carrying a base commit with a two-row snapshot."""
    root = tmp_path / "repo"
    (root / "sdd" / "ledger").mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)

    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True, text=True)
    # Set identity LOCALLY so a developer's global git config is never touched.
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    git("config", "commit.gpgsign", "false")
    (root / SNAPSHOT).write_text(_jsonl(_row("issue:a", "open"), _row("issue:b", "closed")))
    git("add", str(SNAPSHOT))
    git("commit", "-q", "-m", "base snapshot")
    git("branch", "-f", "base")
    return root


def _commit_snapshot(root: Path, text: str, message: str) -> None:
    (root / SNAPSHOT).write_text(text)
    subprocess.run(["git", "add", str(SNAPSHOT)], cwd=root, check=True, capture_output=True, text=True)
    # --allow-empty: a "nothing changed" commit is a legitimate case to test, and git
    # otherwise exits 1 when the snapshot is rewritten with identical content.
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", message],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


class TestMainInGitRepo:
    """End-to-end runs through main() against a real git history (I1-I4)."""

    def test_clean_commit_passes(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        _commit_snapshot(repo, _jsonl(_row("issue:a", "open"), _row("issue:b", "closed")), "no change")
        assert main(["--base-ref", "base"]) == 0

    def test_removing_an_open_row_fails(self, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.chdir(repo)
        _commit_snapshot(repo, _jsonl(_row("issue:b", "closed")), "drop an open issue")
        assert main(["--base-ref", "base"]) == 1
        assert "issue:a" in capsys.readouterr().err

    def test_removing_a_closed_row_passes(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        _commit_snapshot(repo, _jsonl(_row("issue:a", "open")), "compact a closed issue")
        assert main(["--base-ref", "base"]) == 0

    def test_trailer_authorizes_exactly_that_id(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        _commit_snapshot(
            repo,
            _jsonl(_row("issue:b", "closed")),
            "drop an open issue\n\nLedger-Removal: issue:a",
        )
        assert main(["--base-ref", "base"]) == 0

    def test_trailer_does_not_authorize_a_different_id(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        _commit_snapshot(repo, _jsonl(), "drop both\n\nLedger-Removal: issue:zzz")
        assert main(["--base-ref", "base"]) == 1

    def test_allow_flag_authorizes_a_removal(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        _commit_snapshot(repo, _jsonl(_row("issue:b", "closed")), "drop an open issue")
        assert main(["--base-ref", "base", "--allow", "issue:a"]) == 0

    def test_absent_base_snapshot_passes(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        assert main(["--base-ref", "base", "--snapshot", "sdd/ledger/issues.jsonl", "--allow", "x"]) == 0
        assert read_base_snapshot("base", Path("sdd/ledger/nonexistent.jsonl")) is None

    def test_unresolvable_base_ref_fails_closed(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        assert main(["--base-ref", "origin/never-fetched"]) == 1

    def test_malformed_head_snapshot_fails_closed(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        _commit_snapshot(repo, "{not json\n", "corrupt the snapshot")
        assert main(["--base-ref", "base"]) == 1

    def test_missing_head_snapshot_fails_closed(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        assert main(["--base-ref", "base", "--snapshot", "sdd/ledger/absent.jsonl"]) == 1

    def test_trailer_accepts_several_ids(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(repo)
        _commit_snapshot(repo, _jsonl(), "drop both\n\nLedger-Removal: issue:a, issue:b")
        assert allowed_removals("base") == {"issue:a", "issue:b"}
        assert main(["--base-ref", "base"]) == 0


def test_real_repo_snapshot_is_clean() -> None:
    """I5 / AC8: today's committed snapshot must not drop anything vs origin/dev."""
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "origin/dev^{commit}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("origin/dev is not available in this checkout")
    assert main(["--base-ref", "origin/dev"]) == 0


class TestCiWiring:
    """FEAT-712 AC10: the guard must actually run inside lint-and-registry."""

    @staticmethod
    def _guard_step() -> dict:
        yaml = pytest.importorskip("yaml")
        # Resolve from this file, never the cwd: pytest runs with the MAIN checkout as
        # its working directory even inside a worktree, so a relative path would check
        # the wrong tree's workflow and pass or fail for the wrong reason.
        repo_root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((repo_root / ".github/workflows/ci.yml").read_text())
        steps = workflow["jobs"]["lint-and-registry"]["steps"]
        matches = [s for s in steps if s.get("name") == "Check SDD ledger snapshot removals (FEAT-712)"]
        assert matches, f"guard step missing from lint-and-registry: {[s.get('name') for s in steps]}"
        return matches[0]

    def test_guard_step_is_registered_in_lint_and_registry(self) -> None:
        """Membership of THAT job, not mere presence somewhere in the file."""
        assert "check_ledger_snapshot" in self._guard_step()["run"]

    def test_guard_step_fetches_the_base_ref_first(self) -> None:
        """actions/checkout is depth-1 here, so the base ref must be fetched before the check."""
        run = self._guard_step()["run"]
        assert run.index("git fetch") < run.index("check_ledger_snapshot")

    def test_guard_step_falls_back_to_dev_off_pull_requests(self) -> None:
        """github.base_ref is empty on push events; the guard must still have a base."""
        assert "github.base_ref || 'dev'" in self._guard_step()["run"]
