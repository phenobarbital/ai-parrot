"""Per-expert override, readiness and default-policy regression tests for FEAT-790."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import parrot.experts.registry as registry_module
from parrot.experts.models import DuplicateExpertError, ExpertTier
from parrot.experts.policy import model_config_for
from parrot.experts.registry import ExpertRegistry
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.registry.registry import AgentRegistry


class FakeWiki:
    """Toolkit-shaped wrapper around an in-memory wiki store."""

    def __init__(self, store: InMemoryWikiStore) -> None:
        """Initialize the toolkit wrapper.

        Args:
            store: In-memory backing store used for every namespace.
        """
        self.store = store

    def _store_for(self, name: str) -> InMemoryWikiStore:
        """Return the backing store for a requested namespace.

        Args:
            name: Requested namespace name.

        Returns:
            The test backing store.
        """
        return self.store

    def get_tools(self) -> list[object]:
        """Return no optional toolkit tools in tests."""
        return []


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent agent construction from loading an optional remote guardrail model."""
    import parrot.bots.guardrails.builtin.prompt_injection as prompt_injection

    monkeypatch.setattr(prompt_injection, "_get_shared_injection_detector", lambda: MagicMock())


def _bundle(root: Path, name: str, *, tier: str = "balanced") -> Path:
    """Create a complete minimal workspace expert bundle.

    Args:
        root: Workspace fixture root.
        name: Manifest name for the bundle.
        tier: Expert tier name.

    Returns:
        Created bundle root.
    """
    bundle = root / "experts" / name
    (bundle / "identity").mkdir(parents=True)
    (bundle / "knowledge").mkdir()
    (bundle / "rules").mkdir()
    (bundle / "expert.yaml").write_text(
        "\n".join(
            (
                f"name: {name}",
                "display_name: Test Expert",
                "description: Registry test expert",
                f"tier: {tier}",
                "knowledge:",
                "  - {source: wiki, mode: retrieval}",
            )
        ),
        encoding="utf-8",
    )
    (bundle / "identity" / "role.md").write_text("You are an expert.", encoding="utf-8")
    (bundle / "knowledge" / "guide.md").write_text("# Guide\n\nUse evidence.", encoding="utf-8")
    (bundle / "rules" / "governance.md").write_text("## Mandated\nALWAYS cite evidence\n", encoding="utf-8")
    return bundle


