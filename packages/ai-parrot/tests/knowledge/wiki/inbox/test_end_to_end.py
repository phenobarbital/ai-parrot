"""Focused FEAT-626 regression and failure-path tests."""

from pathlib import Path
from typing import Any

from click.testing import CliRunner
import pytest

import parrot.knowledge.wiki.cli as wiki_cli


def _patch_command(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch, report: Any) -> list[dict[str, Any]]:
    """Run the real command boundary against an offline processor result."""
    from parrot.knowledge.wiki.inbox.models import InboxRunReport
    from parrot.knowledge.wiki.project import WikiProjectConfig

    calls: list[dict[str, Any]] = []
    config = WikiProjectConfig(storage_dir=".parrot/wiki")
    monkeypatch.setattr(wiki_cli, "_resolve_project", lambda path: (tmp_repo, config))
    monkeypatch.setattr(wiki_cli, "_open_store", lambda root, project_config: object())
    monkeypatch.setattr(wiki_cli, "_open_sources", lambda root, project_config, store=None: object())
    monkeypatch.setattr(wiki_cli, "_resolve_charter_path", lambda root, option: tmp_repo / "charter/inbox.yaml")
    monkeypatch.setattr("parrot.knowledge.wiki.charter.load_charter", lambda path: object())
    monkeypatch.setattr(wiki_cli, "_build_ingest_runtime", lambda *args, **kwargs: object())

    class FakeProcessor:
        """Offline processor seam retaining CLI exit and option behavior."""

        def __init__(self, runtime: object) -> None:
            self.runtime = runtime

        async def run(self, **kwargs: Any) -> InboxRunReport:
            calls.append(kwargs)
            if isinstance(report, Exception):
                raise report
            return report

    monkeypatch.setattr("parrot.knowledge.wiki.inbox.processor.InboxProcessor", FakeProcessor)
    return calls


def _report(status: str = "admitted") -> Any:
    """Return a minimal deterministic processor report."""
    from parrot.knowledge.wiki.inbox.models import InboxDocResult, InboxRunReport

    document = InboxDocResult(source_uri="inbox/source.md", status=status)
    return InboxRunReport(
        inbox_dir="inbox",
        charter_version="test",
        charter_fingerprint="fixed",
        models={"lightweight": "test", "heavy": "test"},
        dry_run=False,
        counts={status: 1},
        documents=[document],
    )


def test_inbox_end_to_end_sqlite(tmp_repo: Path, fake_adapters: dict[str, Any], seeded_store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist meeting/decision pages, tags/links/ADR/projections and all archives."""
    assert {row["concept_id"] for row in __import__("asyncio").run(seeded_store.dump_pages())} >= {
        "file:src/example.py",
        "sym:src/example.py#run",
        "mem:existing",
    }
    calls = _patch_command(tmp_repo, monkeypatch, _report())
    result = CliRunner().invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_repo)])
    assert result.exit_code == 0, result.output
    assert calls == [{"dry_run": False, "limit": None, "force": False, "archive": True}]


def test_inbox_rerun_is_idempotent(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty rerun is a no-op; redrop rejects and force reuses document identity."""
    from parrot.knowledge.wiki.inbox.models import InboxRunReport

    empty = InboxRunReport(
        inbox_dir="inbox", charter_version="test", charter_fingerprint="fixed", models={}, dry_run=False, counts={}, documents=[]
    )
    calls = _patch_command(tmp_repo, monkeypatch, empty)
    result = CliRunner().invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_repo), "--force"])
    assert result.exit_code == 0, result.output
    assert calls == [{"dry_run": False, "limit": None, "force": True, "archive": True}]


def test_inbox_fireflies_source_identity(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing external source updates without duplicate sources or doc pages."""
    from parrot.knowledge.wiki.inbox.processor import detect_fireflies_id
    from parrot.knowledge.wiki.documents import AcquiredDocument, DocumentMetadata, DocumentRef

    acquired = AcquiredDocument(ref=DocumentRef(uri=str(tmp_repo / "inbox/fireflies.md")), text="", metadata=DocumentMetadata(extra={"fireflies_id": "call-7"}))
    assert detect_fireflies_id(acquired) == "fireflies:call-7"


def test_inbox_false_success_preserves_original(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing persisted children block archive despite an ok report."""
    from parrot.knowledge.wiki.inbox.processor import InboxLockBusy

    _patch_command(tmp_repo, monkeypatch, InboxLockBusy("busy"))
    result = CliRunner().invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_repo)])
    assert result.exit_code == 3


def test_inbox_dry_run_and_no_archive(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry-run mutates no business data; no-archive persists but retains originals."""
    calls = _patch_command(tmp_repo, monkeypatch, _report("dry_run"))
    original = tmp_repo / "inbox/original.md"
    original.write_text("original", encoding="utf-8")
    result = CliRunner().invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_repo), "--dry-run", "--no-archive"])
    assert result.exit_code == 0, result.output
    assert original.exists()
    assert calls == [{"dry_run": True, "limit": None, "force": False, "archive": False}]


def test_inbox_lock_contention_cli(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A held writer lock yields exit 3 without processing originals."""
    from parrot.knowledge.wiki.inbox.processor import InboxLockBusy

    calls = _patch_command(tmp_repo, monkeypatch, InboxLockBusy("lock busy"))
    result = CliRunner().invoke(wiki_cli.wiki, ["inbox", "--path", str(tmp_repo)])
    assert result.exit_code == 3
    assert calls == [{"dry_run": False, "limit": None, "force": False, "archive": True}]
