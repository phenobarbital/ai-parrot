"""Transport-free inter-agent protocol contract shared by Squawk and Roost.

This package never imports transport or policy implementations.
"""

from parrot.interagent.descriptors import HandleDescriptor, MediaType
from parrot.interagent.errors import SquawkError, SquawkErrorCode
from parrot.interagent.handles import (
    ArtifactHandle,
    HandleClaimError,
    HandleOwner,
    HandleStore,
    InMemoryHandleStore,
    handle_key,
)
from parrot.interagent.provenance import HandleProvenance

__all__ = [
    "ArtifactHandle",
    "HandleClaimError",
    "HandleDescriptor",
    "HandleOwner",
    "HandleProvenance",
    "HandleStore",
    "InMemoryHandleStore",
    "MediaType",
    "SquawkError",
    "SquawkErrorCode",
    "handle_key",
]
