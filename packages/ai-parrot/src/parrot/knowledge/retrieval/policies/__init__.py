"""Retrieval policies (spec §5) — the four-stage seed/expand/prune/assemble
implementations `QueryClassifier` routes queries to.

Grows task by task: `DirectSymbolPolicy` (TASK-2280), `VectorSeedPolicy`
(TASK-2281), and later `PersonalizedPageRankPolicy`/`SteinerTreePolicy`/
`AncestrySummaryPolicy`/`RationalePolicy` (v1.1). The full
``RetrievalPolicy`` discriminated union (spec §5.0) is assembled here,
below, and grows as later policies land — a closed set: "Adding a policy
is a spec change, not a config change."

Lives here (not in `models.py`) because `models.py` is imported BY every
policy module (`NodeRef`, `Evidence`, etc.) — a `RetrievalPolicy` union
referencing concrete policy classes there would be a circular import.
This package already imports every policy class, so it is the natural,
non-circular home.
"""

from typing import Annotated

from pydantic import Field

from parrot.knowledge.retrieval.policies.base import (
    RetrievalPolicyProtocol,
    Seed,
    Subgraph,
)
from parrot.knowledge.retrieval.policies.direct_symbol import DirectSymbolPolicy
from parrot.knowledge.retrieval.policies.vector_seed import VectorSeedPolicy

#: The v1-cut `RetrievalPolicy` discriminated union (spec §5.0). Only the
#: two implemented policies are members — `PersonalizedPageRankPolicy`/
#: `SteinerTreePolicy`/`AncestrySummaryPolicy`/`RationalePolicy` join this
#: union when their tasks land (v1.1), never before, since a class that
#: doesn't exist can't be a discriminated-union member.
RetrievalPolicy = Annotated[
    DirectSymbolPolicy | VectorSeedPolicy,
    Field(discriminator="kind"),
]

__all__ = [
    "DirectSymbolPolicy",
    "RetrievalPolicy",
    "RetrievalPolicyProtocol",
    "Seed",
    "Subgraph",
    "VectorSeedPolicy",
]
