"""Domain-neutral data models for BusinessAutomationToolkit.

FEAT-453, Module 5 (Goals G4, G5). These models contain zero site-specific
identifiers — the generic engine is public; site plans (e.g. a specific
bookkeeping-product integration) stay in an external, private plans
directory (Module 6) loaded at runtime.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from parrot_tools.scraping import ParamSpec


class OperationKind(str, Enum):
    """Whether an operation has legal effect, which decides the submit gate.

    - ``READ`` — never gated; pure lookups.
    - ``DRAFT`` — unattended; assembles data but does not submit/commit.
    - ``SUBMIT`` — ALWAYS gated behind human confirmation (Decision D2).
    """

    READ = "read"
    DRAFT = "draft"
    SUBMIT = "submit"


class BusinessOperation(BaseModel):
    """One named, parameterized business operation backed by a ScrapingFlow.

    Attributes:
        name: Operation identifier, referenced by
            :meth:`BusinessAutomationToolkit.run_operation`.
        description: Human-readable summary.
        kind: Legal-effect classification — decides whether this operation
            is gated by :class:`~parrot.auth.confirmation.ConfirmationGuard`.
        flow_ref: The :class:`~parrot_tools.scraping.ScrapingFlow` name
            resolved from the plans directory (Module 6).
        params: Declared parameters (reuses the scraping DSL's
            :class:`~parrot_tools.scraping.ParamSpec`).
        confirm_prompt: Optional briefing template shown to the human at the
            SUBMIT gate (falls back to a generic listing when unset).
    """

    name: str
    description: str
    kind: OperationKind
    flow_ref: str = Field(description="ScrapingFlow name in the plans dir")
    params: List[ParamSpec] = Field(default_factory=list)
    confirm_prompt: Optional[str] = Field(default=None, description="Shown to the human at the SUBMIT gate")


class ImportRun(BaseModel):
    """Discriminates one bank-statement import from another.

    Injected into a flow's ``global_params`` (Decision D3) so two
    legitimate imports with identical logical parameters (e.g. the same
    ``period``) never collide on the same checkpoint token — otherwise the
    second import would resume the first's checkpoint and silently skip
    every row it believes is already done.
    """

    statement_digest: str
    period: str
    started_at: datetime
