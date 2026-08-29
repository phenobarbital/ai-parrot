from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.sdd.id_ledger import LEDGER_PATH, IdLedger, load_ledger, save_ledger
from scripts.sdd.reserve_ids import IdReservationError, main, reserve_ids


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _dirty_tracked_file(clone: Path, name: str) -> None:
    """Commit ``name``, then modify it — an uncommitted change to a TRACKED
    file, which is what the dirty-tree guard exists to catch. Untracked
    files are deliberately ignored by it (see
    ``test_reserve_ids_ignores_untracked_files``).
    """
    (clone / name).write_text("committed\n", encoding="utf-8")
    _git(["add", name], clone)
    _git(["commit", "-m", f"add {name}"], clone)
    _git(["push", "origin", "dev"], clone)
    (clone / name).write_text("dirty\n", encoding="utf-8")


@pytest.fixture
def bare_remote_and_clone(tmp_path: Path):
    """A throwaway bare git 'origin' plus one clone, standing in for the
    real `dev` branch — lets reservation/retry tests exercise real
    `git fetch`/`git push` rejection semantics without touching the actual
    repository or network.
    """
    remote = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=dev", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(remote), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(["config", "user.email", "test@example.com"], clone)
    _git(["config", "user.name", "Test"], clone)

    ledger_path = clone / LEDGER_PATH
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    seed = IdLedger(
        next_task_id=1000,
        next_feature_id=100,
        updated_at="2026-07-28T00:00:00+00:00",
        updated_by="seed",
    )
    save_ledger(ledger_path, seed)
    _git(["add", str(LEDGER_PATH)], clone)
    _git(["commit", "-m", "seed ledger"], clone)
    _git(["push", "origin", "dev"], clone)

    return remote, clone


