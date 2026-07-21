# packages/ai-parrot/src/parrot/outputs/cards/actions.py
"""Pydantic models for AC 1.5 actions."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ACAction(BaseModel):
    """Base for all Adaptive Card actions."""
    action_type: str
    title: str
    style: Literal["default", "positive", "destructive"] | None = None


class ActionSubmit(ACAction):
    action_type: Literal["Action.Submit"] = "Action.Submit"
    data: dict[str, Any] = {}
    associated_inputs: Literal["Auto", "None"] | None = None


class ActionOpenUrl(ACAction):
    action_type: Literal["Action.OpenUrl"] = "Action.OpenUrl"
    url: str


class TargetElement(BaseModel):
    element_id: str
    is_visible: bool | None = None


class ActionToggleVisibility(ACAction):
    action_type: Literal["Action.ToggleVisibility"] = "Action.ToggleVisibility"
    target_elements: list[TargetElement] = []


class ActionShowCard(ACAction):
    action_type: Literal["Action.ShowCard"] = "Action.ShowCard"
    card: Any  # typed as CardSpec at runtime; Any avoids circular import
