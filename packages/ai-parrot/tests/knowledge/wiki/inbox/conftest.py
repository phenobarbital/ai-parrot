"""Isolated SQLite and git fixtures for inbox lifecycle acceptance tests."""

from collections.abc import AsyncIterator
from pathlib import Path
import subprocess
from typing import Any

import pytest
import pytest_asyncio

import parrot.knowledge.wiki.cli as wiki_cli
from parrot.knowledge.wiki.inbox.models import InboxClassification, LinkSelection
from parrot.knowledge.wiki.review import TriageOutput
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, create_wiki_store


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary git root with inbox, SQLite config and fixed charter."""
    for relative in ("inbox", ".parrot/wiki", "charter"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / "charter" / "inbox.yaml").write_text("version: test\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "inbox@example.test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Inbox tests"], check=True)
    (tmp_path / ".gitignore").write_text(".parrot/wiki/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore", "charter/inbox.yaml"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "fixture"], check=True)
    return tmp_path


@pytest.fixture
def fake_adapters(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the CLI adapter seam with typed, schema-directed responses and call records."""
    calls: list[type[Any]] = []

    class FakeAdapter:
        """Return only typed responses used by the inbox pipeline."""

        async def ask_structured(self, prompt: str, output_type: type[Any], **kwargs: Any) -> Any:
            """Record output type and provide a valid deterministic model response."""
            calls.append(output_type)
            if output_type is TriageOutput:
                return TriageOutput.model_validate(
                    {
                        "briefing": "Deterministic inbox fixture.",
                        "scores": {"density": 1.0, "novelty": 1.0, "durability": 1.0},
                    }
                )
            if output_type is InboxClassification:
                return InboxClassification(kind="decision", title="Fixture decision", summary="Fixture summary", tags=["test"])
            if output_type is LinkSelection:
                return LinkSelection()
            raise AssertionError(f"unexpected structured output type: {output_type}")

    adapter = FakeAdapter()
    monkeypatch.setattr(wiki_cli, "_build_triage_adapters", lambda lightweight, model: (adapter, adapter, lightweight, True))
    return {"adapter": adapter, "calls": calls}


@pytest_asyncio.fixture
async def seeded_store(tmp_repo: Path) -> AsyncIterator[BaseWikiStore]:
    """Yield a real temporary store with known code and authored link targets."""
    store = create_wiki_store(tmp_repo / ".parrot/wiki", backend="sqlite")
    await store.upsert_pages(
        [
            WikiPageRecord(concept_id="file:src/example.py", title="Example file", category="code"),
            WikiPageRecord(concept_id="sym:src/example.py#run", title="run", category="code"),
            WikiPageRecord(concept_id="mem:existing", title="Existing note", category="note"),
        ]
    )
    yield store
