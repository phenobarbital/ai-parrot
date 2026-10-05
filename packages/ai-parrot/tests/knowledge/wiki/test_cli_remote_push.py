import asyncio
import json

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki import remote_cli
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config
from parrot.knowledge.wiki.remote import RemoteWikiError
from parrot.knowledge.wiki.store import WikiPageRecord
from parrot.knowledge.wiki.tools import INGEST_MAX_BYTES, SourceSlicePayload


def _envelope(payload, error=False):
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": error}


class FakeClient:
    """Records tools/call traffic; answers the bulk tools."""

    def __init__(self):
        self.tool_calls = []
        self.hashes = {}
        self.ingest_failures = 0
        self.pull_pages = []
        self.pull_page_size = 500

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def call_tool(self, name, arguments):
        self.tool_calls.append({"name": name, "arguments": arguments})
        if name == "wiki_page_hashes":
            return _envelope({"hashes": {i: self.hashes.get(i) for i in arguments["concept_ids"]}})
        if name == "wiki_ingest_batch":
            if self.ingest_failures:
                self.ingest_failures -= 1
                raise RemoteWikiError("tool_error", "boom", url="http://fake")
            slices = arguments["slices"]
            return _envelope(
                {
                    "slices_applied": len(slices),
                    "slices_deleted": len(arguments["deleted_source_ids"]),
                    "pages_written": sum(len(s["pages"]) for s in slices),
                    "symbols_written": sum(len(s["symbols"]) for s in slices),
                }
            )
        if name == "wiki_sync_push":
            return _envelope({"created": len(arguments["pages"])})
        if name == "wiki_sync_pull":
            pages = self.pull_pages
            start = int(arguments.get("cursor") or 0)
            chunk = pages[start : start + self.pull_page_size]
            nxt = str(start + self.pull_page_size) if start + self.pull_page_size < len(pages) else None
            return _envelope({"pages": chunk, "edges": [], "next_cursor": nxt})
        raise AssertionError(name)


@pytest.fixture
def repo_with_remote(tmp_path, monkeypatch):
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w", remote=WikiRemoteConfig(url="http://fake/mcp/w")))
    for i in range(3):
        (tmp_path / f"mod{i}.py").write_text(f"def f{i}():\n    return {i}\n")
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    monkeypatch.chdir(tmp_path)
    fake = FakeClient()
    monkeypatch.setattr(remote_cli, "remote_client", lambda remote, by=None: fake)
    return tmp_path, fake


def test_build_pushes_then_converges(repo_with_remote):
    root, fake = repo_with_remote
    result = CliRunner().invoke(wiki, ["build", "--quiet", "--no-git"])
    assert result.exit_code == 0, result.output
    names = [c["name"] for c in fake.tool_calls]
    assert "wiki_page_hashes" in names and names.count("wiki_ingest_batch") >= 1
    batch = next(c for c in fake.tool_calls if c["name"] == "wiki_ingest_batch")["arguments"]
    assert batch["slices"][0]["pages"] and "symbols" in batch["slices"][0] and batch["batch_id"]
    assert batch["slices"][0]["source_id"].startswith("file:")
    fake.hashes = {p["concept_id"]: p["content_hash"] for s in batch["slices"] for p in s["pages"]}
    fake.tool_calls.clear()
    result = CliRunner().invoke(wiki, ["build", "--quiet", "--no-git"])
    assert result.exit_code == 0, result.output
    assert [c["name"] for c in fake.tool_calls].count("wiki_ingest_batch") == 0


def test_no_push(repo_with_remote):
    root, fake = repo_with_remote
    result = CliRunner().invoke(wiki, ["build", "--quiet", "--no-git", "--no-push"])
    assert result.exit_code == 0, result.output
    assert fake.tool_calls == []
    assert (root / ".parrot").exists()


def test_upsert_pushes_changed_and_deleted(repo_with_remote):
    root, fake = repo_with_remote
    assert CliRunner().invoke(wiki, ["build", "--quiet", "--no-git", "--no-push"]).exit_code == 0
    (root / "mod2.py").unlink()
    (root / "mod0.py").write_text("def f0():\n    return 99\n")
    result = CliRunner().invoke(wiki, ["upsert", "mod0.py", "mod2.py", "--quiet"])
    assert result.exit_code == 0, result.output
    batch = next(c for c in fake.tool_calls if c["name"] == "wiki_ingest_batch")["arguments"]
    assert [s["source_id"] for s in batch["slices"]] == ["file:mod0.py"]
    assert batch["deleted_source_ids"] == ["file:mod2.py"]


