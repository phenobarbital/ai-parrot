"""Tests for RestVaultBackend against a mock Local REST API server."""
import pytest
from aiohttp import web

from parrot.interfaces.obsidian.abstract import VaultAccessError
from parrot.interfaces.obsidian.rest import RestVaultBackend

pytestmark = pytest.mark.asyncio


def _make_app(store: dict[str, str]) -> web.Application:
    """Minimal emulation of the Obsidian Local REST API plugin routes."""

    async def list_root(request: web.Request) -> web.Response:
        return _listing(store, prefix="")

    async def vault_entry(request: web.Request) -> web.Response:
        tail = request.match_info["tail"]
        if tail.endswith("/") or tail == "":
            return _listing(store, prefix=tail)
        if request.method == "GET":
            if tail not in store:
                return web.Response(status=404)
            return web.Response(text=store[tail])
        if request.method == "PUT":
            store[tail] = (await request.read()).decode("utf-8")
            return web.Response(status=204)
        if request.method == "DELETE":
            if tail not in store:
                return web.Response(status=404)
            del store[tail]
            return web.Response(status=204)
        return web.Response(status=405)

    def _listing(files: dict[str, str], prefix: str) -> web.Response:
        names: set[str] = set()
        for path in files:
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix):]
            if "/" in rest:
                names.add(rest.split("/", 1)[0] + "/")
            else:
                names.add(rest)
        if not names and prefix:
            return web.json_response({"errorCode": 404}, status=404)
        return web.json_response({"files": sorted(names)})

    async def search_simple(request: web.Request) -> web.Response:
        query = request.query.get("query", "").lower()
        rows = []
        for path, text in store.items():
            if query and query in text.lower():
                rows.append(
                    {
                        "filename": path,
                        "score": float(text.lower().count(query)),
                        "matches": [{"context": text[:60]}],
                    }
                )
        return web.json_response(rows)

    app = web.Application()
    app.router.add_get("/vault/", list_root)
    app.router.add_post("/search/simple/", search_simple)
    app.router.add_route("*", "/vault/{tail:.*}", vault_entry)
    return app


@pytest.fixture
def store() -> dict[str, str]:
    return {
        "orphan.md": "Just a lonely note.",
        "daily/today.md": "Links to [[orphan]] twice: [[orphan]].",
        "concepts/ml.md": "---\ntags: [ml]\n---\nMachine learning body.",
        ".obsidian/app.json": "{}",
    }


@pytest.fixture
async def backend(store):
    runner = web.AppRunner(_make_app(store))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    vault = RestVaultBackend(
        base_url=f"http://{host}:{port}", api_key="secret", verify_ssl=False
    )
    yield vault
    await vault.close()
    await runner.cleanup()


class TestRestBackend:
    async def test_list_files_recursive(self, backend):
        infos = await backend.list_files()
        paths = [info.path for info in infos]
        assert "daily/today.md" in paths
        assert "concepts/ml.md" in paths
        assert all(not path.startswith(".obsidian") for path in paths)

    async def test_read_note(self, backend):
        assert "lonely" in await backend.read_note("orphan")

    async def test_read_missing_raises(self, backend):
        with pytest.raises(FileNotFoundError):
            await backend.read_note("nope")

    async def test_write_and_exists(self, backend, store):
        await backend.write_note("new-note", "# Hello")
        assert store["new-note.md"] == "# Hello"
        assert await backend.note_exists("new-note") is True

    async def test_write_no_overwrite(self, backend):
        with pytest.raises(FileExistsError):
            await backend.write_note("orphan", "x", overwrite=False)

    async def test_delete(self, backend, store):
        assert await backend.delete_note("orphan") is True
        assert "orphan.md" not in store
        assert await backend.delete_note("orphan") is False

    async def test_stat_degrades_gracefully(self, backend):
        info = await backend.stat("orphan")
        assert info.mtime is None
        assert info.size == len("Just a lonely note.")

    async def test_search(self, backend):
        hits = await backend.search("machine")
        assert hits and hits[0].path == "concepts/ml.md"

    async def test_get_note_parses(self, backend):
        note = await backend.get_note("concepts/ml")
        assert "ml" in note.tags

    async def test_index_over_rest(self, backend):
        index = await backend.build_index()
        assert index.backlinks("orphan") == ["daily/today"]

    async def test_unreachable_server(self):
        vault = RestVaultBackend(base_url="http://127.0.0.1:1", timeout=0.5)
        with pytest.raises(VaultAccessError):
            await vault.read_note("x")
        await vault.close()
