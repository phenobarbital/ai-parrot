"""Unit tests for the free-text feature intake (FEAT-388, Module 2)."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from parrot.cli.devloop.intake import DEFAULT_INTAKE_LLM, FeatureDraft, FeatureIntake
from pydantic import ValidationError


def _draft(**overrides: Any) -> FeatureDraft:
    payload = {
        "title": "Add dark mode",
        "slug": "add-dark-mode",
        "problem_statement": "Users want a dark theme.",
        "requirements": ["Toggle in settings", "Persist preference"],
        "acceptance_criteria": ["Theme persists across sessions"],
    }
    payload.update(overrides)
    return FeatureDraft(**payload)


class InvokeResultStub:
    """Minimal stand-in for ``InvokeResult`` — only ``.output`` is read."""

    def __init__(self, output: Any) -> None:
        self.output = output


class FakeClient:
    """Fake ``AbstractClient`` whose ``invoke()`` is scripted per call.

    ``responses`` is a list consumed one item per call: a ``FeatureDraft``
    (or arbitrary value) is wrapped into an ``InvokeResultStub``; an
    ``Exception`` instance is raised instead.
    """

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def invoke(self, prompt: str, *, output_type: type | None = None, **kwargs: Any):
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("FakeClient.invoke called more times than scripted")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return InvokeResultStub(item)


def _validation_error() -> ValidationError:
    try:
        FeatureDraft()  # missing required fields
    except ValidationError as exc:
        return exc
    raise AssertionError("FeatureDraft() unexpectedly validated")


@pytest.mark.asyncio
async def test_generate_returns_draft():
    """A single successful invoke() call returns the parsed draft."""
    draft = _draft()
    fake_client = FakeClient([draft])
    intake = FeatureIntake(llm="anthropic:claude-haiku-4-5")

    with patch(
        "parrot.clients.factory.LLMFactory.create", return_value=fake_client
    ):
        result = await intake.generate("I want a dark mode toggle")

    assert result is draft
    assert len(fake_client.prompts) == 1


@pytest.mark.asyncio
async def test_generate_retries_once_on_validation():
    """A ValidationError on the first call triggers exactly one retry."""
    draft = _draft()
    fake_client = FakeClient([_validation_error(), draft])
    intake = FeatureIntake(llm="anthropic:claude-haiku-4-5")

    with patch(
        "parrot.clients.factory.LLMFactory.create", return_value=fake_client
    ):
        result = await intake.generate("I want a dark mode toggle")

    assert result is draft
    assert len(fake_client.prompts) == 2
    # The retry prompt must carry the validation error forward.
    assert "validation" in fake_client.prompts[1].lower()


@pytest.mark.asyncio
async def test_generate_raises_after_second_failure():
    """Two consecutive validation failures surface as a clear ValueError."""
    fake_client = FakeClient([_validation_error(), _validation_error()])
    intake = FeatureIntake(llm="anthropic:claude-haiku-4-5")

    with patch(
        "parrot.clients.factory.LLMFactory.create", return_value=fake_client
    ), pytest.raises(ValueError):
        await intake.generate("I want a dark mode toggle")

    assert len(fake_client.prompts) == 2


@pytest.mark.asyncio
async def test_regenerate_includes_guidance():
    """regenerate() folds the user's redo guidance into the prompt."""
    draft = _draft()
    fake_client = FakeClient([draft])
    intake = FeatureIntake(llm="anthropic:claude-haiku-4-5")

    with patch(
        "parrot.clients.factory.LLMFactory.create", return_value=fake_client
    ):
        result = await intake.regenerate("dark mode", "also cover the mobile app")

    assert result is draft
    assert "also cover the mobile app" in fake_client.prompts[0]


def test_write_document_frontmatter(tmp_path: Path):
    """Generated markdown carries FEAT-145 frontmatter."""
    intake = FeatureIntake(proposals_dir=tmp_path)
    path = intake.write_document(_draft())

    assert path.parent == tmp_path
    assert path.name == "add-dark-mode.brainstorm.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith(
        "---\n# SDD flow type and base branch (FEAT-145).\ntype: feature\nbase_branch: dev\n---\n"
    )
    assert "# Brainstorm: Add dark mode" in text


