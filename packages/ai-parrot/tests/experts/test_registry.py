"""Tests for ExpertRegistry discovery, admission, and registration (FEAT-778 M2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import parrot.experts.registry as registry_module
from parrot.experts.models import DuplicateExpertError
from parrot.experts.registry import ExpertRegistry
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.registry.registry import AgentRegistry


class FakeWiki:
    """Toolkit-shaped wrapper around an in-memory store."""

    def __init__(self, store: InMemoryWikiStore) -> None:
        self.store = store

    def _store_for(self, name: str) -> InMemoryWikiStore:
        return self.store

    def get_tools(self) -> list[object]:
        return []


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent Agent construction from loading an optional remote guardrail model."""
    import parrot.bots.guardrails.builtin.prompt_injection as prompt_injection

    monkeypatch.setattr(prompt_injection, "_get_shared_injection_detector", lambda: MagicMock())


def _registry(root: Path, store: InMemoryWikiStore, **kwargs: object) -> ExpertRegistry:
    """Construct a registry with an isolated workspace and wiki store."""
    return ExpertRegistry(
        agent_registry=kwargs.pop("agent_registry", AgentRegistry()),
        agents_dir=root,
        bundled_dir=kwargs.pop("bundled_dir", None),
        wiki_toolkit=FakeWiki(store),
        **kwargs,
    )


def _copy_bundle(source: Path, target: Path, name: str) -> Path:
    """Create the small complete fixture bundle needed by the registry."""
    root = target / "experts" / name
    (root / "identity").mkdir(parents=True)
    (root / "knowledge").mkdir()
    (root / "rules").mkdir()
    (root / "expert.yaml").write_text(
        "\n".join(
            (
                f"name: {name}",
                "display_name: Test Expert",
                "description: Registry test expert",
                "tier: balanced",
                "knowledge:",
                "  - {source: wiki, mode: retrieval}",
            )
        ),
        encoding="utf-8",
    )
    (root / "identity" / "role.md").write_text("You are an expert.", encoding="utf-8")
    (root / "knowledge" / "guide.md").write_text("# Guide\n\nUse evidence.", encoding="utf-8")
    (root / "rules" / "governance.md").write_text("## Mandated\nALWAYS cite evidence\n", encoding="utf-8")
    return root


@pytest.mark.asyncio
async def test_duplicate_expert_fails_load(
    expert_bundle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated names emitted within one root fail deterministically."""
    bundle, _ = registry_module.discover_expert_bundles(tmp_path / "experts")
    monkeypatch.setattr(
        registry_module, "discover_expert_bundles", lambda *args, **kwargs: ([bundle[0], bundle[0]], [])
    )
    registry = _registry(tmp_path, InMemoryWikiStore(tmp_path / "wiki"))
    with pytest.raises(DuplicateExpertError):
        await registry.load()


@pytest.mark.asyncio
async def test_registry_registers_tagged_instance(expert_bundle: Path) -> None:
    """A seeded expert is registered with its discovery tags."""
    store = InMemoryWikiStore(expert_bundle / "wiki")
    registry = _registry(expert_bundle, store)
    assert await registry.load() == 1
    metadata = registry.agent_registry.get_bots_by_tag("expert")
    assert [item.name for item in metadata] == ["sample-expert"]
    assert {"expert:sample-expert", "origin:workspace"} <= metadata[0].tags


@pytest.mark.asyncio
async def test_registry_rejects_empty_wiki_namespace(tmp_path: Path) -> None:
    """An empty namespace without seed files is skipped."""
    root = _copy_bundle(tmp_path, tmp_path, "empty-expert")
    (root / "knowledge" / "guide.md").unlink()
    registry = _registry(tmp_path, InMemoryWikiStore(tmp_path / "wiki"))
    assert await registry.load() == 0
    assert registry.report()["skipped"] == [{"path": str(root), "reason": "empty-wiki-namespace"}]


@pytest.mark.asyncio
async def test_registry_seeds_empty_namespace_from_tier1(expert_bundle: Path) -> None:
    """Tier-one files seed an otherwise empty namespace exactly once."""
    store = InMemoryWikiStore(expert_bundle / "wiki")
    registry = _registry(expert_bundle, store)
    assert await registry.load() == 1
    assert registry.report()["seeded"] == {"sample-expert": 1}
    fresh = _registry(expert_bundle, store)
    assert await fresh.load() == 1
    assert fresh.report()["seeded"] == {}


@pytest.mark.asyncio
async def test_seed_skipped_without_knowledge_files_then_rejected(tmp_path: Path) -> None:
    """Disabling seeding leaves a new namespace inadmissible."""
    root = _copy_bundle(tmp_path, tmp_path, "sample-expert")
    (root / "knowledge" / "guide.md").unlink()
    registry = _registry(tmp_path, InMemoryWikiStore(tmp_path / "wiki"))
    assert await registry.load() == 0
    assert registry.report()["skipped"][0]["reason"] == "empty-wiki-namespace"


@pytest.mark.asyncio
async def test_workspace_bundle_shadows_bundled(expert_bundle: Path, tmp_path: Path) -> None:
    """Workspace overlay wins and records the shadowed bundle path."""
    bundled = _copy_bundle(expert_bundle, tmp_path / "bundled-parent", "sample-expert").parent
    workspace = _copy_bundle(expert_bundle, tmp_path / "workspace", "sample-expert").parent.parent
    store = InMemoryWikiStore(tmp_path / "wiki")
    registry = _registry(workspace, store, bundled_dir=bundled)
    assert await registry.load() == 1
    assert registry.report()["loaded"] == [{"name": "sample-expert", "origin": "workspace"}]
    assert registry.report()["shadowing"] == {"sample-expert": str(workspace / "experts" / "sample-expert")}


@pytest.mark.asyncio
async def test_registry_pushes_deny_rule_to_evaluator(expert_bundle: Path) -> None:
    """The public DB policy registrar receives the mandatory deny rule."""
    agent_registry = AgentRegistry()
    agent_registry._evaluator = MagicMock()
    registry = _registry(expert_bundle, InMemoryWikiStore(expert_bundle / "wiki"), agent_registry=agent_registry)
    assert await registry.load() == 1
    policy = agent_registry.evaluator.load_policies.call_args.args[0][0]
    assert policy["effect"] == "deny"
    assert policy["actions"] == ["tool:execute"]
    assert policy["resources"] == ["tool:spawn_sub_agent"]


@pytest.mark.asyncio
async def test_unknown_toolkit_name_is_skipped(expert_bundle: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Unknown requested toolkit names warn and do not prevent registration."""
    manifest = expert_bundle / "experts" / "sample-expert" / "expert.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "toolkits: [NoSuchToolkit]\n", encoding="utf-8")
    registry = _registry(expert_bundle, InMemoryWikiStore(expert_bundle / "wiki"))
    assert await registry.load() == 1
    assert "unknown toolkit NoSuchToolkit; skipping" in caplog.text
