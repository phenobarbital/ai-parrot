"""Shared context only; concrete source collectors are imported at execution."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from parrot.knowledge.wiki.project import StandupConfig
from parrot.knowledge.wiki.standup.identity import StandupIdentity
from parrot.knowledge.wiki.standup.models import PeriodWindow
from parrot.knowledge.wiki.store import BaseWikiStore


class CollectContext(BaseModel):
    """Explicit shared read context and per-run diagnostic accumulators."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    root: Path
    store: BaseWikiStore
    cfg: StandupConfig
    window: PeriodWindow
    identity: StandupIdentity
    team: bool = False
    diagnostics: list[str] = Field(default_factory=list)
    unmapped_statuses: dict[str, int] = Field(default_factory=dict)
