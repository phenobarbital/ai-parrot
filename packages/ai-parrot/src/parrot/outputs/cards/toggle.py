# packages/ai-parrot/src/parrot/outputs/cards/toggle.py
"""Toggle group and auto-collapse policy models."""
from __future__ import annotations

from pydantic import BaseModel

from .elements import ACElement


class ToggleGroup(BaseModel):
    label_expanded: str = "Hide details"
    label_collapsed: str = "Show details"
    content: list[ACElement]
    initially_visible: bool = False
    group_id: str | None = None


class AutoCollapsePolicy(BaseModel):
    enabled: bool = True
    table_row_threshold: int = 15
    text_char_threshold: int = 500
    code_line_threshold: int = 10
    image_count_threshold: int = 2
