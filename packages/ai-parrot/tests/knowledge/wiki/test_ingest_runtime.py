"""FEAT-647 / TASK-4180 — public wiki ingest runtime tests."""

from pathlib import Path
from typing import Any

import click
import pytest

import parrot.knowledge.wiki.cli as wiki_cli
from parrot.knowledge.wiki import runtime as wiki_runtime
from parrot.knowledge.wiki.charter import load_charter
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import create_wiki_store

_CHARTER_YAML = """\
version: "1"
scope:
  include: []
  exclude: []
weights:
  density: 0.4
  novelty: 0.35
  durability: 0.25
thresholds:
  admit: 0.75
  reject: 0.35
calibration: {}
"""


class _FakeAdapter:
    """Never called during construction; only identity matters."""


@pytest.fixture
def wiki_project(tmp_path: Path) -> dict[str, Any]:
    """Build a minimal SQLite-backed wiki project for runtime construction."""
    storage = tmp_path / ".parrot" / "wiki"
    storage.mkdir(parents=True)
    charter_path = tmp_path / "charter.yaml"
    charter_path.write_text(_CHARTER_YAML, encoding="utf-8")
    config = WikiProjectConfig(storage_dir=".parrot/wiki")
    store = create_wiki_store(storage, backend="sqlite")
    sources = SourceCollectionManager(
        storage / "sources",
        db_path=storage / "wiki.db",
        busy_timeout=config.sqlite_busy_timeout,
    )
    return {
        "root": tmp_path,
        "config": config,
        "store": store,
        "sources": sources,
        "charter_path": charter_path,
    }


def test_runtime_module_is_click_free() -> None:
    """The public runtime must not depend on command-line modules."""
    src = Path(wiki_runtime.__file__).read_text(encoding="utf-8")
    assert "import click" not in src and "wiki.cli" not in src


@pytest.mark.asyncio
async def test_build_novelty_scorer_inside_loop(wiki_project: dict[str, Any]) -> None:
    """The fallback scorer can be built while an event loop is already running."""
    scorer = await wiki_runtime.build_novelty_scorer(
        wiki_project["root"], wiki_project["config"], wiki_project["store"]
    )
    assert scorer is not None


@pytest.mark.asyncio
async def test_build_ingest_runtime_with_injected_adapters(wiki_project: dict[str, Any]) -> None:
    """Injected adapters and scorer are wired into the returned runtime."""
    fake = _FakeAdapter()
    scorer = await wiki_runtime.build_novelty_scorer(
        wiki_project["root"], wiki_project["config"], wiki_project["store"]
    )
    runtime = wiki_runtime.build_ingest_runtime(
        wiki_project["root"],
        wiki_project["config"],
        wiki_project["store"],
        wiki_project["sources"],
        load_charter(wiki_project["charter_path"]),
        wiki_project["charter_path"],
        lightweight_model="google:light",
        model="google:heavy",
        novelty_scorer=scorer,
        adapters=(fake, fake, "light", True),
    )
    assert runtime.light_adapter is fake
    assert runtime.heavy_adapter is fake
    assert runtime.models == {"lightweight": "google:light", "heavy": "google:heavy"}


def test_build_ingest_runtime_wraps_adapter_failure(
    wiki_project: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public builder reports adapter construction failures consistently."""

    def _boom(lightweight_model: str, model: str) -> None:
        raise ValueError("no key")

    monkeypatch.setattr(wiki_runtime, "build_triage_adapters", _boom)
    with pytest.raises(
        wiki_runtime.WikiRuntimeError,
        match=r"Could not build LLM client\(s\) for 'a:b'/'c:d': no key",
    ):
        wiki_runtime.build_ingest_runtime(
            wiki_project["root"],
            wiki_project["config"],
            wiki_project["store"],
            wiki_project["sources"],
            load_charter(wiki_project["charter_path"]),
            wiki_project["charter_path"],
            lightweight_model="a:b",
            model="c:d",
            novelty_scorer=object(),
        )


def test_cli_wrapper_keeps_click_message(wiki_project: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI adapter seam still controls its ClickException boundary."""

    def _boom(lightweight_model: str, model: str) -> None:
        raise ValueError("no key")

    monkeypatch.setattr(wiki_cli, "_build_triage_adapters", _boom)
    with pytest.raises(click.ClickException, match=r"Could not build LLM client\(s\) for 'a:b'/'c:d': no key"):
        wiki_cli._build_ingest_runtime(
            wiki_project["root"],
            wiki_project["config"],
            wiki_project["store"],
            wiki_project["sources"],
            load_charter(wiki_project["charter_path"]),
            wiki_project["charter_path"],
            lightweight_model_opt="a:b",
            model_opt="c:d",
        )