def _slice(i, body="x"):
    return SourceSlicePayload(
        source_id=f"file:f{i}.py",
        pages=[WikiPageRecord(concept_id=f"file:f{i}.py", title="t", body=body, content_hash=f"h{i}")],
    )


class _StubStore:
    pass


def test_chunking_and_oversize(monkeypatch):
    fake = FakeClient()
    slices = [_slice(i) for i in range(450)] + [_slice(999, body="y" * (INGEST_MAX_BYTES + 10))]

    async def collect(store, local_sources):
        return slices

    monkeypatch.setattr(remote_cli, "_collect_slices", collect)
    report = asyncio.run(remote_cli.push_sources(fake, _StubStore(), {"a": "b"}))
    batches = [c["arguments"] for c in fake.tool_calls if c["name"] == "wiki_ingest_batch"]
    assert [len(b["slices"]) for b in batches] == [200, 200, 50]
    assert report.rejected == ["file:f999.py"]
    assert report.slices_applied == 450
    sent = {s["source_id"] for b in batches for s in b["slices"]}
    assert "file:f999.py" not in sent


def test_retry_once_then_fail(monkeypatch):
    fake = FakeClient()

    async def collect(store, local_sources):
        return [_slice(1)]

    monkeypatch.setattr(remote_cli, "_collect_slices", collect)
    fake.ingest_failures = 1
    report = asyncio.run(remote_cli.push_sources(fake, _StubStore(), {"a": "b"}))
    assert report.slices_applied == 1
    assert [c["name"] for c in fake.tool_calls].count("wiki_ingest_batch") == 2

    fake2 = FakeClient()
    fake2.ingest_failures = 2
    with pytest.raises(remote_cli.RemoteCliError) as err:
        asyncio.run(remote_cli.push_sources(fake2, _StubStore(), {"a": "b"}))
    assert "file:f1.py" in str(err.value)
    assert err.value.exit_code == 2


def test_sync_push_and_pull_never_open_arango(repo_with_remote, monkeypatch):
    import parrot.knowledge.wiki.sync as sync

    def boom(*a, **k):
        raise AssertionError("client-side arango")

    monkeypatch.setattr(sync, "_open_remote", boom)
    root, fake = repo_with_remote
    assert CliRunner().invoke(wiki, ["build", "--quiet", "--no-git", "--no-push"]).exit_code == 0
    fake.pull_pages = [
        {
            "concept_id": f"memory:x{i}",
            "title": "x",
            "body": "b",
            "origin": "memory",
            "asserted_by": "human:zed-not-me",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        for i in range(3)
    ]
    fake.pull_page_size = 2
    result = CliRunner().invoke(wiki, ["sync", "pull"])
    assert result.exit_code == 0, result.output
    assert "created=3" in result.output
    assert [c["name"] for c in fake.tool_calls].count("wiki_sync_pull") == 2
    again = CliRunner().invoke(wiki, ["sync", "pull"])
    assert "created=0" in again.output and "skipped-older=3" in again.output

    result = CliRunner().invoke(wiki, ["sync", "push"])
    assert result.exit_code == 0, result.output
    push = next(c for c in fake.tool_calls if c["name"] == "wiki_sync_push")["arguments"]
    assert len(push["pages"]) == 3


def test_tool_json_error_envelope_raises_typed_error():
    """An isError envelope surfaces as a RemoteWikiError, not a TypeError."""
    from parrot.knowledge.wiki.remote import RemoteWikiError
    from parrot.knowledge.wiki.remote_cli import _tool_json

    with pytest.raises(RemoteWikiError) as info:
        _tool_json({"isError": True, "content": [{"type": "text", "text": "boom"}]})
    assert info.value.code == "tool_error" and info.value.exit_code == 2


async def test_call_tool_text_raises_on_tool_error(monkeypatch):
    """Tool-level failures must not look like successful CLI output."""
    from parrot.knowledge.wiki.project import WikiRemoteConfig
    from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError

    monkeypatch.setenv("WT_TEST_TOKEN", "t")
    client = RemoteWikiClient(WikiRemoteConfig(url="https://h/mcp/w", token_env="WT_TEST_TOKEN"), actor="human:a")

    async def fake_call(name, arguments):
        return {"isError": True, "content": [{"type": "text", "text": "Page not found"}]}

    monkeypatch.setattr(client, "call_tool", fake_call)
    with pytest.raises(RemoteWikiError) as info:
        await client.call_tool_text("wiki_page", {"page_id": "x"})
    assert info.value.code == "tool_error" and "Page not found" in info.value.message
    await client.close()
