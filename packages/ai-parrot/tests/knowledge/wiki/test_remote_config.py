import json

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.project import (
    REMOTE_URL_ENV,
    WikiProjectConfig,
    WikiRemoteConfig,
    load_effective_config,
    resolve_remote,
    save_project_config,
)


def test_url_validator_normalises_and_rejects():
    assert WikiRemoteConfig(url="https://h/mcp/parrot/").url == "https://h/mcp/parrot"
    for bad in ("ftp://h/x", "/mcp/parrot", ""):
        with pytest.raises(ValidationError):
            WikiRemoteConfig(url=bad)


def test_overlay_merges_remote(tmp_path, monkeypatch):
    (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w", remote=WikiRemoteConfig(url="https://base/mcp/w")))
    (tmp_path / ".parrot" / "wiki.dev.json").write_text(
        json.dumps({"remote": {"url": "https://dev/mcp/w"}}), encoding="utf-8"
    )
    monkeypatch.setenv("WIKI_ENV", "dev")
    assert load_effective_config(tmp_path).config.remote.url == "https://dev/mcp/w"


def test_resolve_remote_precedence(monkeypatch):
    cfg = WikiProjectConfig(remote=WikiRemoteConfig(url="https://cfg/mcp/w", token_env="T", timeout=5))
    monkeypatch.delenv(REMOTE_URL_ENV, raising=False)
    assert resolve_remote(cfg).url == "https://cfg/mcp/w"
    monkeypatch.setenv(REMOTE_URL_ENV, "https://env/mcp/w")
    remote = resolve_remote(cfg)
    assert (remote.url, remote.token_env, remote.timeout) == ("https://env/mcp/w", "T", 5)
    assert resolve_remote(WikiProjectConfig()) is not None
    monkeypatch.delenv(REMOTE_URL_ENV)
    assert resolve_remote(WikiProjectConfig()) is None