def test_write_document_collision_suffix(tmp_path: Path):
    """Slug collisions produce -2, -3, ... suffixes and never overwrite."""
    intake = FeatureIntake(proposals_dir=tmp_path)

    first = intake.write_document(_draft())
    second = intake.write_document(_draft())
    third = intake.write_document(_draft())

    assert first.name == "add-dark-mode.brainstorm.md"
    assert second.name == "add-dark-mode-2.brainstorm.md"
    assert third.name == "add-dark-mode-3.brainstorm.md"
    assert first.read_text() != "" and second.exists() and third.exists()


def test_write_document_sanitizes_slug(tmp_path: Path):
    """An LLM-provided slug with invalid characters is sanitized; empty falls back to title."""
    intake = FeatureIntake(proposals_dir=tmp_path)

    path = intake.write_document(_draft(slug="Dark Mode!! Toggle_now"))
    assert path.name == "dark-mode-toggle-now.brainstorm.md"

    path_empty_slug = intake.write_document(_draft(slug="", title="Totally New Feature"))
    assert path_empty_slug.name == "totally-new-feature.brainstorm.md"


def test_build_brief_assembly(tmp_path: Path):
    """build_brief() returns a FeatureBrief with document_kind='brainstorm'."""
    intake = FeatureIntake(proposals_dir=tmp_path)
    draft = _draft()
    document_path = intake.write_document(draft)

    brief = intake.build_brief(draft, document_path)

    assert brief.document_kind == "brainstorm"
    assert brief.document_path == str(document_path)
    assert brief.dev_agents is None
    assert brief.judge_panel is None


def test_build_brief_passes_through_pool_and_judges(tmp_path: Path):
    """Explicit dev_agents/judge_panel pass through unchanged."""
    from parrot.flows.dev_loop.models import DevAgentSpec, JudgePanelConfig, JudgeSpec

    intake = FeatureIntake(proposals_dir=tmp_path)
    draft = _draft()
    document_path = intake.write_document(draft)
    dev_agents = [DevAgentSpec(agent="codex", model="gpt-5.5", count=2)]
    judge_panel = JudgePanelConfig(judges=[JudgeSpec(agent="mantle", model="")])

    brief = intake.build_brief(
        draft, document_path, dev_agents=dev_agents, judge_panel=judge_panel
    )

    assert brief.dev_agents == dev_agents
    assert brief.judge_panel == judge_panel


@pytest.mark.asyncio
async def test_default_llm_key(monkeypatch: pytest.MonkeyPatch):
    """With DEV_LOOP_INTAKE_LLM unset, the factory receives the Haiku default."""
    draft = _draft()
    fake_client = FakeClient([draft])
    captured: dict = {}

    def _fake_create(llm: str, *args: Any, **kwargs: Any) -> FakeClient:
        captured["llm"] = llm
        return fake_client

    monkeypatch.delenv("DEV_LOOP_INTAKE_LLM", raising=False)
    with patch("parrot.clients.factory.LLMFactory.create", side_effect=_fake_create):
        await FeatureIntake().generate("something")

    assert captured["llm"] == DEFAULT_INTAKE_LLM


@pytest.mark.asyncio
async def test_custom_llm_key_via_conf(monkeypatch: pytest.MonkeyPatch):
    """Setting DEV_LOOP_INTAKE_LLM switches the resolved client spec."""
    draft = _draft()
    fake_client = FakeClient([draft])
    captured: dict = {}

    def _fake_create(llm: str, *args: Any, **kwargs: Any) -> FakeClient:
        captured["llm"] = llm
        return fake_client

    from parrot import conf

    monkeypatch.setattr(
        conf.config, "get", lambda key, fallback=None: "openai:gpt-5.5"
        if key == "DEV_LOOP_INTAKE_LLM" else fallback
    )
    with patch("parrot.clients.factory.LLMFactory.create", side_effect=_fake_create):
        await FeatureIntake().generate("something")

    assert captured["llm"] == "openai:gpt-5.5"
