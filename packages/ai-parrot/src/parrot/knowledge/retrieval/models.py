"""Node identity primitives for the GraphIndex Retrieval Layer.

Implements spec §3.1 (FEAT-435, TASK-2270): ``NodeRef``, the
``parrot-graph://`` URI scheme, and ``EdgeRef``.

``NodeRef`` is the identity primitive for the whole retrieval layer: every
``Evidence`` (TASK-2271), every ``WikiPage.scope`` (TASK-2283), and every
resolved anchor (TASK-2276) is one. It must round-trip losslessly through
the ``parrot-graph://`` URI form so a ``ContextBundle`` can be serialized,
replayed offline, and cited in a trace (spec §8).

Corrected from the spec's original draft (verified against
``parrot/knowledge/graphindex/schema.py``): ``NodeKind`` has a single
``SYMBOL`` member — there is no ``Module``/``Class``/``Function`` split in
the enum. That distinction lives in ``domain_tags["symbol_type"]`` on L0
nodes, so ``NodeRef`` carries both ``kind: NodeKind`` and
``symbol_type: str | None`` as separate fields (spec §3.1, §14.2).
"""

from __future__ import annotations

import logging
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind

logger = logging.getLogger(__name__)

_SCHEME = "parrot-graph://"

# A concrete git SHA: 7-40 lowercase/uppercase hex characters. This is what
# rejects symbolic revs like "HEAD", "main", "dev", "staging", "v1.0" — none
# of those are valid hex strings of the right length (spec §3.1: "rev is a
# concrete SHA, never a symbolic ref").
_REV_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


class NodeRef(BaseModel):
    """Identity of a single L0 node, addressable via a ``parrot-graph://`` URI.

    Attributes:
        repo: Repository name (e.g. ``"ai-parrot"``, ``"fieldsync"``).
        rev: Concrete git SHA the node was resolved at. Never a symbolic
            ref (``HEAD``, branch names, tags) — validated at construction.
        path: Repo-relative file path the node lives in.
        kind: The L0 ``NodeKind`` (``SYMBOL``, ``RATIONALE``, ``SECTION``,
            ``CONCEPT``, ...). Real L0 enum — see
            ``parrot.knowledge.graphindex.schema.NodeKind``.
        symbol_type: For ``SYMBOL`` nodes, one of ``"module"``, ``"class"``,
            ``"function"`` — read from L0's ``domain_tags["symbol_type"]``.
            ``None`` for non-symbol node kinds.
        qualname: Dotted qualified name (module.Class.method). Derived, not
            read verbatim from L0 (spec §3.5.2) — this task only defines the
            identity shape, not how qualnames are computed (TASK-2276).

    Note:
        The URI fragment encodes both ``kind`` and ``symbol_type`` so that
        ``NodeRef.parse(ref.uri) == ref`` holds for every constructible
        ``NodeRef`` (a value not otherwise recoverable from the
        ``{kind}:{qualname}`` shape alone would break the acceptance
        criterion's round-trip property). The encoding is
        ``{kind}[{symbol_type}]:{qualname}`` when ``symbol_type`` is set,
        and plain ``{kind}:{qualname}`` when it is ``None``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    rev: str
    path: str
    kind: NodeKind
    symbol_type: str | None = None
    qualname: str

    @field_validator("rev")
    @classmethod
    def _validate_rev(cls, value: str) -> str:
        """Reject symbolic revs; only a concrete hex SHA is accepted."""
        if not _REV_RE.match(value):
            raise ValueError(
                f"NodeRef.rev must be a concrete git SHA (7-40 hex chars); "
                f"got symbolic or malformed ref: {value!r}"
            )
        return value

    @property
    def uri(self) -> str:
        """Serialize to ``parrot-graph://{repo}@{rev}/{path}#{kind}:{qualname}``."""
        kind_part = self.kind.value
        if self.symbol_type is not None:
            kind_part = f"{kind_part}[{self.symbol_type}]"
        return f"{_SCHEME}{self.repo}@{self.rev}/{self.path}#{kind_part}:{self.qualname}"

    @classmethod
    def parse(cls, uri: str) -> NodeRef:
        """Parse a ``parrot-graph://`` URI back into a ``NodeRef``.

        Exact inverse of ``.uri``. Splitting order (deliberately, so paths
        containing ``#`` or ``@`` still round-trip):

        1. Split off the fragment on the LAST ``#``.
        2. Split off the path on the FIRST ``/`` after the authority
           (``rev`` never contains ``/``, so this boundary is unambiguous).
        3. Split ``repo`` from ``rev`` on the LAST ``@`` (``rev`` never
           contains ``@``, so a ``repo`` containing ``@`` still survives).
        4. Split ``kind[symbol_type]`` from ``qualname`` on the FIRST ``:``.

        Args:
            uri: A ``parrot-graph://`` URI, typically produced by ``.uri``.

        Returns:
            The parsed ``NodeRef``.

        Raises:
            ValueError: If the URI does not start with the expected scheme
                or is missing a required component.
        """
        if not uri.startswith(_SCHEME):
            raise ValueError(f"Not a parrot-graph:// URI: {uri!r}")
        rest = uri[len(_SCHEME):]

        before_hash, hash_sep, after_hash = rest.rpartition("#")
        if not hash_sep:
            raise ValueError(f"Missing '#{{kind}}:{{qualname}}' fragment: {uri!r}")

        repo_and_rev, slash_sep, path = before_hash.partition("/")
        if not slash_sep:
            raise ValueError(f"Missing '/' path separator: {uri!r}")

        repo, at_sep, rev = repo_and_rev.rpartition("@")
        if not at_sep:
            raise ValueError(f"Missing '@' between repo and rev: {uri!r}")

        kind_part, colon_sep, qualname = after_hash.partition(":")
        if not colon_sep:
            raise ValueError(f"Missing ':' between kind and qualname: {uri!r}")

        symbol_type: str | None = None
        kind_str = kind_part
        if kind_part.endswith("]") and "[" in kind_part:
            kind_str, _, bracketed = kind_part.partition("[")
            symbol_type = bracketed[:-1]

        return cls(
            repo=repo,
            rev=rev,
            path=path,
            kind=NodeKind(kind_str),
            symbol_type=symbol_type,
            qualname=qualname,
        )


