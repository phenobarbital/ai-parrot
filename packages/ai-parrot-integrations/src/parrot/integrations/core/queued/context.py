"""Context-local access to a running command job."""

import logging
from contextvars import ContextVar
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from .models import Requester

LOGGER = logging.getLogger(__name__)


class CommandJobContext(BaseModel):
    """The current command's job identity and progress owner."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    job_id: str
    command: str
    requester: Requester
    service: Any


current_command_job: ContextVar[Optional[CommandJobContext]] = ContextVar("current_command_job", default=None)


async def report_command_progress(message: str) -> None:
    """Record progress for the current queued command without raising."""

    context = current_command_job.get()
    if context is None:
        return
    try:
        await context.service.manager.update_metadata(context.job_id, progress=str(message))
    except Exception:  # pylint: disable=broad-except
        LOGGER.warning("Failed to report progress for queued job %s", context.job_id, exc_info=True)


def current_job_id() -> Optional[str]:
    """Return the running job ID, or ``None`` outside queued execution."""

    context = current_command_job.get()
    return context.job_id if context else None