def _registry(root: Path, **kwargs: object) -> ExpertRegistry:
    """Construct an isolated registry with an in-memory wiki store.

    Args:
        root: Workspace fixture root.
        **kwargs: Registry customizations.

    Returns:
        Isolated registry instance.
    """
    return ExpertRegistry(
        agent_registry=kwargs.pop("agent_registry", AgentRegistry()),
        agents_dir=root,
        bundled_dir=kwargs.pop("bundled_dir", None),
        wiki_toolkit=FakeWiki(InMemoryWikiStore(root / "wiki")),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_defaults_match_tier_policy(tmp_path: Path) -> None:
    """None and empty mappings preserve tier defaults without override reports."""
    _bundle(tmp_path, "balanced", tier="balanced")
    _bundle(tmp_path, "judgment", tier="judgment")
    for overrides in (None, {}):
        registry = _registry(tmp_path, model_overrides=overrides)
        assert await registry.load() == 2
        assert registry.effective_model("balanced") == model_config_for(ExpertTier.BALANCED)
        assert registry.effective_model("judgment") == model_config_for(ExpertTier.JUDGMENT)
        assert registry.report()["skipped"] == []


@pytest.mark.asyncio
async def test_override_is_per_expert_and_reaches_resolver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the named expert changes in both runtime and resolver configuration."""
    _bundle(tmp_path, "selected")
    _bundle(tmp_path, "sibling")
    models: list[str | None] = []
    original_resolve = registry_module.KnowledgeResolver.resolve

    async def recording_resolve(self: object, *args: object, **kwargs: object) -> object:
        """Record resolver model selection while retaining real resolution."""
        models.append(kwargs.get("model") if isinstance(kwargs.get("model"), str) else None)
        return await original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(registry_module.KnowledgeResolver, "resolve", recording_resolve)
    registry = _registry(
        tmp_path,
        model_overrides={
            "selected": {"provider": "anthropic", "model": "claude-test", "temperature": 0.3, "max_tokens": 99}
        },
    )
    assert await registry.load() == 2
    selected = registry.effective_model("selected")
    assert selected.provider == "anthropic"
    assert selected.model == "claude-test"
    assert selected.temperature == 0.3
    assert selected.max_tokens == 99
    assert registry.effective_model("sibling") == model_config_for(ExpertTier.BALANCED)
    assert models == ["claude-test", "gemini-2.5-flash"]


@pytest.mark.asyncio
async def test_invalid_unknown_and_unadmitted_overrides_are_reported(tmp_path: Path) -> None:
    """Each rejected override skips only its target with a classified diagnostic."""
    invalid = _bundle(tmp_path, "invalid")
    unadmitted = _bundle(tmp_path, "unadmitted")
    (unadmitted / "knowledge" / "guide.md").unlink()
    registry = _registry(
        tmp_path,
        model_overrides={
            "invalid": {"provider": "google", "model": "", "unknown": True},
            "missing": {"provider": "google", "model": "gemini-test"},
            "unadmitted": {"provider": "google", "model": "gemini-test"},
        },
    )
    assert await registry.load() == 0
    override_reports = [item for item in registry.report()["skipped"] if "model-override" in item["reason"]]
    assert {(item["name"], item["reason"].split(":", 1)[0]) for item in override_reports} == {
        ("invalid", "invalid-model-override"),
        ("missing", "unknown-model-override"),
        ("unadmitted", "unadmitted-model-override"),
    }
    assert next(item for item in override_reports if item["name"] == "invalid")["path"] == str(invalid)
    missing_report = next(item for item in override_reports if item["name"] == "missing")
    assert missing_report["path"] == str(tmp_path / "experts" / "missing")
    with pytest.raises(KeyError):
        registry.effective_model("invalid")


@pytest.mark.asyncio
async def test_effective_model_and_input_are_isolated(tmp_path: Path) -> None:
    """Mutating input or returned config cannot affect the loaded agent."""
    _bundle(tmp_path, "isolated")
    override = {"provider": "google", "model": "gemini-test", "temperature": 0.4}
    registry = _registry(tmp_path, model_overrides={"isolated": override})
    override["model"] = "mutated"
    with pytest.raises(KeyError):
        registry.effective_model("isolated")
    assert await registry.load() == 1
    result = registry.effective_model("isolated")
    result.model = "returned-mutation"
    assert registry.effective_model("isolated").model == "gemini-test"


@pytest.mark.asyncio
async def test_shadowed_bundle_override_and_duplicate_failure(tmp_path: Path) -> None:
    """The winning overlay uses one override while local duplicate rejection remains unchanged."""
    bundled_parent = tmp_path / "bundled"
    _bundle(bundled_parent, "shadowed", tier="templated")
    workspace = tmp_path / "workspace"
    _bundle(workspace, "shadowed", tier="judgment")
    registry = _registry(
        workspace,
        bundled_dir=bundled_parent / "experts",
        model_overrides={"shadowed": {"provider": "google", "model": "gemini-override"}},
    )
    assert await registry.load() == 1
    assert registry.effective_model("shadowed").model == "gemini-override"

    duplicate = _registry(workspace)
    bundle = registry_module.discover_expert_bundles(workspace / "experts")[0][0]
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(registry_module, "discover_expert_bundles", lambda *args, **kwargs: ([bundle, bundle], []))
        with pytest.raises(DuplicateExpertError):
            await duplicate.load()
