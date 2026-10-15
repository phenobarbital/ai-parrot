"""Config validated by the wiki registry (FEAT-540 M7)."""

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki import store as wiki_store
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.project import WikiEnvOverlay, WikiNamespaceConfig, WikiProjectConfig


@pytest.fixture
def satellite(monkeypatch):
    """Register a temporary satellite backend, restoring the registry afterwards."""
    monkeypatch.setattr(wiki_store, "_EXTRA_BACKENDS", dict(wiki_store._EXTRA_BACKENDS))
    monkeypatch.setattr(wiki_store, "_EXTRA_SPECS", dict(wiki_store._EXTRA_SPECS))
    wiki_store.register_wiki_backend("fakegraph", lambda **_: None, kind="server")
    return "fakegraph"


@pytest.mark.parametrize("model", [WikiConfig, WikiProjectConfig])
def test_unknown_backend_rejected(model):
    field = "storage_backend" if model is WikiConfig else "backend"
    with pytest.raises(ValidationError) as exc:
        model(**{"wiki_name": "w", "storage_dir": "d", field: "nope"}) if model is WikiConfig else model(backend="nope")
    assert "'sqlite'" in str(exc.value)


def test_overlay_unknown_rejected_and_none_ok():
    assert WikiEnvOverlay().backend is None
    with pytest.raises(ValidationError):
        WikiEnvOverlay(backend="nope")


def test_registered_satellite_accepted_everywhere(satellite):
    assert WikiConfig(wiki_name="w", storage_dir="d", storage_backend=satellite).storage_backend == satellite
    assert WikiProjectConfig(backend=satellite).backend == satellite
    assert WikiEnvOverlay(backend=satellite).backend == satellite


def test_server_kind_is_built_true(satellite, tmp_path):
    assert WikiProjectConfig(backend=satellite).is_built(tmp_path) is True
    assert WikiProjectConfig(backend="arangodb").is_built(tmp_path) is True


def test_local_kinds_probe_disk(tmp_path):
    cfg = WikiProjectConfig(backend="sqlite", storage_dir="store")
    assert cfg.is_built(tmp_path) is False
    (tmp_path / "store").mkdir()
    (tmp_path / "store" / "wiki.db").write_text("")
    assert cfg.is_built(tmp_path) is True
    mem = WikiProjectConfig(backend="memory", storage_dir="mstore")
    assert mem.is_built(tmp_path) is False
    (tmp_path / "mstore" / "pages").mkdir(parents=True)
    assert mem.is_built(tmp_path) is True


def test_namespace_database_default_coerced_to_arangodb():
    assert WikiNamespaceConfig(database="db").backend == "arangodb"


def test_namespace_database_explicit_backend_survives(satellite):
    assert WikiNamespaceConfig(database="db", backend=satellite).backend == satellite


def test_database_namespace_with_local_default_backend_is_coerced_to_arangodb() -> None:
    """The CLI always passes ``backend='sqlite'``; a database source must still resolve to ArangoDB."""
    from parrot.knowledge.wiki.project import WikiNamespaceConfig

    assert WikiNamespaceConfig(database="mydb", backend="sqlite").backend == "arangodb"
    assert WikiNamespaceConfig(database="mydb").backend == "arangodb"
    assert WikiNamespaceConfig(path="x", backend="sqlite").backend == "sqlite"


async def test_null_persistence_list_commits_accepts_publisher_filters() -> None:
    """GraphPublisher forwards run_id/agent_id; the null backend must accept them."""
    from parrot.knowledge.graphindex.backends import NullPersistence

    assert await NullPersistence().list_commits(None, run_id="r", agent_id="a", limit=3) == []