class EdgeRef(BaseModel):
    """A single traversed edge, recording how a node was reached from a seed.

    Used by ``Evidence.edge_path`` (TASK-2271) to make PPR/expansion traces
    replayable and attributable (spec §3.2, §3.5.3).

    Attributes:
        source: The edge's source ``NodeRef``.
        target: The edge's target ``NodeRef``.
        kind: The L0 ``EdgeKind`` (``CONTAINS``, ``REFERENCES``, ...).
        derivation: How the edge was derived — ``"ast"`` for intra-repo
            parser-exact edges, ``"package_metadata"`` for cross-repo edges
            resolved via ``PackageRepoMap`` (spec §5.3.1).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: NodeRef
    target: NodeRef
    kind: EdgeKind
    derivation: Literal["ast", "package_metadata"]


class EvidenceOrigin(StrEnum):
    """Where a `ContextUnit`'s text came from.

    Closed set, widened pre-emptively for the cross-corpus bridge (OQ-6).
    The ``L2_*`` members are **RESERVED**: declared now so the union is
    stable across a future spec, but no retrieval policy in THIS feature may
    emit them until the cross-corpus bridge spec lands. Emitting a reserved
    origin from a policy is a contract violation, caught by the
    TASK-2272 parametrised contract test.

    Attributes:
        L0_SOURCE: Raw source excerpt read directly from the L0 graph.
        L1_WIKI: Prose from an LLM-synthesized `WikiSection`.
        L1_RATIONALE: Prose sourced from a `Rationale` L0 node / wiki
            ``## Rationale`` section.
        L2_DOC: RESERVED — ADRs, SDD specs, tickets. Not emittable in v1.
        L2_NORM: RESERVED — legal/regulatory clauses (Fieldsync). Not
            emittable in v1.
        L2_EXTERNAL: RESERVED — third-party dependency docs. Not emittable
            in v1.
    """

    L0_SOURCE = "l0_source"
    L1_WIKI = "l1_wiki"
    L1_RATIONALE = "l1_rationale"
    L2_DOC = "l2_doc"
    L2_NORM = "l2_norm"
    L2_EXTERNAL = "l2_external"


class Evidence(BaseModel):
    """Provenance for a single retrieved unit, sufficient to attribute it.

    Satisfies INV-4: every unit in a `ContextBundle` must be traceable to
    ``file:line_span`` at a concrete rev, except `RATIONALE`-kind evidence
    (``line_span`` may be ``None`` until the L0 lineno fix lands — RQ-4).

    Attributes:
        node: The `NodeRef` this evidence is about.
        digest: Content hash of the L0 node at ``rev``, computed over the
            bytes actually served (spec §3.5.1). Populated by TASK-2273;
            this task only defines the field.
        digest_scope: The granularity the digest was computed at
            (``"span"``/``"file"``/``"summary"``). Left as a plain ``str``
            here — tightened to the `DigestScope` enum once TASK-2273 lands.
        line_span: ``(start_line, end_line)``, or ``None`` for nodes with no
            line span (rationale, module-level, synthetic nodes).
        edge_path: How this node was reached from the seed set — empty for
            direct hits (`DirectSymbolPolicy`), populated for traversal
            policies.
        origin: Where the served text came from — see `EvidenceOrigin`.
        score: Policy-local relevance score. **Not comparable across
            policies** — each policy has its own scale and semantics; do not
            sort or threshold scores from different policies together.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    node: NodeRef
    digest: str
    digest_scope: str
    line_span: tuple[int, int] | None = None
    edge_path: tuple[EdgeRef, ...] = ()
    origin: EvidenceOrigin
    score: float


