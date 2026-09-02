"""Google Antigravity (agy) dispatch profile for the dev-loop flow.

Development seat only. ``agy`` remains a supported CODING agent; its
review profile was removed with ``GoogleCodingCodeReviewDispatcher``
after the reviewer ban (see ``models/base.py``'s ``JudgeBackend``).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class GoogleCodingDispatchProfile(BaseModel):
    """Declarative profile consumed by ``GoogleCodingDispatcher.dispatch()``.

    Targets the Google Antigravity CLI console (``agy``) in headless mode.
    """

    subagent: Literal["sdd-worker", "sdd-secondopinion", "sdd-research", "sdd-qa", "sdd-planner", "sdd-feedback"] = "sdd-worker"
    model: str = "auto"
    agent: Optional[str] = None
    effort: Optional[Literal["low", "medium", "high"]] = None
    mode: Literal["accept-edits", "plan"] = "accept-edits"
    dangerously_skip_permissions: bool = True
    sandbox: bool = True
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
