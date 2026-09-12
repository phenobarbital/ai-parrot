"""Channel-neutral dev-loop kick-off integration (FEAT-555).

Transport adapters (Slack today) live next to their platform packages; this
package owns parsing, brief building, subprocess lifecycle, state tailing and
the dispatch service.
"""

from .briefs import brief_summary_fields, brief_to_file, build_bug_brief, build_feature_brief
from .models import (
    BridgeResult,
    CommandSyntaxError,
    DevLoopCommand,
    DevLoopError,
    DevLoopIntegrationConfig,
    GateView,
    NotRunOwnerError,
    PendingConfirmation,
    Requester,
    RequestType,
    RunEvent,
    RunNotFoundError,
    RunRecord,
    SpawnError,
)
from .parser import USAGE, parse_command

__all__ = [
    "USAGE",
    "BridgeResult",
    "CommandSyntaxError",
    "DevLoopCommand",
    "DevLoopError",
    "DevLoopIntegrationConfig",
    "GateView",
    "NotRunOwnerError",
    "PendingConfirmation",
    "Requester",
    "RequestType",
    "RunEvent",
    "RunNotFoundError",
    "RunRecord",
    "SpawnError",
    "brief_summary_fields",
    "brief_to_file",
    "build_bug_brief",
    "build_feature_brief",
    "parse_command",
]