class ContextUnit(BaseModel):
    """A single attributable piece of retrieved context.

    Attributes:
        text: The source excerpt or wiki prose actually served to the caller.
        evidence: Provenance for ``text`` — see `Evidence`.
        token_estimate: Estimated token count of ``text``, used for budget
            accounting against `RetrievalBudget.max_tokens`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    evidence: Evidence
    token_estimate: int


class ContextBundle(BaseModel):
    """The retrieval layer's output: a bounded, attributable set of units.

    Attributes:
        schema_version: Bump on any breaking change to this shape. Declared
            explicitly (unlike `EventEnvelope`'s past omission) so persisted
            and traced bundles remain interpretable across versions.
        units: The retrieved, budget-bounded context units.
        decision: The full routing trace that produced this bundle —
            `RetrievalRoutingDecision` (TASK-2278). Typed ``Any`` here
            because that model does not exist yet; tighten the annotation
            when TASK-2278 lands.
        truncated: INV-5 — ``True`` iff the budget was exhausted before the
            policy completed. Partial results are flagged, never disguised.
        stale_sources: INV-2 — nodes whose backing wiki section was served
            stale (with a staleness marker) rather than freshly regenerated.
        token_total: Sum of ``token_estimate`` across ``units``.
        elapsed_ms: Wall-clock time spent producing this bundle.
        mixed_freshness: RQ-2 — ``True`` when the selected `WikiSection`s do
            not all share one `coherence_group`, i.e. the bundle describes
            more than one point-in-time state of the code. Surfaced, not
            prevented.
        index_pin_mismatch: §3.5.3 — ``True`` when the sampled pin-coherence
            check found a mismatch and the request was served anyway under
            ``budget.allow_stale``.
        boundary_truncation: §5.3.1 — ``True`` when traversal was terminated
            at a cross-repo boundary because the target repo is absent from
            `WorkspacePin.pins`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    units: tuple[ContextUnit, ...]
    decision: Any
    truncated: bool
    stale_sources: tuple[NodeRef, ...] = ()
    token_total: int
    elapsed_ms: float
    mixed_freshness: bool = False
    index_pin_mismatch: bool = False
    boundary_truncation: bool = False


class RetrievalBudget(BaseModel):
    """Bounds a retrieval request must respect (INV-5: budget honesty).

    Attributes:
        deadline_ms: Wall-clock deadline for the whole request. Policies are
            interruptible and must return the best partial result rather
            than overrun.
        max_tokens: Maximum total token budget across all `ContextUnit`s.
        max_llm_calls: ``0`` = synthesis-free path (no L1 regeneration
            allowed); ``>0`` permits L1 lazy fill / regeneration.
        max_expansion_nodes: Upper bound on nodes visited during traversal
            (`expand` stage of `RetrievalPolicyProtocol`).
        allow_stale: Whether a stale `WikiSection` may be served with a
            staleness marker, versus falling back to L0 source excerpts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    deadline_ms: int = 800
    max_tokens: int = 12_000
    max_llm_calls: int = 0
    max_expansion_nodes: int = 400
    allow_stale: bool = True


class RetrievalRequest(BaseModel):
    """A single retrieval request over a pinned workspace.

    Attributes:
        query: The natural-language question to answer.
        workspace: The frozen set of repo/rev pins this request is scoped
            to. Typed ``Any`` here because `WorkspacePin` (TASK-2274) does
            not exist yet; tighten the annotation when it lands.
        budget: The `RetrievalBudget` this request must respect.
        policy_override: Escape hatch — bypasses `QueryClassifier` and
            forces a specific policy. Logged with
            ``matched_rule="OVERRIDE"``. Typed ``Any`` here because
            `RetrievalPolicy` (TASK-2280 onward) does not exist yet.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    workspace: Any
    budget: RetrievalBudget = RetrievalBudget()
    policy_override: Any | None = None