class TestReserveIds:
    def test_reserve_ids_happy_path(self, bare_remote_and_clone) -> None:
        remote, clone = bare_remote_and_clone
        reservation = reserve_ids("task", 3, "dev", "test-feature", repo_root=clone)
        assert reservation.kind == "task"
        assert reservation.count == 3
        assert reservation.first_id == 1000
        assert reservation.ids == ["TASK-1000", "TASK-1001", "TASK-1002"]

        ledger = load_ledger(clone / LEDGER_PATH)
        assert ledger.next_task_id == 1003

    def test_reserve_ids_retries_on_non_fast_forward(
        self, bare_remote_and_clone, tmp_path: Path
    ) -> None:
        """A second clone racing the first must never get overlapping IDs."""
        remote, clone_a = bare_remote_and_clone
        clone_b = tmp_path / "clone_b"
        subprocess.run(
            ["git", "clone", str(remote), str(clone_b)],
            check=True,
            capture_output=True,
            text=True,
        )
        _git(["config", "user.email", "test-b@example.com"], clone_b)
        _git(["config", "user.name", "Test B"], clone_b)

        # clone_a wins the race first (its local view is already in sync
        # with origin/dev at reservation time).
        reservation_a = reserve_ids("task", 2, "dev", "feature-a", repo_root=clone_a)
        assert reservation_a.ids == ["TASK-1000", "TASK-1001"]

        # clone_b was cloned BEFORE clone_a's push, so its local ledger is
        # now stale relative to origin/dev — its first push attempt must be
        # rejected, then it fetches/recomputes and succeeds with the next
        # available range, never overlapping clone_a's reservation.
        sleeps: list[float] = []
        reservation_b = reserve_ids(
            "task",
            2,
            "dev",
            "feature-b",
            repo_root=clone_b,
            sleep_fn=sleeps.append,
        )
        assert reservation_b.ids == ["TASK-1002", "TASK-1003"]
        assert not set(reservation_a.ids) & set(reservation_b.ids)
        assert len(sleeps) >= 1  # at least one retry occurred

    def test_reserve_ids_raises_after_max_retries(
        self, bare_remote_and_clone, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every push attempt rejected -> IdReservationError, not a hang."""
        remote, clone = bare_remote_and_clone
        original_run = subprocess.run

        class _RejectedPush:
            returncode = 1
            stdout = ""
            stderr = "! [rejected]        HEAD -> dev (fetch first)\n"

        def _fake_run(args, *a, **kw):
            if args[:2] == ["git", "push"]:
                return _RejectedPush()
            return original_run(args, *a, **kw)

        monkeypatch.setattr(subprocess, "run", _fake_run)

        with pytest.raises(IdReservationError):
            reserve_ids(
                "task",
                1,
                "dev",
                "feature-c",
                repo_root=clone,
                max_retries=2,
                sleep_fn=lambda _seconds: None,
            )

    def test_reserve_ids_commit_touches_only_ledger(
        self, bare_remote_and_clone
    ) -> None:
        """The reservation commit must stage exactly one file."""
        remote, clone = bare_remote_and_clone
        reserve_ids("task", 1, "dev", "feature-d", repo_root=clone)

        show = subprocess.run(
            ["git", "show", "--stat", "--name-only", "--format=", "HEAD"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        )
        files = [line for line in show.stdout.splitlines() if line.strip()]
        assert files == [str(LEDGER_PATH)]

    def test_reserve_ids_rejects_non_positive_count(
        self, bare_remote_and_clone
    ) -> None:
        """A non-positive count must never be allowed to rewind the ledger."""
        remote, clone = bare_remote_and_clone

        with pytest.raises(ValueError):
            reserve_ids("task", 0, "dev", "feature-e", repo_root=clone)
        with pytest.raises(ValueError):
            reserve_ids("task", -3, "dev", "feature-e", repo_root=clone)

        # Ledger must be untouched — no commit/push attempted.
        ledger = load_ledger(clone / LEDGER_PATH)
        assert ledger.next_task_id == 1000

    def test_reserve_ids_refuses_when_working_tree_dirty(
        self, bare_remote_and_clone
    ) -> None:
        """The library function itself (not just the CLI) must refuse a dirty tree."""
        remote, clone = bare_remote_and_clone
        _dirty_tracked_file(clone, "unrelated.txt")

        with pytest.raises(IdReservationError, match="uncommitted changes"):
            reserve_ids("task", 1, "dev", "feature-f", repo_root=clone)

        ledger = load_ledger(clone / LEDGER_PATH)
        assert ledger.next_task_id == 1000

    def test_reserve_ids_ignores_untracked_files(self, bare_remote_and_clone) -> None:
        """Untracked files never block a reservation — nothing here can clobber them."""
        remote, clone = bare_remote_and_clone
        (clone / "scratch.txt").write_text("untracked\n", encoding="utf-8")

        reservation = reserve_ids("task", 1, "dev", "feature-i", repo_root=clone)

        assert reservation.ids == ["TASK-1000"]
        assert (clone / "scratch.txt").read_text(encoding="utf-8") == "untracked\n"

    def test_reserve_ids_refuses_on_branch_mismatch(
        self, bare_remote_and_clone
    ) -> None:
        """Must refuse if the checked-out branch does not match base_branch."""
        remote, clone = bare_remote_and_clone
        _git(["checkout", "-b", "some-other-branch"], clone)

        with pytest.raises(IdReservationError, match="does not match"):
            reserve_ids("task", 1, "dev", "feature-g", repo_root=clone)


class TestReserveIdsCli:
    def test_cli_prints_reserved_ids_and_exits_zero(
        self, bare_remote_and_clone, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        remote, clone = bare_remote_and_clone
        monkeypatch.chdir(clone)

        exit_code = main(["--kind", "task", "--count", "2", "--base-branch", "dev", "--label", "cli-test"])

        assert exit_code == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert out == ["TASK-1000", "TASK-1001"]

    def test_cli_refuses_when_working_tree_dirty(
        self, bare_remote_and_clone, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        remote, clone = bare_remote_and_clone
        monkeypatch.chdir(clone)
        _dirty_tracked_file(clone, "unrelated.txt")

        exit_code = main(["--kind", "task", "--count", "1", "--base-branch", "dev", "--label", "cli-test"])

        assert exit_code == 1
        err = capsys.readouterr().err
        assert "refusing to run" in err


class TestReserveIdsNeverDestroysLocalWork:
    """Regression tests for the FEAT-387 allocator's destructive retry path.

    ``reserve_ids()`` used to commit on top of whatever local HEAD it found
    and push the WHOLE branch (``HEAD:<base>``); on a lost race it ran
    ``git reset --hard origin/<base>``, which silently discarded every
    local-only commit on the base branch and still exited 0. The
    reservation must be a compare-and-swap against ``origin/<base>``
    alone — it must never publish, and never destroy, unrelated local
    commits.
    """

    @staticmethod
    def _add_local_commit(clone: Path, name: str) -> str:
        """Commit an unpushed, unrelated change and return its sha."""
        (clone / name).write_text("local work\n", encoding="utf-8")
        _git(["add", name], clone)
        _git(["commit", "-m", f"local work: {name}"], clone)
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    @staticmethod
    def _remote_shas(remote: Path, branch: str = "dev") -> list[str]:
        result = subprocess.run(
            ["git", "rev-list", branch],
            cwd=remote,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.split()

    def test_losing_the_race_preserves_unpushed_local_commits(
        self, bare_remote_and_clone, tmp_path: Path
    ) -> None:
        """A rejected push must not discard local-only commits on the base branch."""
        remote, clone_a = bare_remote_and_clone
        clone_b = tmp_path / "clone_b"
        subprocess.run(
            ["git", "clone", str(remote), str(clone_b)],
            check=True,
            capture_output=True,
            text=True,
        )
        _git(["config", "user.email", "test-b@example.com"], clone_b)
        _git(["config", "user.name", "Test B"], clone_b)

        # clone_b carries two unpushed commits of real work on dev.
        first_sha = self._add_local_commit(clone_b, "work_one.txt")
        second_sha = self._add_local_commit(clone_b, "work_two.txt")

        # clone_a wins the race, making clone_b's view of the ledger stale.
        reserve_ids("task", 2, "dev", "feature-a", repo_root=clone_a)

        sleeps: list[float] = []
        reservation_b = reserve_ids(
            "task",
            2,
            "dev",
            "feature-b",
            repo_root=clone_b,
            sleep_fn=sleeps.append,
        )

        assert reservation_b.ids == ["TASK-1002", "TASK-1003"]
        assert len(sleeps) >= 1, "expected the stale clone to lose a race first"

        # Both local commits must still be reachable from clone_b's HEAD.
        log = subprocess.run(
            ["git", "rev-list", "HEAD"],
            cwd=clone_b,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert first_sha in log
        assert second_sha in log
        assert (clone_b / "work_one.txt").exists()
        assert (clone_b / "work_two.txt").exists()

    def test_reservation_does_not_publish_unpushed_local_commits(
        self, bare_remote_and_clone
    ) -> None:
        """The ledger push must carry the ledger commit only, never local work."""
        remote, clone = bare_remote_and_clone
        local_sha = self._add_local_commit(clone, "unpublished.txt")

        reservation = reserve_ids("task", 1, "dev", "feature-h", repo_root=clone)

        assert reservation.ids == ["TASK-1000"]
        assert local_sha not in self._remote_shas(remote), (
            "reserve_ids published an unrelated local commit to origin/dev"
        )
        # …and the reservation itself still landed on the remote.
        remote_ledger = subprocess.run(
            ["git", "show", "dev:" + str(LEDGER_PATH)],
            cwd=remote,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert '"next_task_id": 1001' in remote_ledger

    def test_unpushable_local_branch_is_left_alone_with_a_warning(
        self, bare_remote_and_clone, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Local commits block the courtesy fast-forward — warn, never rewrite."""
        remote, clone = bare_remote_and_clone
        local_sha = self._add_local_commit(clone, "in_progress.txt")

        reserve_ids("task", 1, "dev", "feature-j", repo_root=clone)

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert head == local_sha, "local branch was moved despite unpushed commits"

        err = capsys.readouterr().err
        assert "could not be fast-forwarded" in err
        assert "your local commits are intact" in err.lower()
