"""Regression cases for FEAT-627 delta and persistence."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

import parrot.knowledge.wiki.standup.delta as delta
import parrot.knowledge.wiki.standup.writer as subject
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.standup.models import BriefDocument, HygieneReport, PeriodWindow


class _Store:
    """Small async store seam recording page writes and prior brief queries."""

    def __init__(self, pages: list[dict[str, object]] | None = None, fail: bool = False) -> None:
        self.pages = pages or []
        self.fail = fail
        self.written: list[object] = []

    async def list_by_attrs(self, filters: dict[str, str], *, limit: int = 200) -> list[dict[str, object]]:
        del filters, limit
        return self.pages

    async def upsert_pages(self, pages: list[object]) -> int:
        if self.fail:
            raise OSError("injected page failure")
        self.written.extend(pages)
        return len(pages)


def _document() -> BriefDocument:
    """Create the minimum deterministic brief accepted by the writer."""
    window = PeriodWindow(
        period="day",
        anchor=date(2026, 10, 3),
        start=date(2026, 10, 2),
        end=date(2026, 10, 4),
        recent_start=date(2026, 10, 2),
        upcoming_end=date(2026, 10, 4),
        brief_id="brief:daily:2026-10-03",
    )
    return BriefDocument(
        window=window,
        identity=StandupIdentity(wiki="human:test"),
        team=False,
        language="en",
        on_your_plate=[],
        projects=[],
        internal=[],
        delta_new=[],
        delta_closed=[],
        sources=[],
        hygiene=HygieneReport(),
        item_ids=["issues::ONE", "TASK-2"],
    )


@pytest.mark.asyncio
async def test_same_period_delta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Select only the prior daily brief and tolerate corrupt persisted items."""
    del tmp_path, monkeypatch
    store = _Store(
        [
            {
                "concept_id": "brief:daily:2026-10-02",
                "attrs": {"period": "day", "date": "2026-10-02", "items": '["TASK-1", "TASK-2"]'},
            },
            {
                "concept_id": "brief:weekly:2026-W40",
                "attrs": {"period": "week", "date": "2026-10-02", "items": '["OTHER"]'},
            },
            {
                "concept_id": "brief:daily:2026-10-03",
                "attrs": {"period": "day", "date": "2026-10-03", "items": '["CURRENT"]'},
            },
        ]
    )
    previous = await delta.previous_brief(store, _document().window)  # type: ignore[arg-type]
    assert previous is not None
    assert previous["concept_id"] == "brief:daily:2026-10-02"
    assert delta.diff(["TASK-2", "TASK-3"], previous) == (["TASK-3"], ["TASK-1"])
    assert delta.diff(["TASK-3"], {"attrs": {"items": "not-json"}}) == (["TASK-3"], [])
    assert delta.diff(["TASK-3"], None) == ([], [])


@pytest.mark.asyncio
async def test_locked_page_and_atomic_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write complete attrs and atomically replace a real output file."""
    store = _Store()
    output = tmp_path / "output"
    target = output / "brief-daily-2026-10-03.md"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")

    result = await subject.write(
        _document(),
        "# Current\n",
        store=store,
        storage_dir=tmp_path / "store",
        out_dir=output,
        write_page=True,
        write_file=True,
        vault_dir=output,
    )

    assert result.written_page is True
    assert result.written_file == str(target)
    assert store.written[0].attrs == {
        "type": "deliverable",
        "status": "draft",
        "date": "2026-10-03",
        "owner": "human:test",
        "period": "day",
        "items": '["TASK-2", "issues::ONE"]',
        "source": "brief",
        "language": "en",
    }
    content = target.read_text(encoding="utf-8")
    assert "wiki_id: brief:daily:2026-10-03" in content
    assert content.endswith("# Current\n")
    assert not list(output.glob("*.tmp"))
    assert "[STANDUP]" in (tmp_path / "store" / "log.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_partial_failure_and_vault_markers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Retain a successful file when page persistence fails or is lock-contended."""

    @contextmanager
    def denied_lock(_: Path) -> Iterator[bool]:
        yield False

    monkeypatch.setattr(subject, "wiki_write_lock", denied_lock)
    outside = tmp_path / "outside"
    result = await subject.write(
        _document(),
        "# Current\n",
        store=_Store(fail=True),
        storage_dir=tmp_path / "store",
        out_dir=outside,
        write_page=True,
        write_file=True,
        vault_dir=tmp_path / "vault",
    )

    assert result.written_page is False
    assert result.written_file is not None
    assert "lock is held" in result.diagnostics[0]
    content = Path(result.written_file).read_text(encoding="utf-8")
    assert not content.startswith("---")
    assert not list(outside.glob("*.tmp"))
