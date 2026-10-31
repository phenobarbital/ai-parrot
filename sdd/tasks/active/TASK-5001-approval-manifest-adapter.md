# TASK-5001: Approval manifest + GitCommitApprovalAdapter (M3b)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4997, TASK-4999
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (approval half), §2 "Approval", AC13, §8 "Approval trust adapter". Decisions become
authoritative only through an append-only `sdd/decisions/approvals.jsonl` entry bound to the git commit on
`base_branch` that approved the spec (or landed a seed batch). The adapter trusts an entry only when: the
commit exists, it is an ancestor of `origin/<base_branch>` (local base when offline, with an
`APPROVAL_LOCAL_BASE` diagnostic), the Decisions block of the spec blob **at that commit** re-hashes to
`block_sha256`, and `actor` equals the commit author. Editing the block after approval (current text no longer
hashing to the recorded digest) makes its records non-authoritative (AC13).

---

## Scope

- Create `approvals.py`: `ApprovalEntry`, `ApprovalManifest` (`load`, `for_document`, `digest`, `entries`),
  `ApprovalAdapter` Protocol, `GitCommitApprovalAdapter`.
- Git calls via `asyncio.create_subprocess_exec` only (spec §7 "never blocking subprocess calls in async paths").
- Tests `test_approvals.py` with a temp git repo fixture.

**NOT in scope**: writing manifest entries (humans/TASK-5013 append them); publication (TASK-5007); eligibility (TASK-5003).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/approvals.py` | CREATE | manifest + adapter |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_approvals.py` | CREATE | unit tests (temp git repo) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio, hashlib, json
from pathlib import Path
from typing import Literal, Protocol
from pydantic import Field, ValidationError
from parrot.knowledge.wiki.decisions.models import (   # models.py:47,57,215 + TASK-4997 symbols/codes
    _Strict, DecisionDiagnostic, DecisionError, DecisionRef,
    APPROVAL_MANIFEST_INVALID, APPROVAL_UNVERIFIED, APPROVAL_LOCAL_BASE,
)
from parrot.knowledge.wiki.decisions.spec_entries import (  # TASK-4999
    DECISIONS_HEADING, SEED_HEADING, canonical_block_bytes, parse_spec_decisions,
)
```

### Existing Signatures to Use
```python
# models.py:215
class DecisionDiagnostic(_Strict): code: str; message: str = ""; path: str | None = None; decision_id: str | None = None
# spec_entries.py (TASK-4999)
def parse_spec_decisions(text, *, source_path, heading=DECISIONS_HEADING) -> tuple[SpecDecisionsBlock | None, list[ConflictWaiver], list[DecisionDiagnostic]]
def canonical_block_bytes(block: SpecDecisionsBlock) -> bytes
```

### Does NOT Exist
- ~~`sdd/decisions/approvals.jsonl`~~ — created by TASK-5013; tests use temp files.
- ~~`subprocess.run` / `check_output` in this module~~ — forbidden in async paths; use `asyncio.create_subprocess_exec`.
- ~~`DecisionService.review()` as an approval path~~ — review is never publication/approval (spec S10).
- ~~a GitHub API check~~ — verification is local git only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/approvals.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_approvals.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionDiagnostic",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionError"
  ]
}
```

---

## Implementation Notes

- **Actor format** (decided here): `"<author name> <<author email>>"` exactly as `git log -1 --format='%an <%ae>' <sha>` prints it.
- **Block hash**: `sha256(canonical_block_bytes(block)).hexdigest()`; heading is `SEED_HEADING` when `kind == "seed"`, else `DECISIONS_HEADING`.
- **Kinds**: `spec`/`seed` verify the block hash; `retirement`/`waiver` verify commit existence, ancestry and actor
  only, and their `entries` name the affected refs (FILL IN — waivers are additionally bound by fingerprint in TASK-5005).
- **Offline**: if `git rev-parse --verify origin/<base>` fails, check ancestry against the local `<base>` ref and
  append `APPROVAL_LOCAL_BASE`; verification can still pass (spec §7 "Approval offline"). Publication separately requires ancestry.
- **Manifest digest**: sha256 over the raw file bytes (empty file / missing file → sha256 of b"").
- `for_document` returns entries in file order.

---

## Implementation Blueprint

