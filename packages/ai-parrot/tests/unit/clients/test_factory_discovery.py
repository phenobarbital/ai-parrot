"""TASK-2847: entry-point discovery + catalogue tests for ``LLMFactory``.

Spec §4 Module 3 rows. Exercises ``factory._discover()`` in isolation via
mocked ``importlib.metadata.entry_points`` — the sole discovery source
since TASK-2854 removed the transitional ``_IN_CORE_PROVIDERS`` registry
— plus the ``list_providers()``/``list_models()`` catalogue methods.
"""
import importlib.metadata as md

import pytest

from parrot.clients import factory


def _reset(monkeypatch):
    """Force a fresh discovery pass: clear the flag + the registry dict."""
    monkeypatch.setattr(factory, "_DISCOVERED", False, raising=False)
    factory.SUPPORTED_CLIENTS.clear()
    factory._PROVIDER_DIST.clear()


@pytest.fixture(autouse=True)
def _restore_real_discovery():
    """TASK-2855: several tests in this file mutate the REAL
    ``SUPPORTED_CLIENTS``/``_PROVIDER_DIST`` dicts directly (via
    ``_reset()``) and repopulate them with mocked entry points —
    ``monkeypatch`` reverts ``_DISCOVERED``/``importlib.metadata.
    entry_points`` afterward, but not those direct dict mutations. Left
    unrestored, a fake ``"test-provider"`` entry (or an empty registry)
    leaks into any test file that runs afterward and iterates every
    registered key (e.g.
    ``tests/integration/clients/test_factory_create_all_keys.py``,
    ``tests/unit/clients/test_folder_convention.py``). Force one real,
    unmocked discovery pass after every test in this module.
    """
    yield
    factory.SUPPORTED_CLIENTS.clear()
    factory._PROVIDER_DIST.clear()
    factory._DISCOVERED = False
    factory.LLMFactory._discover()


def test_discover_entry_points(monkeypatch):
    _reset(monkeypatch)
    ep = md.EntryPoint(
        name="test-provider",
        value="tests.unit.clients.fakes:FakeClient",
        group="parrot.clients",
    )
    monkeypatch.setattr(md, "entry_points", lambda group=None: [ep])
    factory.LLMFactory._discover()
    assert "test-provider" in factory.SUPPORTED_CLIENTS


def test_duplicate_entry_point_warning(monkeypatch, caplog):
    _reset(monkeypatch)
    ep1 = md.EntryPoint(
        name="test-provider",
        value="tests.unit.clients.fakes:FakeClient",
        group="parrot.clients",
    )
    ep2 = md.EntryPoint(
        name="test-provider",
        value="parrot.clients.openai:OpenAIClient",
        group="parrot.clients",
    )
    monkeypatch.setattr(md, "entry_points", lambda group=None: [ep1, ep2])
    with caplog.at_level("WARNING", logger="parrot.clients.factory"):
        factory.LLMFactory._discover()
    assert "test-provider" in factory.SUPPORTED_CLIENTS
    # First registration wins — the ep1-loaded FakeClient, not ep2's OpenAIClient.
    # The registered value is ep1.load itself (a lazy loader), same shape
    # as the pre-existing _lazy_* closures — resolve it to compare classes.
    from tests.unit.clients.fakes import FakeClient

    registered = factory.SUPPORTED_CLIENTS["test-provider"]
    resolved = registered() if callable(registered) and not isinstance(registered, type) else registered
    assert resolved is FakeClient
    assert any("Duplicate LLM provider key" in rec.message for rec in caplog.records)


def test_create_missing_satellite(monkeypatch):
    # FEAT-523 (TASK-2854): _IN_CORE_PROVIDERS no longer exists — entry
    # points are the only discovery source now, so an empty entry_points()
    # result alone is enough to simulate zero satellites installed.
    _reset(monkeypatch)
    monkeypatch.setattr(md, "entry_points", lambda group=None: [])
    with pytest.raises(ImportError, match="ai-parrot-client-claude"):
        factory.LLMFactory.create("claude:x")


def test_list_models_active_deprecated(monkeypatch):
    _reset(monkeypatch)
    # FEAT-523 (TASK-2853): every real provider is now extracted to its
    # own satellite — _IN_CORE_PROVIDERS is empty, so this core test can
    # no longer assert against a real in-core provider without depending
    # on a satellite being installed. Mock an entry point instead (same
    # pattern as test_discover_entry_points).
    ep = md.EntryPoint(
        name="test-provider",
        value="tests.unit.clients.fakes:FakeClient",
        group="parrot.clients",
    )
    monkeypatch.setattr(md, "entry_points", lambda group=None: [ep])
    out = factory.LLMFactory.list_models("test-provider")
    assert out == {"active": ["fake-active-model"], "deprecated": ["fake-deprecated-model"]}


def test_list_providers_lists_in_core_keys(monkeypatch):
    _reset(monkeypatch)
    # FEAT-523 (TASK-2853): _IN_CORE_PROVIDERS is now empty — assert the
    # entry-point-sourced distribution name instead ("ai-parrot" would
    # never appear for any key anymore; this test's title predates the
    # last provider leaving core, kept for the list_providers() shape).
    ep = md.EntryPoint(
        name="test-provider",
        value="tests.unit.clients.fakes:FakeClient",
        group="parrot.clients",
    )
    monkeypatch.setattr(md, "entry_points", lambda group=None: [ep])
    providers = factory.LLMFactory.list_providers()
    assert providers.get("test-provider") == "test-provider"


def test_provider_backend_discovered():
    from parrot.clients.factory import PROVIDER_BACKEND

    assert PROVIDER_BACKEND["bedrock"] == "bedrock"


def test_provider_backend_injected_on_create(monkeypatch):
    """create() must inject backend=PROVIDER_BACKEND[provider] before **kwargs."""
    captured = {}

    class _StubAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(factory.SUPPORTED_CLIENTS, "bedrock", _StubAnthropic)
    factory.LLMFactory.create("bedrock")
    assert captured.get("backend") == "bedrock"


def test_no_provider_import_at_module_scope():
    """AC: factory.py has no `from .<provider>` import at module scope —
    only `.base` (AbstractClient)."""
    import pathlib

    src = pathlib.Path(factory.__file__).read_text()
    from_dot_lines = [
        line for line in src.splitlines() if line.startswith("from .")
    ]
    assert from_dot_lines == ["from .base import AbstractClient"]


def test_zai_client_not_importable_from_parrot_clients():
    """AC: `parrot/clients/__init__.py` starts with extend_path; the old
    `from parrot.clients import ZaiClient` hard cut must now fail."""
    with pytest.raises(ImportError):
        from parrot.clients import ZaiClient  # noqa: F401
