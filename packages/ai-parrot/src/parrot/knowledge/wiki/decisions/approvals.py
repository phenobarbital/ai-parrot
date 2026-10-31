"""Approval manifest and git-commit trust adapter (FEAT-784 Module 3)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, ValidationError

from parrot.knowledge.wiki.decisions.models import (
    APPROVAL_LOCAL_BASE,
    APPROVAL_MANIFEST_INVALID,
    APPROVAL_UNVERIFIED,
    DecisionDiagnostic,
    DecisionError,
    DecisionRef,
    _Strict,
)
from parrot.knowledge.wiki.decisions.spec_entries import (
    DECISIONS_HEADING,
    SEED_HEADING,
    canonical_block_bytes,
    parse_spec_decisions,
)


class ApprovalEntry(_Strict):
    """One append-only approval event."""

    kind: Literal["spec", "seed", "retirement", "waiver"]
    batch_id: str = Field(..., min_length=1)
    spec_path: str = Field(..., min_length=1)
    document_id: str = Field(..., min_length=1)
    entries: list[DecisionRef]
    block_sha256: str
    commit: str = Field(..., min_length=7)
    actor: str = Field(..., min_length=1)
    recorded_at: str = Field(..., min_length=1)


class ApprovalManifest:
    """Parsed ``sdd/decisions/approvals.jsonl`` (append-only)."""

    def __init__(self, entries: list[ApprovalEntry], raw: bytes) -> None:
        self.entries = entries
        self._raw = raw

    @classmethod
    def load(cls, path: Path) -> "ApprovalManifest":
        """Load JSONL and reject malformed or duplicate approval batches."""
        if not path.exists():
            return cls([], b"")
        raw = path.read_bytes()
        entries: list[ApprovalEntry] = []
        for lineno, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                entries.append(ApprovalEntry.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise DecisionError(APPROVAL_MANIFEST_INVALID, f"{path}:{lineno}: {exc}") from exc

        approval_batch_ids = [entry.batch_id for entry in entries if entry.kind in {"spec", "seed"}]
        duplicate_batch_ids = sorted(
            {batch_id for batch_id in approval_batch_ids if approval_batch_ids.count(batch_id) > 1}
        )
        if duplicate_batch_ids:
            raise DecisionError(
                APPROVAL_MANIFEST_INVALID,
                f"{path}: duplicate spec/seed approval batch_id(s): {', '.join(duplicate_batch_ids)}",
            )
        return cls(entries, raw)

    def for_document(self, document_id: str) -> list[ApprovalEntry]:
        """Return entries for one document, in file order."""
        return [entry for entry in self.entries if entry.document_id == document_id]

    def digest(self) -> str:
        """Return the sha256 digest of raw manifest bytes."""
        return hashlib.sha256(self._raw).hexdigest()


class ApprovalAdapter(Protocol):
    """Pluggable trust check for an approval entry."""

    async def verify(self, entry: ApprovalEntry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]:
        """Verify whether an approval entry is authoritative."""


class GitCommitApprovalAdapter:
    """Trust an approval only through the git commit that recorded it."""

    def __init__(self, root: Path, base_branch: str) -> None:
        self._root = root
        self._base = base_branch
        self.logger = logging.getLogger(__name__)

    async def _git(self, *args: str) -> tuple[int, str]:
        """Run one git invocation without blocking the event loop."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(self._root),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        return proc.returncode or 0, out.decode("utf-8", errors="replace")

    async def verify(self, entry: ApprovalEntry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]:
        """Verify commit, ancestry, actor, and required block hashes for an approval."""
        diagnostics: list[DecisionDiagnostic] = []

        def fail(message: str) -> tuple[bool, list[DecisionDiagnostic]]:
            diagnostics.append(DecisionDiagnostic(code=APPROVAL_UNVERIFIED, message=message, path=entry.spec_path))
            return False, diagnostics

        rc, _ = await self._git("cat-file", "-e", f"{entry.commit}^{{commit}}")
        if rc != 0:
            return fail(f"commit {entry.commit} does not exist")

        remote_base = f"origin/{self._base}"
        rc, _ = await self._git("rev-parse", "--verify", remote_base)
        if rc == 0:
            base_ref = remote_base
        else:
            base_ref = self._base
            diagnostics.append(
                DecisionDiagnostic(
                    code=APPROVAL_LOCAL_BASE,
                    message=f"{remote_base} is unavailable; verified against local {base_ref}",
                    path=entry.spec_path,
                )
            )

        rc, _ = await self._git("merge-base", "--is-ancestor", entry.commit, base_ref)
        if rc != 0:
            return fail(f"commit {entry.commit} is not an ancestor of {base_ref}")

        rc, author = await self._git("log", "-1", "--format=%an <%ae>", entry.commit)
        if rc != 0:
            return fail(f"could not determine author for commit {entry.commit}")
        if author.strip() != entry.actor:
            return fail(f"commit author {author.strip()!r} does not match approval actor {entry.actor!r}")

        if entry.kind not in {"spec", "seed"}:
            return True, diagnostics

        rc, blob = await self._git("show", f"{entry.commit}:{entry.spec_path}")
        if rc != 0:
            return fail(f"spec blob {entry.spec_path!r} is unavailable at commit {entry.commit}")
        heading = SEED_HEADING if entry.kind == "seed" else DECISIONS_HEADING
        committed_block, _, _ = parse_spec_decisions(blob, source_path=entry.spec_path, heading=heading)
        if committed_block is None:
            return fail("Decisions block at commit could not be parsed")
        if committed_block.document_id != entry.document_id:
            return fail(f"block document_id {committed_block.document_id!r} does not match {entry.document_id!r}")
        if hashlib.sha256(canonical_block_bytes(committed_block)).hexdigest() != entry.block_sha256:
            return fail("block at commit does not match approval digest")

        current_block, _, _ = parse_spec_decisions(spec_text, source_path=entry.spec_path, heading=heading)
        if current_block is None:
            return fail("current Decisions block could not be parsed")
        if current_block.document_id != entry.document_id:
            return fail(f"current block document_id {current_block.document_id!r} does not match {entry.document_id!r}")
        if hashlib.sha256(canonical_block_bytes(current_block)).hexdigest() != entry.block_sha256:
            return fail("Decisions block edited after approval")
        return True, diagnostics
