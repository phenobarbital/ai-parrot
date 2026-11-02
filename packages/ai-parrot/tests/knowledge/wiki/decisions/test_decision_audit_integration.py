"""FEAT-784 integration: preview, publish, conflicts, and surface parity."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

import scripts.sdd.check_spec_consequences as gate
from parrot.knowledge.wiki.cli import _open_store, _resolve_project, wiki
from parrot.knowledge.wiki.decisions.approvals import ApprovalEntry, ApprovalManifest
from parrot.knowledge.wiki.decisions.consequences_render import check_spec, render_spec
from parrot.knowledge.wiki.decisions.operations import SpecConsequencesInput, op_spec_consequences
from parrot.knowledge.wiki.decisions.publish import BatchPublisher
from parrot.knowledge.wiki.decisions.spec_audit import approvals_path, open_consequence_service
from parrot.knowledge.wiki.decisions.spec_entries import canonical_block_bytes, parse_spec_decisions


def _git(root: Path, *args: str) -> str:
    """Run one deterministic git command in the temporary repository."""
    command = [
        "git",
        "-C",
        str(root),
        "-c",
        "user.name=Audit Tester",
        "-c",
        "user.email=audit@example.test",
        *args,
    ]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def audit_repo(tmp_path: Path) -> Path:
    """Create a built local git repository with a configured decision audit."""
    root = tmp_path / "audit-repo"
    root.mkdir()
    _git(root, "init", "-b", "dev")
    source = root / "src/pkg/mod.py"
    source.parent.mkdir(parents=True)
    source.write_text("class Widget:\n    pass\n", encoding="utf-8")
    taxonomy = root / "sdd/taxonomy/subsystems.yaml"
    taxonomy.parent.mkdir(parents=True)
    taxonomy.write_text(
        "schema_version: 1\nsubsystems:\n"
        "  - id: core\n    title: Core\n    projects: [ai-parrot]\n"
        "  - id: tooling\n    title: Tooling\n    projects: []\n"
        "mapping:\n  audit: tooling\n",
        encoding="utf-8",
    )
    approvals = root / "sdd/decisions/approvals.jsonl"
    approvals.parent.mkdir(parents=True)
    approvals.write_text("", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial audit fixture")
    result = CliRunner().invoke(wiki, ["build", "--path", str(root), "--no-graph", "--quiet"])
    assert result.exit_code == 0, result.output
    return root


def _spec(root: Path, slug: str, entries: str, *, waivers: str = "") -> Path:
    """Write a minimal decision-audit spec and return its repository-relative path."""
    path = root / "sdd/specs" / f"{slug}.spec.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "---\nprojects: [ai-parrot]\ntags: [audit]\n---\n"
        f"# {slug}\n\n**Status**: draft\n\n## Decisions\n\n```yaml\n"
        f"schema_version: 1\ndocument_id: {slug}\nentries:\n{entries}```\n\n"
        "## 2. Architectural Design\n\nBody.\n\n## 8. Open Questions\n\nNone.\n"
    )
    if waivers:
        text += f"\n## Decision Waivers\n\n```yaml\n{waivers}```\n"
    path.write_text(text, encoding="utf-8")
    return path.relative_to(root)


def _entry(entry_id: str, *, relation: str = "requires", extra: str = "") -> str:
    """Return one valid entry targeting the fixture module."""
    return (
        f"  - id: {entry_id}\n"
        "    statement: Keep the fixture module governed.\n"
        f"    relation: {relation}\n"
        "    about: [core]\n"
        '    targets: ["file:src/pkg/mod.py"]\n'
        f"{extra}"
    )


def _approval(root: Path, spec: Path, batch_id: str) -> ApprovalEntry:
    """Append a verified approval record for the committed spec block."""
    text = (root / spec).read_text(encoding="utf-8")
    block, _waivers, diagnostics = parse_spec_decisions(text, source_path=spec.as_posix())
    assert block is not None and not diagnostics
    entry = ApprovalEntry(
        kind="spec",
        batch_id=batch_id,
        spec_path=spec.as_posix(),
        document_id=block.document_id,
        entries=[
            {"decision_id": f"adr:spec:{block.document_id}#{item.id}", "revision": item.revision}
            for item in block.entries
        ],
        block_sha256=hashlib.sha256(canonical_block_bytes(block)).hexdigest(),
        commit=_git(root, "rev-parse", "HEAD"),
        actor="Audit Tester <audit@example.test>",
        recorded_at="2026-10-31T00:00:00Z",
    )
    with approvals_path(root).open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")
    return entry


async def _publish(root: Path, spec: Path, batch_id: str) -> None:
    """Approve and publish one fixture spec through the production publisher."""
    full_path = root / spec
    full_path.write_text(
        full_path.read_text(encoding="utf-8").replace("**Status**: draft", "**Status**: approved"), encoding="utf-8"
    )
    _git(root, "add", spec.as_posix())
    _git(root, "commit", "-m", f"approve {batch_id}")
    _approval(root, spec, batch_id)
    service = open_consequence_service(root)
    publisher = BatchPublisher(
        service.store,
        root,
        service.config,
        service,
        ApprovalManifest.load(approvals_path(root)),
        service.adapter,
    )
    result = await publisher.publish(batch_id)
    assert result.status == "published", result.diagnostics
    retry = await publisher.publish(batch_id)
    assert retry.status == "already-published"


async def test_end_to_end_preview_and_publish(audit_repo: Path, monkeypatch) -> None:
    """AC1/AC12: preview, check, approved publication and governing retrieval compose."""
    from parrot.clients.factory import LLMFactory

    def _boom(*args, **kwargs):
        raise AssertionError("LLMFactory.create must never be called by the decision audit")

    monkeypatch.setattr(LLMFactory, "create", staticmethod(_boom))
    spec = _spec(audit_repo, "first", _entry("one") + _entry("two", relation="constrains"))
    service = open_consequence_service(audit_repo)
    report = await render_spec(service, spec, budget_tokens=3_000)
    assert report.status == "pass", report.diagnostics
    assert (await check_spec(service, spec)).status == "current"
    await _publish(audit_repo, spec, "batch-first")

    next_spec = _spec(audit_repo, "next", _entry("three"))
    dossier = await open_consequence_service(audit_repo).governing(next_spec)
    assert {entry.decision_id for entry in dossier.entries} >= {"adr:spec:first#one", "adr:spec:first#two"}


async def test_conflict_resolution_paths(audit_repo: Path) -> None:
    """AC4/AC9: explicit conflict blocks, exact supersession and approved waiver resolve it."""
    predecessor = _spec(audit_repo, "predecessor", _entry("rule"))
    await _publish(audit_repo, predecessor, "batch-predecessor")
    reference = "{decision_id: 'adr:spec:predecessor#rule', revision: 1}"
    conflict = _spec(audit_repo, "conflict", _entry("replacement", extra=f"    contradicts: [{reference}]\n"))
    assert (await open_consequence_service(audit_repo).evaluate(conflict)).status == "conflict"

    replacement = _spec(
        audit_repo,
        "replacement",
        _entry("replacement", extra=f"    contradicts: [{reference}]\n    supersedes: [{reference}]\n"),
    )
    assert (await open_consequence_service(audit_repo).evaluate(replacement)).status == "pass"

    provisional = _spec(audit_repo, "waived", _entry("replacement", extra=f"    contradicts: [{reference}]\n"))
    report = await open_consequence_service(audit_repo).evaluate(provisional)
    finding = next(item for item in report.findings if item.kind == "contradiction")
    participants = "".join(
        f"    - {{decision_id: '{item.decision_id}', revision: {item.revision}}}\n" for item in finding.participants
    )
    waiver = (
        f"- finding_fingerprint: '{finding.fingerprint}'\n  participants:\n{participants}"
        "  actor: 'Audit Tester <audit@example.test>'\n  reason: accepted risk\n  approval_ref: waiver-batch\n"
    )
    waived = _spec(
        audit_repo, "waived", _entry("replacement", extra=f"    contradicts: [{reference}]\n"), waivers=waiver
    )
    assert (await open_consequence_service(audit_repo).evaluate(waived)).status == "conflict"
    with approvals_path(audit_repo).open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "kind": "waiver",
                    "batch_id": "waiver-batch",
                    "spec_path": waived.as_posix(),
                    "document_id": "waived",
                    "entries": [],
                    "block_sha256": "0" * 64,
                    "commit": _git(audit_repo, "rev-parse", "HEAD"),
                    "actor": "Audit Tester <audit@example.test>",
                    "recorded_at": "2026-10-31T00:00:00Z",
                }
            )
            + "\n"
        )
    assert (await open_consequence_service(audit_repo).evaluate(waived)).status == "pass"


async def test_cli_mcp_json_equivalence(audit_repo: Path) -> None:
    """S11: CLI, operation, and gate return one equivalent consequence report."""
    spec = _spec(audit_repo, "surface", _entry("rule"))
    service = open_consequence_service(audit_repo)
    await render_spec(service, spec, budget_tokens=3_000)
    cli = await asyncio.to_thread(
        CliRunner().invoke,
        wiki,
        ["spec", "consequences", "check", spec.as_posix(), "--json", "--path", str(audit_repo)],
    )
    assert cli.exit_code == 0, cli.output
    cli_payload = json.loads(cli.output)
    root, config = _resolve_project(str(audit_repo))
    mcp = await op_spec_consequences(
        _open_store(root, config), SpecConsequencesInput(spec_path=spec.as_posix()), root=root, config=config
    )
    assert not mcp.is_error, mcp.text

    import contextlib
    import io

    def _run_gate() -> tuple[int, str]:
        with contextlib.redirect_stdout(io.StringIO()) as output:
            exit_code = gate.main([spec.as_posix(), "--root", str(audit_repo), "--json"])
        return exit_code, output.getvalue()

    gate_exit, gate_stdout = await asyncio.to_thread(_run_gate)
    assert gate_exit == 0
    gate_payload = json.loads(gate_stdout)
    gate_payload.pop("check")
    mcp_payload = dict(mcp.data)
    mcp_payload.pop("check")
    cli_payload.pop("check")
    assert cli_payload == mcp_payload == gate_payload
