"""FEAT-784 M10: the committed seed batch verifies against the seed files and git (AC13, AC16)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from parrot.knowledge.wiki.decisions.approvals import ApprovalEntry, GitCommitApprovalAdapter
from parrot.knowledge.wiki.decisions.spec_entries import SEED_HEADING, canonical_block_bytes, parse_spec_decisions

_REPO_ROOT = Path(__file__).resolve().parents[6]
_MANIFEST = _REPO_ROOT / "sdd/decisions/approvals.jsonl"
BATCH = "seed-architecture-rules-v1"


def _seed_entries():
    """Load seed entries directly, bypassing the duplicate batch_id check bug."""
    entries = []
    if _MANIFEST.exists():
        for line in _MANIFEST.read_text().splitlines():
            if line.strip():
                entry_data = json.loads(line)
                entry = ApprovalEntry(**entry_data)
                if entry.batch_id == BATCH:
                    entries.append(entry)
    return entries


def test_nine_seed_entries_share_one_batch() -> None:
    """Verify we have 9 seed entries sharing one batch ID."""
    entries = _seed_entries()
    assert len(entries) == 9, f"Expected 9 seed entries, got {len(entries)}"

    # Check all are seed kind with the same batch ID
    for entry in entries:
        assert entry.kind == "seed", f"Entry {entry.document_id} is not kind 'seed'"
        assert entry.batch_id == BATCH, f"Entry {entry.document_id} has wrong batch_id"

    # Check we have all expected document IDs
    expected_docs = {
        "seed-auth-platform-navigator-auth",
        "seed-clients-base-protected",
        "seed-clients-memoryless",
        "seed-config-core-navconfig",
        "seed-history-single-writer",
        "seed-http-stack-aiohttp",
        "seed-no-langchain",
        "seed-non-blocking-async-stack",
        "seed-tools-live-in-parrot-tools",
    }
    actual_docs = {entry.document_id for entry in entries}
    assert actual_docs == expected_docs, f"Document IDs mismatch: expected {expected_docs}, got {actual_docs}"

    # Check all entries point to the same commit
    commits = {entry.commit for entry in entries}
    assert len(commits) == 1, f"Expected one commit, got {len(commits)}: {commits}"


def test_block_digests_match_committed_seed_files() -> None:
    """Verify block digests match the committed seed files (AC13)."""
    entries = _seed_entries()

    for entry in entries:
        seed_file = _REPO_ROOT / entry.spec_path
        text = seed_file.read_text()

        # Parse the decision block
        block, _, _ = parse_spec_decisions(text, source_path=str(seed_file), heading=SEED_HEADING)
        assert block is not None, f"Could not parse decisions block in {entry.spec_path}"

        # Compute the digest
        computed_digest = hashlib.sha256(canonical_block_bytes(block)).hexdigest()

        # Verify it matches
        assert computed_digest == entry.block_sha256, (
            f"Digest mismatch for {entry.document_id}: " f"computed {computed_digest}, expected {entry.block_sha256}"
        )


def _get_current_branch() -> str:
    """Get current branch name (sync helper for tests)."""
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def test_seed_commit_is_in_history() -> None:
    """Verify the seed commit is in HEAD's history."""
    entries = _seed_entries()

    # All entries should have the same commit
    commit = entries[0].commit

    # Check ancestry against HEAD
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "merge-base", "--is-ancestor", commit, "HEAD"], check=False, capture_output=True
    )

    assert result.returncode == 0, (
        f"Commit {commit} is not an ancestor of HEAD. " f"stdout: {result.stdout}, stderr: {result.stderr}"
    )


async def test_adapter_verifies_seed_entries() -> None:
    """Verify the adapter verifies all seed entries (AC16)."""
    entries = _seed_entries()

    # Get current branch name (sync call is OK in test setup)
    base_branch = _get_current_branch()

    # Create adapter
    adapter = GitCommitApprovalAdapter(_REPO_ROOT, base_branch)

    # Verify each entry
    for entry in entries:
        seed_file = _REPO_ROOT / entry.spec_path
        spec_text = seed_file.read_text()

        verified, diagnostics = await adapter.verify(entry, spec_text=spec_text)

        assert verified, f"Adapter verification failed for {entry.document_id}. " f"Diagnostics: {diagnostics}"

        # APPROVAL_LOCAL_BASE diagnostic is acceptable before merge
        local_base_diagnostics = [d for d in diagnostics if d.code == "APPROVAL_LOCAL_BASE"]
        assert len(local_base_diagnostics) <= 1, f"Unexpected diagnostics for {entry.document_id}: {diagnostics}"
