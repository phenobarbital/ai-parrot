# packages/ai-parrot/src/parrot/outputs/cards/inputs.py
"""Pydantic models for AC 1.5 input elements."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .elements import ACElement


class InputChoice(BaseModel):
    title: str
    value: str


class InputText(ACElement):
    element_type: Literal["Input.Text"] = "Input.Text"
    id: str
    placeholder: str = ""
    value: str = ""
    is_multiline: bool = False
    max_length: int | None = None
    regex: str | None = None
    style: Literal["Text", "Email", "Url", "Tel", "Password"] | None = None
    is_required: bool = False
    label: str | None = None
    error_message: str | None = None


class InputNumber(ACElement):
    element_type: Literal["Input.Number"] = "Input.Number"
    id: str
    placeholder: str = ""
    value: float | int | None = None
    min: float | int | None = None
    max: float | int | None = None
    is_required: bool = False
    label: str | None = None
    error_message: str | None = None


class InputToggle(ACElement):
    element_type: Literal["Input.Toggle"] = "Input.Toggle"
    id: str
    title: str
    value: str = "false"
    value_on: str = "true"
    value_off: str = "false"
    is_required: bool = False
    label: str | None = None


class InputDate(ACElement):
    element_type: Literal["Input.Date"] = "Input.Date"
    id: str
    value: str | None = None
    min: str | None = None
    max: str | None = None
    is_required: bool = False
    label: str | None = None


class InputTime(ACElement):
    element_type: Literal["Input.Time"] = "Input.Time"
    id: str
    value: str | None = None
    min: str | None = None
    max: str | None = None
    is_required: bool = False
    label: str | None = None


class InputChoiceSet(ACElement):
    element_type: Literal["Input.ChoiceSet"] = "Input.ChoiceSet"
    id: str
    choices: list[InputChoice] = []
    value: str | None = None
    is_multi_select: bool = False
    style: Literal["compact", "expanded", "filtered"] | None = None
    is_required: bool = False
    label: str | None = None
