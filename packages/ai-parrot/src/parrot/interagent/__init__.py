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
from parrot.interagent.contract import (
    CAP_ID_PATTERN,
    CapabilityCategory,
    ContractDelta,
    PolicyAnnotations,
    ReturnsSpec,
    SquawkCapability,
    SquawkContract,
    category_hash,
    contract_delta,
)
from parrot.interagent.ledger import CallCost, CallerIdentity, ServedLedgerEntry

__all__ = [
    "ArtifactHandle",
    "CAP_ID_PATTERN",
    "CallCost",
    "CallerIdentity",
    "CapabilityCategory",
    "ContractDelta",
    "HandleClaimError",
    "HandleDescriptor",
    "HandleOwner",
    "HandleProvenance",
    "HandleStore",
    "InMemoryHandleStore",
    "MediaType",
    "PolicyAnnotations",
    "ReturnsSpec",
    "ServedLedgerEntry",
    "SquawkCapability",
    "SquawkContract",
    "SquawkError",
    "SquawkErrorCode",
    "category_hash",
    "contract_delta",
    "handle_key",
]
