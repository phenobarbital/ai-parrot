# packages/ai-parrot/src/parrot/outputs/cards/spec.py
"""CardSpec — top-level Adaptive Card specification."""
from __future__ import annotations

from navconfig import config
from pydantic import BaseModel

from .actions import ACAction
from .sections import CardSection
from .toggle import AutoCollapsePolicy

DEFAULT_ADAPTIVE_CARD_VERSION: str = config.get("ADAPTIVE_CARD_VERSION") or "1.4"


class CardSpec(BaseModel):
    title: str | None = None
    summary: str | None = None
    sections: list[CardSection] = []
    actions: list[ACAction] = []
    auto_collapse: AutoCollapsePolicy | None = None
    version: str = DEFAULT_ADAPTIVE_CARD_VERSION
    schema_url: str = "http://adaptivecards.io/schemas/adaptive-card.json"
