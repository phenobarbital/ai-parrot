"""FEAT-609 M5: symbol queries read federated namespaces; foreign planes are never written."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle
from parrot.knowledge.wiki.project import WikiNamespaceConfig, WikiProjectConfig, config_path
from parrot.knowledge.wiki.store import SQLiteWikiStore
from parrot.knowledge.wiki.structural import StructuralService
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord

from .languages.conftest import requires_astgrep


def _symbol(name: str, rel_path: str, language: str = "python") -> SymbolRecord:
    return SymbolRecord(
        rel_path=rel_path,
        language=language,
        kind=SymbolKind.FUNCTION,
        name=name,
        qualname=name,
        signature="()",
        doc=f"{name} doc",
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=10,
        content_hash="a" * 40,
    )


def _handle(name: str, store: SQLiteWikiStore, storage_dir: Path, weight: float = 1.0) -> NamespaceHandle:
    return NamespaceHandle(
        name=name,
        store=store,
        config=WikiNamespaceConfig(store=str(storage_dir), weight=weight),
        origin="repo",
        storage_dir=storage_dir,
        read_only=True,
    )


@pytest.fixture
async def federation(tmp_path: Path) -> FederatedWikiStore:
    local_dir, foreign_dir = tmp_path / "local", tmp_path / "foreign"
    local_dir.mkdir()
    foreign_dir.mkdir()
    local = SQLiteWikiStore(local_dir / "wiki.db")
    await local.upsert_symbols([_symbol("localFn", "a.py"), _symbol("shared", "a.py")])
    seed = SQLiteWikiStore(foreign_dir / "wiki.db")
    await seed.upsert_symbols([_symbol("remoteFn", "src/lib/x.ts", "javascript"), _symbol("shared", "b.py")])
    foreign = SQLiteWikiStore(foreign_dir / "wiki.db", read_only=True)
    return FederatedWikiStore(local, "local", [_handle("ns", foreign, foreign_dir)])


async def test_federated_find_symbols_fans_out(federation) -> None:
    remote = await federation.find_symbols(name="remoteFn")
    assert [(r.qualname, r.namespace) for r in remote] == [("remoteFn", "ns")]

    both = await federation.find_symbols(name="shared")
    assert [(r.rel_path, r.namespace) for r in both] == [("a.py", None), ("b.py", "ns")]  # local first


async def test_federated_search_symbols_fts_fans_out(federation) -> None:
    hits = await federation.search_symbols_fts("remoteFn")
    assert [(h.qualname, h.namespace) for h in hits] == [("remoteFn", "ns")]


async def test_federated_symbols_skip_unopenable(federation, tmp_path) -> None:
    class _Broken(SQLiteWikiStore):
        async def find_symbols(self, *args, **kwargs):
            raise RuntimeError("plane is gone")

    broken_dir = tmp_path / "broken"
    broken_dir.mkdir()
    federation.namespaces["broken"] = _handle("broken", _Broken(broken_dir / "wiki.db"), broken_dir)
    hits = await federation.find_symbols(name="localFn")
    assert [h.qualname for h in hits] == ["localFn"]
    assert [s.name for s in federation.last_skipped] == ["broken"]


async def test_namespace_never_persisted(federation) -> None:
    record = (await federation.find_symbols(name="remoteFn"))[0]
    assert record.namespace == "ns"
    assert "namespace" not in record.model_dump()
    # The foreign store's own object is untouched (copies are tagged).
    raw = await federation.namespaces["ns"].store.find_symbols(name="remoteFn")
    assert raw[0].namespace is None


async def test_lookup_hit_is_qualified(federation, tmp_path) -> None:
    service = StructuralService(federation, tmp_path / "local", WikiProjectConfig())
    out = await service.lookup("remoteFn")
    hit = out.hits[0]
    assert hit.symbol_id == "ns::sym:src/lib/x.ts#remoteFn"
    assert hit.namespace == "ns"
    assert out.repaired_files == []


async def test_lookup_dedup_is_namespace_aware(federation, tmp_path) -> None:
    """Same name in two planes -> two hits, ids told apart by namespace."""
    service = StructuralService(federation, tmp_path / "local", WikiProjectConfig())
    out = await service.lookup("shared")
    assert sorted(h.symbol_id for h in out.hits) == ["ns::sym:b.py#shared", "sym:a.py#shared"]


async def test_outline_redispatches_qualified_target(federation, tmp_path) -> None:
    service = StructuralService(federation, tmp_path / "local", WikiProjectConfig())
    out = await service.outline("ns::src/lib/x.ts")
    assert [s.qualname for s in out.symbols] == ["remoteFn"]
    assert (await service.outline("src/lib/x.ts")).symbols == []  # unqualified stays local


async def test_foreign_plane_never_written(federation, tmp_path, monkeypatch) -> None:
    foreign = federation.namespaces["ns"].store
    calls: list[str] = []

    async def _guard(*args, **kwargs):
        calls.append("write")
        raise AssertionError("foreign plane written")

    for method in ("upsert_pages", "upsert_symbols", "add_edges", "delete_page"):
        monkeypatch.setattr(foreign, method, _guard)
    root = tmp_path / "local"
    (root / "src" / "lib").mkdir(parents=True)
    (root / "src" / "lib" / "x.ts").write_text("export function remoteFn() {}\n", encoding="utf-8")
    service = StructuralService(federation, root, WikiProjectConfig())
    await service.lookup("remoteFn")
    await service.outline("ns::src/lib/x.ts")
    await service.blast_radius("ns::sym:src/lib/x.ts#remoteFn")  # unresolved seed: must still not write
    assert calls == []


async def test_read_repair_off_for_foreign_service(federation, tmp_path) -> None:
    service = StructuralService(federation, tmp_path / "local", WikiProjectConfig(), read_repair=False)
    assert await service._ensure_fresh(["a.py"]) == []


# -- CLI ------------------------------------------------------------------------


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "parrot-home"
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home


def _build(runner: CliRunner, repo: Path) -> None:
    result = runner.invoke(wiki, ["build", "--path", str(repo), "--no-git"])
    assert result.exit_code == 0, result.output


def _repo(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _federated_pair(tmp_path: Path, runner: CliRunner) -> Path:
    other = _repo(
        tmp_path / "other",
        {
            "pkg/store.py": "class Store:\n    def get(self):\n        return 1\n",
            "pkg/use.py": "from pkg.store import Store\n\n\ndef run():\n    return Store()\n",
        },
    )
    local = _repo(tmp_path / "local", {"pkg/util.py": "def helper():\n    return 1\n"})
    _build(runner, other)
    _build(runner, local)
    path = config_path(local)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["namespaces"] = {"other": {"path": str(other)}}
    path.write_text(json.dumps(data), encoding="utf-8")
    return local


@pytest.mark.usefixtures("isolated_home")
def test_cli_symbols_ns_option(tmp_path) -> None:
    runner = CliRunner()
    local = _federated_pair(tmp_path, runner)

    default = runner.invoke(wiki, ["symbols", "lookup", "Store", "--path", str(local), "--json"])
    assert default.exit_code == 0, default.output
    ids = [h["symbol_id"] for h in json.loads(default.output)["hits"]]
    assert ids[0] == "other::sym:pkg/store.py#Store" and all(i.startswith("other::") for i in ids)

    explicit = runner.invoke(wiki, ["symbols", "lookup", "Store", "--path", str(local), "--ns", "other", "--json"])
    assert explicit.exit_code == 0, explicit.output
    ids = [h["symbol_id"] for h in json.loads(explicit.output)["hits"]]
    assert ids[0] == "other::sym:pkg/store.py#Store" and all(i.startswith("other::") for i in ids)

    only_local = runner.invoke(wiki, ["symbols", "lookup", "Store", "--path", str(local), "--ns", "local", "--json"])
    assert only_local.exit_code == 0, only_local.output
    assert json.loads(only_local.output)["hits"] == []

    helper = runner.invoke(wiki, ["symbols", "lookup", "helper", "--path", str(local), "--json"])
    assert [h["symbol_id"] for h in json.loads(helper.output)["hits"]] == ["sym:pkg/util.py#helper"]


@pytest.mark.usefixtures("isolated_home")
def test_cli_outline_qualified_target(tmp_path) -> None:
    runner = CliRunner()
    local = _federated_pair(tmp_path, runner)
    result = runner.invoke(wiki, ["symbols", "outline", "other::pkg/store.py", "--path", str(local), "--json"])
    assert result.exit_code == 0, result.output
    assert "Store" in {s["qualname"] for s in json.loads(result.output)["symbols"]}


@requires_astgrep
@pytest.mark.usefixtures("isolated_home")
def test_cli_blast_qualified_seed(tmp_path) -> None:
    runner = CliRunner()
    local = _federated_pair(tmp_path, runner)
    result = runner.invoke(
        wiki, ["symbols", "blast", "other::sym:pkg/store.py#Store", "--path", str(local), "--depth", "1", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["root"]["qualname"] == "Store"
    assert "run" in {imp["symbol"]["qualname"] for imp in payload["impacted"]}


@requires_astgrep
@pytest.mark.usefixtures("isolated_home")
def test_lookup_across_namespace(tmp_path) -> None:
    runner = CliRunner()
    other = _repo(tmp_path / "svelte", {"src/lib/guard.ts": "export function requireDashboardContainer() {\n  return 1\n}\n"})
    local = _repo(tmp_path / "local", {"pkg/util.py": "def helper():\n    return 1\n"})
    _build(runner, other)
    _build(runner, local)
    path = config_path(local)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["namespaces"] = {"svelte": {"path": str(other)}}
    path.write_text(json.dumps(data), encoding="utf-8")
    for extra in ([], ["--ns", "svelte"]):
        result = runner.invoke(
            wiki, ["symbols", "lookup", "requireDashboardContainer", "--path", str(local), "--json", *extra]
        )
        assert result.exit_code == 0, result.output
        ids = [h["symbol_id"] for h in json.loads(result.output)["hits"]]
        assert ids == ["svelte::sym:src/lib/guard.ts#requireDashboardContainer"]


@pytest.mark.usefixtures("isolated_home")
def test_cli_ns_outline_blast_qualified_and_no_repair(tmp_path) -> None:
    """--ns <one>: outline/blast must not read-repair the foreign plane and must qualify ids."""
    runner = CliRunner()
    local = _federated_pair(tmp_path, runner)
    _repo(local, {"pkg/store.py": "class Store:\n    pass\n"})  # same rel_path exists locally
    out = runner.invoke(wiki, ["symbols", "outline", "pkg/store.py", "--path", str(local), "--ns", "other", "--json"])
    assert out.exit_code == 0, out.output
    ids = [s["symbol_id"] for s in json.loads(out.output)["symbols"]]
    assert ids and all(i.startswith("other::") for i in ids)
    blast = runner.invoke(
        wiki, ["symbols", "blast", "sym:pkg/store.py#Store", "--path", str(local), "--ns", "other", "--depth", "1", "--json"]
    )
    assert blast.exit_code == 0, blast.output
    payload = json.loads(blast.output)
    assert payload["root"]["symbol_id"].startswith("other::")


@pytest.mark.usefixtures("isolated_home")
def test_cli_qualified_target_ids_are_qualified(tmp_path) -> None:
    runner = CliRunner()
    local = _federated_pair(tmp_path, runner)
    result = runner.invoke(
        wiki, ["symbols", "blast", "other::sym:pkg/store.py#Store", "--path", str(local), "--depth", "1", "--json"]
    )
    payload = json.loads(result.output)
    assert payload["root"]["symbol_id"] == "other::sym:pkg/store.py#Store"
    assert all(i["symbol"]["symbol_id"].startswith("other::") for i in payload["impacted"])
