"""Canonical integration of sealed ledger batches into origin/dev (FEAT-758 Module 2)."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps
from parrot.knowledge.wiki.ledger.outbox import (
    LedgerBatch,
    LedgerDeliveryConflict,
    LedgerDeliveryReport,
    LedgerOutbox,
    StrictLedgerReadError,
    read_strict_events,
)
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.shared_log import ARCHIVE_REL_DIR, SHARED_LOG_REL_PATH, shared_log_files
from parrot.knowledge.wiki.store import WikiStoreBusy

logger = logging.getLogger(__name__)

TERMINAL = frozenset({"closed", "superseded"})


class MergePlan(BaseModel):
    """Events to append to the destination log, in captured order."""

    new_lines: list[bytes] = Field(default_factory=list)
    new_events: list[LedgerEvent] = Field(default_factory=list)
    duplicates: int = 0


def _canonical(event: LedgerEvent) -> str:
    """Return the canonical serialized representation of an event."""
    return canonical_json_dumps(event.model_dump())


def read_logical_log(repo_root: Path) -> list[tuple[bytes, LedgerEvent]]:
    """Strictly read archives and current log in ``shared_log_files`` order."""
    result: list[tuple[bytes, LedgerEvent]] = []
    known: dict[str, str] = {}
    for path in shared_log_files(repo_root):
        strict_read = read_strict_events(path)
        if strict_read.truncated_tail:
            raise StrictLedgerReadError(f"{path}: committed log has a truncated tail")
        for raw_line, event in zip(strict_read.raw_lines, strict_read.events, strict=True):
            canonical = _canonical(event)
            previous = known.get(event.event_id)
            if previous is None:
                known[event.event_id] = canonical
                result.append((raw_line, event))
            elif previous != canonical:
                raise StrictLedgerReadError(f"event {event.event_id!r} has conflicting canonical content")
    return result


def merge_batch(remote: Sequence[tuple[bytes, LedgerEvent]], batch: Sequence[tuple[bytes, LedgerEvent]]) -> MergePlan:
    """Return batch events absent from ``remote``; reject equal ids with different content."""
    remote_by_id = {event.event_id: _canonical(event) for _, event in remote}
    plan = MergePlan()
    for raw_line, event in batch:
        remote_content = remote_by_id.get(event.event_id)
        if remote_content is None:
            plan.new_lines.append(raw_line)
            plan.new_events.append(event)
        elif remote_content == _canonical(event):
            plan.duplicates += 1
        else:
            raise StrictLedgerReadError(f"event {event.event_id!r} has conflicting canonical content")
    return plan


def find_transition_conflicts(
    remote: Sequence[LedgerEvent], new: Sequence[LedgerEvent]
) -> list[LedgerDeliveryConflict]:
    """Replay ``remote`` then check each ``new`` issue event against its preceding state."""
    state: dict[str, dict[str, Any]] = {}
    conflicts: list[LedgerDeliveryConflict] = []
    for event in remote:
        _apply(state, event)

    for event in new:
        if event.kind.startswith("issue."):
            current = state.get(event.subject)
            reason: str | None = None
            if event.kind != "issue.opened" and current is None:
                reason = "missing-predecessor"
            elif event.kind == "issue.claimed" and current["status"] == "claimed":
                if current["claimed_by"] != event.payload.get("claimed_by"):
                    reason = "competing-claim"
            elif event.kind == "issue.closed" and current["status"] in TERMINAL:
                evidence = (
                    event.payload.get("closed_by"),
                    event.payload.get("reason"),
                    event.payload.get("resolved_by"),
                )
                if current["close"] != evidence:
                    reason = "conflicting-close"
            elif event.kind == "issue.unclaimed" and current["status"] in TERMINAL:
                reason = "unclaim-terminal"

            if reason is not None:
                conflicts.append(LedgerDeliveryConflict(event_id=event.event_id, subject=event.subject, reason=reason))
        _apply(state, event)
    return conflicts


def _apply(state: dict[str, dict[str, Any]], event: LedgerEvent) -> None:
    """Mirror the live reducer for status, claim owner, and close evidence."""
    if not event.kind.startswith("issue."):
        return
    current = state.get(event.subject)
    if event.kind == "issue.opened":
        if current is None:
            state[event.subject] = {"status": "open", "claimed_by": None, "close": None}
    elif event.kind == "issue.claimed" and current is not None and current["status"] == "open":
        current["status"] = "claimed"
        current["claimed_by"] = event.payload.get("claimed_by")
    elif event.kind == "issue.unclaimed" and current is not None and current["status"] == "claimed":
        current["status"] = "open"
        current["claimed_by"] = None
    elif event.kind == "issue.closed" and current is not None:
        current["status"] = "closed"
        current["close"] = (
            event.payload.get("closed_by"),
            event.payload.get("reason"),
            event.payload.get("resolved_by"),
        )
    elif event.kind == "issue.superseded" and current is not None:
        current["status"] = "superseded"


async def build_scratch_snapshot(merged: Sequence[bytes], *, scratch_dir: Path, dest: Path) -> bool:
    """Replay ``merged`` raw lines in an isolated ledger and export ``dest``."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    data = b"".join(line + b"\n" for line in merged)
    await asyncio.to_thread((scratch_dir / "events.jsonl").write_bytes, data)
    service = LedgerService.from_dir(scratch_dir)
    await service.index.sync()
    changed = await service.export_snapshot(dest, reconcile=True)
    logger.debug("Scratch ledger snapshot %s (changed=%s) from %d events", dest, changed, len(merged))
    return changed


