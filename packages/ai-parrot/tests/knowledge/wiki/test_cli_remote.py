import json

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w", remote=WikiRemoteConfig(url="http://fake/mcp/w")))
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_query_proxies_before_opening_store(repo, monkeypatch):
    calls = []

    def fake_text(remote, tool, arguments, *, by=None):
        calls.append({"tool": tool, "arguments": arguments, "by": by})
        return "hello"

    monkeypatch.setattr("parrot.knowledge.wiki.cli.remote_cli.call_remote_text", fake_text)
    result = CliRunner().invoke(wiki, ["query", "how does ingest work"])

    assert result.exit_code == 0, result.output
    assert "hello" in result.output
    assert not (repo / ".parrot" / "wiki" / "wiki.db").exists()
    assert calls == [
        {
            "tool": "wiki_query",
            "arguments": {
                "question": "how does ingest work",
                "budget_tokens": 1200,
                "namespace": None,
                "include_symbols": False,
            },
            "by": None,
        }
    ]


def test_remote_commands_use_exact_tool_arguments(repo, monkeypatch):
    calls = []

    def fake_text(remote, tool, arguments, *, by=None):
        calls.append((tool, arguments, by))
        return "hello"

    monkeypatch.setattr("parrot.knowledge.wiki.cli.remote_cli.call_remote_text", fake_text)
    runner = CliRunner()
    for args in (
        ["page", "file:README.md"],
        ["related", "file:README.md"],
        ["status"],
        ["symbols", "lookup", "Widget"],
        ["ledger", "ready"],
    ):
        result = runner.invoke(wiki, args)
        assert result.exit_code == 0, (args, result.output)

    assert [tool for tool, _arguments, _by in calls] == [
        "wiki_page",
        "wiki_related",
        "wiki_status",
        "wiki_symbol_lookup",
        "ledger_ready",
    ]
    assert calls[0][1] == {"page_id": "file:README.md", "namespace": None}
    assert calls[1][1] == {"page_id": "file:README.md", "namespace": None}
    assert calls[2][1] == {}
    assert calls[3][1] == {
        "query": "Widget",
        "kind": None,
        "language": None,
        "path_prefix": None,
        "limit": 20,
        "namespace": None,
    }
    assert calls[4][1] == {"kind": None}
    assert "Mode      : remote (http://fake/mcp/w)" in runner.invoke(wiki, ["status"]).output


def test_remote_json_uses_raw_result_dict(repo, monkeypatch):
    def fake_result(remote, tool, arguments, *, by=None):
        return {"content": [{"type": "text", "text": "hello"}], "tool": tool}

    monkeypatch.setattr("parrot.knowledge.wiki.cli.remote_cli.call_remote", fake_result)
    result = CliRunner().invoke(wiki, ["query", "q", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["content"][0]["text"] == "hello"
    assert payload["tool"] == "wiki_query"


def test_remote_write_propagates_actor(repo, monkeypatch):
    calls = []

    def fake_text(remote, tool, arguments, *, by=None):
        calls.append((tool, arguments, by))
        return "saved"

    monkeypatch.setattr("parrot.knowledge.wiki.cli.remote_cli.call_remote_text", fake_text)
    result = CliRunner().invoke(wiki, ["remember", "fact", "--by", "human:bob"])

    assert result.exit_code == 0, result.output
    assert calls == [
        (
            "wiki_remember",
            {"fact": "fact", "category": "note", "title": None, "link_page_id": None, "rel": "references"},
            "human:bob",
        )
    ]


def test_remote_refusals_and_store_override(repo):
    runner = CliRunner()
    result = runner.invoke(wiki, ["query", "--store", "x", "q"])
    assert result.exit_code == 2
    assert "remote mode" in result.output

    for args in (["ns", "list"], ["link", "a", "b"], ["memories"], ["ledger", "blockers", "FEAT-1"]):
        result = runner.invoke(wiki, args)
        assert result.exit_code == 2, (args, result.output)
        assert "not available in remote mode" in result.output


def test_remote_failure_is_fail_closed_without_store(tmp_path, monkeypatch):
    (tmp_path / ".parrot").mkdir()
    save_project_config(
        tmp_path,
        WikiProjectConfig(wiki_name="w", remote=WikiRemoteConfig(url="http://127.0.0.1:1/mcp/w", timeout=1)),
    )
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(wiki, ["query", "q"])

    assert result.exit_code == 2
    assert "[remote:unreachable]" in result.output
    assert not (tmp_path / ".parrot" / "wiki" / "wiki.db").exists()
