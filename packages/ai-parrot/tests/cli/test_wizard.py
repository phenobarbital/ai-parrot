"""Unit tests for the generic PydanticWizard engine."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Literal, Optional
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, Field
from rich.console import Console

from parrot.cli.wizard import PydanticWizard, WizardConfig, WizardFieldOverride


# ── Test models ─────────────────────────────────────────────────────────────

class SimpleModel(BaseModel):
    name: str = Field(..., description="Your name")
    age: int = Field(default=25)
    active: bool = Field(default=True)


class LiteralModel(BaseModel):
    kind: Literal["bug", "enhancement", "new_feature"] = "bug"
    title: str = Field(..., min_length=1)


class OptionalModel(BaseModel):
    label: str = Field(...)
    comment: Optional[str] = None


class NestedChild(BaseModel):
    x: int = Field(default=0)
    y: int = Field(default=0)


class NestedModel(BaseModel):
    name: str = "parent"
    child: NestedChild = Field(default_factory=NestedChild)


class ListItemA(BaseModel):
    kind: Literal["a"] = "a"
    val: str = ""


class ListItemB(BaseModel):
    kind: Literal["b"] = "b"
    num: int = 0


class ListModel(BaseModel):
    items: List[ListItemA | ListItemB] = Field(..., min_length=1)


class ScalarListModel(BaseModel):
    tags: List[str] = Field(default_factory=list)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_wizard(model, inputs: list[str], **kwargs):
    """Build a wizard with a mock prompt session returning scripted inputs."""
    session = AsyncMock()
    session.prompt_async = AsyncMock(side_effect=inputs)
    console = Console(record=True, force_terminal=True, width=120)
    return PydanticWizard(model, console=console, session=session, **kwargs)


# ── Scalar fields ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_scalar_fields():
    wizard = _make_wizard(SimpleModel, ["Alice", "30", "n"])
    result = await wizard.collect()
    assert result.name == "Alice"
    assert result.age == 30
    assert result.active is False


@pytest.mark.asyncio
async def test_wizard_scalar_defaults():
    wizard = _make_wizard(SimpleModel, ["Bob", "", ""])
    result = await wizard.collect()
    assert result.name == "Bob"
    assert result.age == 25
    assert result.active is True


# ── Literal choice ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_literal_choice():
    wizard = _make_wizard(LiteralModel, ["2", "Fix login"])
    result = await wizard.collect()
    assert result.kind == "enhancement"
    assert result.title == "Fix login"


@pytest.mark.asyncio
async def test_wizard_literal_default():
    wizard = _make_wizard(LiteralModel, ["", "Some title"])
    result = await wizard.collect()
    assert result.kind == "bug"


# ── Optional fields ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_optional_skip():
    wizard = _make_wizard(OptionalModel, ["Required label", ""])
    result = await wizard.collect()
    assert result.label == "Required label"
    assert result.comment is None


@pytest.mark.asyncio
async def test_wizard_optional_fill():
    wizard = _make_wizard(OptionalModel, ["Label", "My comment"])
    result = await wizard.collect()
    assert result.comment == "My comment"


# ── Nested submodel ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_nested_submodel():
    wizard = _make_wizard(NestedModel, ["parent-name", "10", "20"])
    result = await wizard.collect()
    assert result.name == "parent-name"
    assert result.child.x == 10
    assert result.child.y == 20


# ── List with discriminated union variants ──────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_list_variants():
    # Enter interactively (skip file load), pick variant 'a', fill submodel fields, no more
    wizard = _make_wizard(
        ListModel,
        [
            "",       # skip file load prompt
            "1",      # variant: a
            "",       # kind (Literal default 'a')
            "hello",  # val
            "n",      # add another? no
        ],
    )
    result = await wizard.collect()
    assert len(result.items) == 1
    assert isinstance(result.items[0], ListItemA)
    assert result.items[0].val == "hello"


# ── File input (@path) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_file_input_text(tmp_path):
    desc_file = tmp_path / "desc.txt"
    desc_file.write_text("This is the description from a file.")
    config = WizardConfig(
        overrides={"comment": WizardFieldOverride(file_loadable=True)}
    )
    wizard = _make_wizard(
        OptionalModel,
        ["Label", f"@{desc_file}"],
        config=config,
    )
    result = await wizard.collect()
    assert "description from a file" in result.comment


@pytest.mark.asyncio
async def test_wizard_file_input_yaml_list(tmp_path):
    items_file = tmp_path / "items.yaml"
    items_file.write_text('- kind: a\n  val: "from-file"\n')
    wizard = _make_wizard(
        ListModel,
        [f"@{items_file}"],  # file load at list prompt
    )
    result = await wizard.collect()
    assert len(result.items) == 1
    assert result.items[0].val == "from-file"


# ── Initial values (skip pre-filled fields) ────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_initial_values():
    wizard = _make_wizard(SimpleModel, ["", ""])
    result = await wizard.collect(initial={"name": "Pre-set", "age": 42})
    assert result.name == "Pre-set"
    assert result.age == 42
    assert result.active is True  # default kept


# ── Validation error ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_validation_error_raises():
    from pydantic import ValidationError
    # Pre-set kind and provide EOFError for title (min_length=1 violation).
    # The wizard catches EOF and breaks out, leaving title missing.
    session = AsyncMock()
    session.prompt_async = AsyncMock(side_effect=EOFError())
    console = Console(record=True, force_terminal=True, width=120)
    wizard = PydanticWizard(LiteralModel, console=console, session=session)
    with pytest.raises(ValidationError):
        await wizard.collect(initial={"kind": "bug"})


# ── Bool fields ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_bool_yes():
    wizard = _make_wizard(SimpleModel, ["Name", "18", "y"])
    result = await wizard.collect()
    assert result.active is True


# ── WorkBrief roundtrip ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_workbrief_roundtrip():
    pytest.importorskip("parrot.flows.dev_loop.models", reason="dev-loop models require Cython build")
    from parrot.flows.dev_loop.models import WorkBrief  # noqa: PLC0415
    inputs = [
        "1",                           # kind: bug (Literal choice #1)
        "Customer sync drops last row", # summary
        "Detailed description here",   # description
        "etl-service",                 # affected_component
        "",                            # log_sources: skip file load
        "",                            # log_sources: empty = no items (Enter to finish)
        "",                            # acceptance_criteria: skip file load
        "1",                           # variant: flowtask
        "etl/sync.yaml",              # task_path
        "",                            # args default
        "",                            # timeout default
        "",                            # exit code default
        "criterion-1",                 # name
        "n",                           # add another? no
        "user@example.com",           # escalation_assignee
        "reporter@example.com",       # reporter
        "",                            # existing_issue_key (optional)
        "",                            # dev_agents (optional)
        "",                            # dev_isolation (optional)
    ]
    wizard = _make_wizard(WorkBrief, inputs)
    result = await wizard.collect()
    assert result.kind == "bug"
    assert result.summary == "Customer sync drops last row"
    assert result.affected_component == "etl-service"
