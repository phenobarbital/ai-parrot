"""Channel-neutral dev-loop kick-off integration (FEAT-555).

Transport adapters (Slack today) live next to their platform packages; this
package owns parsing, brief building, subprocess lifecycle, state tailing and
the dispatch service.
"""

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

__all__ = [
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
]
