"""FEAT-784 M3 — approval manifest and git adapter."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.approvals import ApprovalEntry, ApprovalManifest, GitCommitApprovalAdapter
from parrot.knowledge.wiki.decisions.models import (
    APPROVAL_LOCAL_BASE,
    APPROVAL_MANIFEST_INVALID,
    APPROVAL_UNVERIFIED,
    DecisionError,
)
from parrot.knowledge.wiki.decisions.spec_entries import canonical_block_bytes, parse_spec_decisions

FENCE = "`" * 3
SPEC_PATH = "sdd/specs/x.spec.md"
GOOD = f"""# Spec

## Decisions

{FENCE}yaml
schema_version: 1
document_id: feat-784
entries:
  - id: one
    statement: Clients never persist history.
    relation: forbids
    about: [clients, memory]
    targets: [dir:packages/ai-parrot/src/parrot/clients]
{FENCE}
"""


def _run_git(repo: Path, *args: str) -> str:
    """Run git synchronously while arranging an isolated test repository."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, capture_output=True).stdout.strip()


@pytest.fixture
def git_base_repo(tmp_path: Path) -> Path:
    """Create a dev repo with Ada's committed spec Decisions block."""
    _run_git(tmp_path, "init", "-b", "dev")
    _run_git(tmp_path, "config", "user.name", "Ada")
    _run_git(tmp_path, "config", "user.email", "ada@example.com")
    spec_path = tmp_path / SPEC_PATH
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(GOOD, encoding="utf-8")
    _run_git(tmp_path, "add", SPEC_PATH)
    _run_git(tmp_path, "commit", "-m", "add spec")
    return tmp_path


def _entry(repo: Path, **over: object) -> ApprovalEntry:
    """Build an entry whose digest refers to the committed Decisions block."""
    spec_text = (repo / SPEC_PATH).read_text(encoding="utf-8")
    block, _, diagnostics = parse_spec_decisions(spec_text, source_path=SPEC_PATH)
    assert block is not None
    assert diagnostics == []
    values: dict[str, object] = {
        "kind": "spec",
        "batch_id": "batch-1",
        "spec_path": SPEC_PATH,
        "document_id": block.document_id,
        "entries": [{"decision_id": "adr:spec:feat-784#one", "revision": 1}],
        "block_sha256": hashlib.sha256(canonical_block_bytes(block)).hexdigest(),
        "commit": _run_git(repo, "rev-parse", "HEAD"),
        "actor": "Ada <ada@example.com>",
        "recorded_at": "2026-10-31T00:00:00Z",
    }
    values.update(over)
    return ApprovalEntry.model_validate(values)


async def test_commit_on_base_passes(git_base_repo: Path) -> None:
    """A base commit verifies locally when no origin remote exists."""
    entry = _entry(git_base_repo)
    result, diagnostics = await GitCommitApprovalAdapter(git_base_repo, "dev").verify(
        entry, spec_text=(git_base_repo / SPEC_PATH).read_text(encoding="utf-8")
    )
    assert result is True
    assert [diagnostic.code for diagnostic in diagnostics] == [APPROVAL_LOCAL_BASE]


@pytest.mark.parametrize("override", ["wrong_digest", "unknown_commit", "wrong_actor", "non_ancestor", "edited_after"])
async def test_git_commit_approval_adapter_failures(git_base_repo: Path, override: str) -> None:
    """Every invalid git or block binding rejects the approval."""
    entry = _entry(git_base_repo)
    spec_text = (git_base_repo / SPEC_PATH).read_text(encoding="utf-8")
    if override == "wrong_digest":
        entry = entry.model_copy(update={"block_sha256": "0" * 64})
    elif override == "unknown_commit":
        entry = entry.model_copy(update={"commit": "f" * 40})
    elif override == "wrong_actor":
        entry = entry.model_copy(update={"actor": "Grace <grace@example.com>"})
    elif override == "non_ancestor":
        _run_git(git_base_repo, "checkout", "-b", "side")
        (git_base_repo / "side.txt").write_text("side", encoding="utf-8")
        _run_git(git_base_repo, "add", "side.txt")
        _run_git(git_base_repo, "commit", "-m", "side commit")
        entry = entry.model_copy(update={"commit": _run_git(git_base_repo, "rev-parse", "HEAD")})
        _run_git(git_base_repo, "checkout", "dev")
    else:
        spec_text = spec_text.replace("Clients never persist history.", "Clients may persist history.")

    result, diagnostics = await GitCommitApprovalAdapter(git_base_repo, "dev").verify(entry, spec_text=spec_text)
    assert result is False
    assert APPROVAL_UNVERIFIED in {diagnostic.code for diagnostic in diagnostics}


def test_manifest_load_and_malformed(tmp_path: Path) -> None:
    """Manifests preserve order, treat missing files as empty, and fail closed on invalid lines."""
    manifest_path = tmp_path / "approvals.jsonl"
    entry = _entry_for_manifest()
    manifest_path.write_text(
        "\n".join(
            [
                entry.model_dump_json(),
                entry.model_copy(update={"kind": "retirement", "batch_id": "batch-2"}).model_dump_json(),
            ]
        ),
        encoding="utf-8",
    )
    manifest = ApprovalManifest.load(manifest_path)
    assert manifest.for_document("feat-784") == manifest.entries
    assert ApprovalManifest.load(tmp_path / "missing.jsonl").entries == []
    manifest_path.write_text("{bad json}\n", encoding="utf-8")
    with pytest.raises(DecisionError, match=APPROVAL_MANIFEST_INVALID):
        ApprovalManifest.load(manifest_path)
    manifest_path.write_text(
        "\n".join(
            [
                entry.model_dump_json(),
                entry.model_copy(update={"kind": "seed"}).model_dump_json(),
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(DecisionError, match=APPROVAL_MANIFEST_INVALID):
        ApprovalManifest.load(manifest_path)


def test_manifest_digest_changes_on_append(tmp_path: Path) -> None:
    """The digest covers exact raw JSONL bytes and changes after an append."""
    manifest_path = tmp_path / "approvals.jsonl"
    entry = _entry_for_manifest()
    manifest_path.write_bytes(entry.model_dump_json().encode("utf-8"))
    before = ApprovalManifest.load(manifest_path).digest()
    with manifest_path.open("ab") as manifest_file:
        manifest_file.write(
            b"\n"
            + entry.model_copy(update={"kind": "retirement", "batch_id": "batch-2"}).model_dump_json().encode("utf-8")
        )
    after = ApprovalManifest.load(manifest_path).digest()
    assert before != after
    assert after == hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _entry_for_manifest() -> ApprovalEntry:
    """Return a valid stable approval event suitable for manifest parsing tests."""
    return ApprovalEntry(
        kind="spec",
        batch_id="batch-1",
        spec_path=SPEC_PATH,
        document_id="feat-784",
        entries=[{"decision_id": "adr:spec:feat-784#one", "revision": 1}],
        block_sha256="a" * 64,
        commit="a" * 40,
        actor="Ada <ada@example.com>",
        recorded_at="2026-10-31T00:00:00Z",
    )