### Steps (in order)
1. Models + manifest loader (malformed line ⇒ `DecisionError(APPROVAL_MANIFEST_INVALID)` naming the line number) — *why*: append-only file must fail closed.
2. `_git()` async helper returning `(returncode, stdout)` — *why*: one place for subprocess handling.
3. `GitCommitApprovalAdapter.verify` performing the four checks, collecting diagnostics — *why*: AC13.
4. Tests with a real temp repo.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/approvals.py` (CREATE)
```python
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
    APPROVAL_LOCAL_BASE, APPROVAL_MANIFEST_INVALID, APPROVAL_UNVERIFIED,
    DecisionDiagnostic, DecisionError, DecisionRef, _Strict,
)
from parrot.knowledge.wiki.decisions.spec_entries import (
    DECISIONS_HEADING, SEED_HEADING, canonical_block_bytes, parse_spec_decisions,
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
        """JSONL, append-only; malformed line ⇒ DecisionError(APPROVAL_MANIFEST_INVALID). Missing file ⇒ empty."""
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
        # FILL IN: duplicate batch_id across entries of kind spec/seed ⇒ APPROVAL_MANIFEST_INVALID — append-only contract
        return cls(entries, raw)

    def for_document(self, document_id: str) -> list[ApprovalEntry]:
        """Entries for one document, in file order."""
        return [e for e in self.entries if e.document_id == document_id]

    def digest(self) -> str:
        """sha256 of the raw manifest bytes."""
        return hashlib.sha256(self._raw).hexdigest()
```
*(continued — same file)*

```python
class ApprovalAdapter(Protocol):
    """Pluggable trust check for an approval entry."""

    async def verify(self, entry: ApprovalEntry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]: ...


class GitCommitApprovalAdapter:
    """Trust an approval only through the git commit that recorded it."""

    def __init__(self, root: Path, base_branch: str) -> None:
        self._root = root
        self._base = base_branch
        self.logger = logging.getLogger(__name__)

    async def _git(self, *args: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(self._root), *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        return proc.returncode or 0, out.decode("utf-8", errors="replace")

    async def verify(self, entry: ApprovalEntry, *, spec_text: str) -> tuple[bool, list[DecisionDiagnostic]]:
        """commit exists · ancestor of base · blob at commit hashes to block_sha256 · actor matches author.

        ``spec_text`` is the CURRENT spec text: for spec/seed kinds its block must also hash to
        ``block_sha256``, otherwise the block was edited after approval (AC13) and verification fails.
        """
        diags: list[DecisionDiagnostic] = []

        def fail(message: str) -> tuple[bool, list[DecisionDiagnostic]]:
            diags.append(DecisionDiagnostic(code=APPROVAL_UNVERIFIED, message=message, path=entry.spec_path))
            return False, diags

        rc, _ = await self._git("cat-file", "-e", f"{entry.commit}^{{commit}}")
        if rc != 0:
            return fail(f"commit {entry.commit} does not exist")
        # FILL IN: base_ref = f"origin/{self._base}" if `rev-parse --verify` succeeds, else self._base + APPROVAL_LOCAL_BASE diag;
        #          `merge-base --is-ancestor <commit> <base_ref>` rc != 0 → fail("not an ancestor of ...")
        # FILL IN: author = `log -1 --format=%an <%ae> <commit>`.strip(); != entry.actor → fail(...)
        # FILL IN: for kind in {"spec","seed"}: blob = `show <commit>:<spec_path>` (rc!=0 → fail);
        #          heading = SEED_HEADING if seed else DECISIONS_HEADING; parse_spec_decisions(blob, ...) block None → fail;
        #          sha256(canonical_block_bytes(block)) != entry.block_sha256 → fail("block at commit does not match");
        #          same check on spec_text → fail("Decisions block edited after approval") (AC13);
        #          block.document_id != entry.document_id → fail
        return True, diags
```
**Why this shape**: signatures fixed by spec §3 M3 skeleton. All four checks are independent failure reasons
with stable code `APPROVAL_UNVERIFIED`; `APPROVAL_LOCAL_BASE` is informational and does not fail.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_approvals.py` (CREATE)
```python
"""FEAT-784 M3 — approval manifest and git adapter."""

from __future__ import annotations

import hashlib
import subprocess  # test-only, synchronous setup of a temp repo is fine outside async code paths
from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.approvals import ApprovalEntry, ApprovalManifest, GitCommitApprovalAdapter
from parrot.knowledge.wiki.decisions.models import DecisionError


@pytest.fixture
def git_base_repo(tmp_path: Path) -> Path:
    """Temp repo on branch `dev`, author 'Ada <ada@example.com>', one commit adding a spec with a Decisions block."""
    # FILL IN: git init -b dev; config user.name/email; write sdd/specs/x.spec.md (reuse the GOOD block shape
    #          from test_spec_entries, building the ``` fence at runtime); add; commit
    return tmp_path


def _entry(repo: Path, **over) -> ApprovalEntry:
    # FILL IN: compute block_sha256 from the committed spec via parse_spec_decisions + canonical_block_bytes;
    #          commit = git rev-parse HEAD; actor = "Ada <ada@example.com>"
    raise AssertionError("fill in")


async def test_commit_on_base_passes(git_base_repo):
    # FILL IN: no origin → passes with an APPROVAL_LOCAL_BASE diagnostic


@pytest.mark.parametrize("override", ["wrong_digest", "unknown_commit", "wrong_actor", "non_ancestor", "edited_after"])
async def test_git_commit_approval_adapter_failures(git_base_repo, override):
    # FILL IN: each case → (False, [... APPROVAL_UNVERIFIED ...]); non_ancestor = commit on a side branch


def test_manifest_load_and_malformed(tmp_path):
    # FILL IN: valid two-line file loads; missing file → empty; bad JSON line → DecisionError APPROVAL_MANIFEST_INVALID


def test_manifest_digest_changes_on_append(tmp_path):
    # FILL IN
```

### FILL IN checklist
- [ ] manifest duplicate batch check
- [ ] ancestry (origin vs local base), actor, blob hash, current-text hash, document_id checks — AC13
- [ ] temp-repo fixture and test bodies

---

## Acceptance Criteria

- [ ] Commit on base passes; wrong digest, unknown commit, non-ancestor, wrong actor, post-approval edit all fail with `APPROVAL_UNVERIFIED`.
- [ ] Offline (no `origin/<base>`) verifies against local base with `APPROVAL_LOCAL_BASE`.
- [ ] No blocking subprocess call in `approvals.py`.
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_approvals.py -q`

---

## Test Specification

See the blueprint test block (spec §4 `test_git_commit_approval_adapter`).

---

## Agent Instructions

1. Worktree `feat-FEAT-784-sdd-decision-audit`; TASK-4997, TASK-4999 `done`.
2. Implement; complete FILL INs; run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the two files; `scripts/sdd/close_task.sh TASK-5001 sdd-decision-audit verified`.

---

## Completion Note

*(filled in by the implementing agent)*
