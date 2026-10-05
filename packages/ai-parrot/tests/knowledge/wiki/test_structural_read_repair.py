"""Rootless (``read_repair=False``) mode of ``StructuralService`` (FEAT-569)."""
from pathlib import Path

import pytest

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.knowledge.wiki.structural.tools import create_structural_tools
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord


@pytest.fixture
async def seeded(tmp_path):
    (tmp_path / ".parrot" / "wiki").mkdir(parents=True)
    store = create_wiki_store(tmp_path / ".parrot" / "wiki", wiki_name="t", backend="sqlite")
    rec = SymbolRecord(
        rel_path="pkg/mod.py", language="python", kind=SymbolKind.FUNCTION, name="f", qualname="f",
        start_line=1, end_line=2, start_byte=0, end_byte=10, content_hash="h",
    )
    await store.upsert_symbols([rec], source_id="file:pkg/mod.py")
    return store


async def test_rootless_outline_never_touches_disk(seeded, tmp_path, monkeypatch):
    def boom(self):
        raise AssertionError("disk access in rootless mode")

    monkeypatch.setattr(Path, "read_bytes", boom)
    svc = StructuralService(seeded, tmp_path, WikiProjectConfig(wiki_name="t"), read_repair=False)
    out = await svc.outline("file:pkg/mod.py")
    assert [s.qualname for s in out.symbols] == ["f"]
    out2 = await svc.outline("sym:pkg/mod.py#f", include_source=True)
    assert out2.source is None and out2.truncated is False


async def test_factory_threads_flag(seeded, tmp_path):
    cfg = WikiProjectConfig(wiki_name="t")
    tools = create_structural_tools(seeded, tmp_path, cfg, read_repair=False)
    assert tools[0]._service_factory(None)._read_repair is False
    default = create_structural_tools(seeded, tmp_path, cfg)
    assert default[0]._service_factory(None)._read_repair is True