class GitResult(BaseModel):
    """The decoded result of one bounded git subprocess."""

    returncode: int
    stdout: str
    stderr: str


async def _git(*args: str, cwd: Path, timeout: float = 120.0) -> GitResult:
    """Run one git command without blocking the loop; a timeout yields returncode -1."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(cwd),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return GitResult(returncode=-1, stdout="", stderr=f"git {' '.join(args)} timed out")
    return GitResult(returncode=proc.returncode or 0, stdout=out.decode(), stderr=err.decode())


class IntegrationError(RuntimeError):
    """The local repository cannot safely perform a ledger delivery."""


ALLOWLIST: tuple[str, ...] = (str(SHARED_LOG_REL_PATH), "sdd/ledger/issues.jsonl")
_NON_FF_MARKERS: tuple[str, ...] = ("non-fast-forward", "fetch first", "[rejected]")


class LedgerIntegrator:
    """Deliver immutable batches to origin/dev without touching active checkouts."""

    def __init__(self, repo_root: Path, outbox: LedgerOutbox, *, remote: str = "origin") -> None:
        """Bind repository identity and local outbox; destination is origin/dev."""
        self.repo_root = Path(repo_root).resolve()
        self.outbox = outbox
        self.remote = remote
        self.branch = "dev"
        self.logger = logging.getLogger(__name__)

    async def _primary_root(self) -> Path:
        """Return the primary checkout that owns this repository's common git dir."""
        result = await _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=self.repo_root)
        if result.returncode != 0:
            raise IntegrationError("not-a-git-repo")
        return Path(result.stdout.strip()).parent

    async def remote_event_ids(self) -> set[str]:
        """Fetch origin/dev and return every event id in its archives and current log."""
        fetched = await _git("fetch", self.remote, self.branch, cwd=self.repo_root)
        if fetched.returncode != 0:
            raise IntegrationError("fetch-failed")
        ref = f"{self.remote}/{self.branch}"
        listed = await _git("ls-tree", "-r", "--name-only", ref, "--", "sdd/ledger", cwd=self.repo_root)
        if listed.returncode != 0:
            raise IntegrationError("remote-log-unavailable")
        paths = [
            path
            for path in listed.stdout.splitlines()
            if path == str(SHARED_LOG_REL_PATH)
            or (path.startswith(f"{ARCHIVE_REL_DIR}/") and Path(path).name.startswith("events-"))
        ]
        result: set[str] = set()
        for path in sorted(paths, key=lambda value: (value == str(SHARED_LOG_REL_PATH), value)):
            shown = await _git("show", f"{ref}:{path}", cwd=self.repo_root)
            if shown.returncode != 0:
                raise IntegrationError("remote-log-unavailable")
            for line in shown.stdout.splitlines():
                if line.strip():
                    try:
                        event_id = json.loads(line)["event_id"]
                    except (KeyError, TypeError, json.JSONDecodeError) as exc:
                        raise IntegrationError("remote-log-invalid") from exc
                    if not isinstance(event_id, str):
                        raise IntegrationError("remote-log-invalid")
                    result.add(event_id)
        return result

    async def integrate(self, batch: LedgerBatch, *, max_attempts: int = 3) -> LedgerDeliveryReport:
        """Recompute after rejected pushes; acknowledge only matching remote event content."""
        if batch.remote != self.remote or batch.branch != self.branch:
            return LedgerDeliveryReport(
                status="unsupported",
                batch_id=batch.batch_id,
                attempts=0,
                remote_head=None,
                commit_sha=None,
                added=0,
                remaining=len(batch.event_ids),
                error_code="destination-mismatch",
            )
        self.outbox.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.outbox.root / f"integrate-{self.remote}-{self.branch}.lock"
        with lock_path.open("a+b") as lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                return LedgerDeliveryReport(
                    status="pending",
                    batch_id=batch.batch_id,
                    attempts=0,
                    remote_head=None,
                    commit_sha=None,
                    added=0,
                    remaining=len(batch.event_ids),
                    error_code="integration-locked",
                )
            try:
                for attempt in range(1, max_attempts + 1):
                    report = await self._attempt(batch, attempt)
                    if report is not None:
                        return report
                return LedgerDeliveryReport(
                    status="pending",
                    batch_id=batch.batch_id,
                    attempts=max_attempts,
                    remote_head=None,
                    commit_sha=None,
                    added=0,
                    remaining=len(batch.event_ids),
                    error_code="retry-exhausted",
                )
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    async def _remove_if_clean(self, path: Path) -> str | None:
        """Remove one owned worktree only after proving it has no uncommitted changes."""
        status = await _git("status", "--porcelain", cwd=path)
        if status.returncode != 0 or status.stdout.strip():
            return str(path)
        removed = await _git("worktree", "remove", str(path), cwd=self.repo_root)
        return None if removed.returncode == 0 else str(path)

    async def _attempt(self, batch: LedgerBatch, attempt: int) -> LedgerDeliveryReport | None:
        """Perform one fresh-base attempt; ``None`` denotes a non-fast-forward retry."""
        fetched = await _git("fetch", self.remote, self.branch, cwd=self.repo_root)
        if fetched.returncode != 0:
            return LedgerDeliveryReport(
                status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=None,
                added=0, remaining=len(batch.event_ids), error_code="push-failed"
            )
        remote_ref = f"refs/remotes/{self.remote}/{self.branch}"
        base = await _git("rev-parse", remote_ref, cwd=self.repo_root)
        if base.returncode != 0:
            return LedgerDeliveryReport(
                status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=None,
                added=0, remaining=len(batch.event_ids), error_code="push-failed"
            )
        base_sha = base.stdout.strip()
        primary = await self._primary_root()
        tmp = primary / ".claude" / "worktrees" / f"_ledger-outbox-{uuid.uuid4()}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        added = await _git("worktree", "add", "--detach", str(tmp), base_sha, cwd=self.repo_root)
        if added.returncode != 0:
            return LedgerDeliveryReport(
                status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=None,
                added=0, remaining=len(batch.event_ids), error_code="push-failed"
            )
        try:
            try:
                remote_log = read_logical_log(tmp)
                sealed = await self.outbox.batch_events(batch)
                plan = merge_batch(remote_log, list(zip(sealed.raw_lines, sealed.events, strict=True)))
            except StrictLedgerReadError:
                recovery = await self._remove_if_clean(tmp)
                return LedgerDeliveryReport(
                    status="conflict", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=None,
                    added=0, remaining=len(batch.event_ids), error_code="invalid-content", recovery_path=recovery
                )
            conflicts = find_transition_conflicts([event for _, event in remote_log], plan.new_events)
            if conflicts:
                recovery = await self._remove_if_clean(tmp)
                return LedgerDeliveryReport(
                    status="conflict", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=None,
                    added=0, remaining=len(batch.event_ids), conflicts=conflicts, recovery_path=recovery
                )
            commit_sha: str | None = None
            delivery_status = "already_delivered" if not plan.new_lines else "delivered"
            if plan.new_lines:
                events_path = tmp / SHARED_LOG_REL_PATH
                events_path.parent.mkdir(parents=True, exist_ok=True)
                separator = b""
                if events_path.exists() and events_path.stat().st_size and not events_path.read_bytes().endswith(b"\n"):
                    separator = b"\n"
                with events_path.open("ab") as handle:
                    handle.write(separator + b"".join(line + b"\n" for line in plan.new_lines))
                try:
                    await build_scratch_snapshot(
                        [raw for raw, _ in remote_log] + plan.new_lines,
                        scratch_dir=self.outbox.root / "scratch" / str(uuid.uuid4()),
                        dest=tmp / "sdd" / "ledger" / "issues.jsonl",
                    )
                except WikiStoreBusy:
                    recovery = await self._remove_if_clean(tmp)
                    return LedgerDeliveryReport(
                        status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=None,
                        added=0, remaining=len(batch.event_ids), error_code="index-busy", recovery_path=recovery
                    )
                committed = await _git("add", "--", *ALLOWLIST, cwd=tmp)
                if committed.returncode != 0:
                    recovery = await self._remove_if_clean(tmp)
                    return LedgerDeliveryReport(
                        status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=None,
                        added=0, remaining=len(batch.event_ids), error_code="push-failed", recovery_path=recovery
                    )
                committed = await _git("commit", "-m", f"sdd: ledger delivery {batch.batch_id}", cwd=tmp)
                if committed.returncode != 0:
                    recovery = await self._remove_if_clean(tmp)
                    return LedgerDeliveryReport(
                        status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=None,
                        added=0, remaining=len(batch.event_ids), error_code="push-failed", recovery_path=recovery
                    )
                head = await _git("rev-parse", "HEAD", cwd=tmp)
                parent = await _git("rev-parse", "HEAD^", cwd=tmp)
                changed = await _git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", cwd=tmp)
                status = await _git("status", "--porcelain", cwd=tmp)
                hashes_match = True
                for path in ALLOWLIST:
                    tree_hash = await _git("rev-parse", f"HEAD:{path}", cwd=tmp)
                    disk_hash = await _git("hash-object", str(tmp / path), cwd=tmp)
                    hashes_match = hashes_match and tree_hash.returncode == 0 and disk_hash.returncode == 0 and tree_hash.stdout.strip() == disk_hash.stdout.strip()
                changed_paths = {path for path in changed.stdout.splitlines() if path}
                if (
                    head.returncode != 0
                    or parent.returncode != 0
                    or parent.stdout.strip() != base_sha
                    or not changed_paths.issubset(ALLOWLIST)
                    or status.stdout.strip()
                    or not hashes_match
                ):
                    return LedgerDeliveryReport(
                        status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None,
                        commit_sha=head.stdout.strip() if head.returncode == 0 else None, added=0,
                        remaining=len(batch.event_ids), error_code="hook-mutated-commit", recovery_path=str(tmp)
                    )
                commit_sha = head.stdout.strip()
                pushed = await _git("push", self.remote, "HEAD:refs/heads/dev", cwd=tmp)
                if pushed.returncode != 0:
                    if any(marker in pushed.stderr.lower() for marker in _NON_FF_MARKERS):
                        await self._remove_if_clean(tmp)
                        return None
                    return LedgerDeliveryReport(
                        status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=commit_sha,
                        added=len(plan.new_lines), remaining=len(batch.event_ids), error_code="push-failed", recovery_path=str(tmp)
                    )
            refreshed = await _git("fetch", self.remote, self.branch, cwd=tmp)
            checked_out = await _git("checkout", "--detach", f"{self.remote}/{self.branch}", cwd=tmp)
            if refreshed.returncode != 0 or checked_out.returncode != 0:
                return LedgerDeliveryReport(
                    status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=commit_sha,
                    added=len(plan.new_lines), remaining=len(batch.event_ids), error_code="push-failed", recovery_path=str(tmp)
                )
            verified_log = read_logical_log(tmp)
            verified_by_id = {event.event_id: _canonical(event) for _, event in verified_log}
            expected = {event.event_id: _canonical(event) for event in sealed.events}
            if any(verified_by_id.get(event_id) != canonical for event_id, canonical in expected.items()):
                return LedgerDeliveryReport(
                    status="pending", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=commit_sha,
                    added=len(plan.new_lines), remaining=len(batch.event_ids), error_code="push-failed", recovery_path=str(tmp)
                )
            remote_head_result = await _git("rev-parse", "HEAD", cwd=tmp)
            remote_head = remote_head_result.stdout.strip()
            verified_digest = hashlib.sha256(
                "".join(f"{event.event_id}\0{_canonical(event)}\n" for event in sealed.events).encode("utf-8")
            ).hexdigest()
            await self.outbox.acknowledge(batch, remote_head=remote_head, verified_digest=verified_digest)
            remaining_status = await self.outbox.status(known_ids=set(verified_by_id))
            remaining = max(0, int(remaining_status["pending_events"]) + int(remaining_status["unsealed_events"]) - len(batch.event_ids))
            self.logger.info("ledger delivery attempt=%d base=%s added=%d", attempt, base_sha, len(plan.new_lines))
            recovery = await self._remove_if_clean(tmp)
            return LedgerDeliveryReport(
                status=delivery_status, batch_id=batch.batch_id, attempts=attempt, remote_head=remote_head,
                commit_sha=commit_sha, added=len(plan.new_lines), remaining=remaining, recovery_path=recovery
            )
        except StrictLedgerReadError:
            return LedgerDeliveryReport(
                status="conflict", batch_id=batch.batch_id, attempts=attempt, remote_head=None, commit_sha=None,
                added=0, remaining=len(batch.event_ids), error_code="invalid-content", recovery_path=str(tmp)
            )

    async def check_feature_diff(self, feature_ref: str) -> list[str]:
        """List canonical ledger paths changed since merge-base with origin/dev; never edit them."""
        base = await _git("merge-base", f"{self.remote}/{self.branch}", feature_ref, cwd=self.repo_root)
        if base.returncode != 0:
            raise IntegrationError("merge-base-failed")
        changed = await _git(
            "diff", "--name-only", base.stdout.strip(), feature_ref, "--", *ALLOWLIST, cwd=self.repo_root
        )
        if changed.returncode != 0:
            raise IntegrationError("feature-diff-failed")
        return sorted(path for path in changed.stdout.splitlines() if path)
