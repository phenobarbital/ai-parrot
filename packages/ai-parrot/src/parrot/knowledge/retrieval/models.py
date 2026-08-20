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
from typing import Literal

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
