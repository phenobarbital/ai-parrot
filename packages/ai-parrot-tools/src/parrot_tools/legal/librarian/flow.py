"""The retrieval DAG (FEAT-449 §2 Overview flow, §3 M6).

    query
      -> as_of_extract    (regex-first; structured LLM micro-call only for
                            genuinely ambiguous multi-date queries — R9)
      -> graph_retrieve    (explicit-id pass, then search_articles view
                            pattern — all inside the ArangoDB tenant, R14/R15)
      -> dossier_build     (PayloadEntry assembly, precedence order)
      -> LegalLibrarianAgent.draft()  (DraftAnswer; dossier span ids
                            enumerated in the prompt — R12)
      -> span_verify       (existence gate + anchor integrity + suppression
                            records — R4)
      -> ground             (GroundednessScorer atom check over the
                            surviving guide)

Every stage except the librarian LLM call is a deterministic callable —
pure code, no LLM, no network (skeleton §5.3). ``answer()`` runs the six
stages as direct, sequential async calls rather than through
``AgentCrew.run_flow``'s ``ToolNode`` template-placeholder plumbing: flow
mode passes data between nodes via ``{input}`` / ``{nodes.<id>.output}``
string-templated placeholders resolved into a SINGLE tool call's
args/kwargs, which does not fit this pipeline's fan-in shape (e.g.
``dossier_build`` needs BOTH ``graph_retrieve``'s hits AND
``as_of_extract``'s ``as_of`` AND the tenant ``store``/``ctx``, none of
which are plain strings) — see this task's Completion Note for the full
reasoning. ``build_legal_librarian_crew`` still builds a structurally
faithful ``AgentCrew`` (six registered nodes, `ToolNode` dependencies
wired) as a discoverable, inspectable artifact; ``answer()`` is the
executed/tested path.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from parrot.bots.flows.crew import AgentCrew, CrewAgentNode
from parrot.models.basic import ToolCall
from parrot.security.groundedness.evidence import EvidenceIndex
from parrot.security.groundedness.policy import GroundednessPolicy
from parrot.security.groundedness.scorer import GroundednessScorer
from parrot.tools.abstract import AbstractTool

from parrot_tools.legal.boe.queries import article_in_force, search_articles
from parrot_tools.legal.ids import is_valid_boe_id

from .as_of import extract_as_of, regex_dates
from .models import LegalAnswer, PayloadEntry, ReadingNote, SpanRef, SuppressionRecord
from .suppression import SuppressionLog
from .verifier import SpanVerifier

_ARTICULO_KEY_RE = re.compile(r"\bBOE-[A-Z]-\d{4}-\d+:[A-Za-z0-9_\-.@()+,=;$!*'%]+\b")
_DOSSIER_LIMIT = 20
_TRUNCATE_AT = 4000
_HEAD_CHARS = 2000
_TAIL_CHARS = 1000


@runtime_checkable
class LibrarianLike(Protocol):
    """Structural protocol satisfied by ``LegalLibrarianAgent`` and test doubles."""

    async def draft(self, enumerated_dossier: str, query: str, as_of: date) -> Any: ...

    async def ask(self, *args: Any, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# Stage 1: as_of_extract
# ---------------------------------------------------------------------------


async def as_of_extract(query: str, *, llm_ask) -> dict[str, Any]:
    """Resolve the ``as_of`` date for a query (R9).

    Regex-first: exactly one distinct date is used immediately. Zero
    distinct dates default directly to ``date.today()`` — no LLM call
    for the (overwhelmingly common) case of a query that doesn't mention
    a date at all. More than one distinct (genuinely ambiguous) date
    triggers the ONE structured LLM micro-call (``extract_as_of``).

    Args:
        query: The user's query text.
        llm_ask: Injected async callable bound to the librarian's ``ask``,
            used only for the genuinely-ambiguous multi-date fallback.

    Returns:
        ``{"query": query, "as_of": <resolved date>}``.
    """
    distinct_dates = set(regex_dates(query))
    if len(distinct_dates) == 1:
        as_of = next(iter(distinct_dates))
    elif len(distinct_dates) == 0:
        as_of = datetime.now(UTC).date()
    else:
        as_of = await extract_as_of(query, llm_ask)
        if as_of is None:
            as_of = datetime.now(UTC).date()
    return {"query": query, "as_of": as_of}


# ---------------------------------------------------------------------------
# Stage 2: graph_retrieve
# ---------------------------------------------------------------------------


def _extract_explicit_articulo_keys(query: str) -> list[str]:
    """Find explicit ``articulo_key``-shaped substrings in free-text query.

    Args:
        query: The user's query text.

    Returns:
        Deduplicated, order-preserved ``articulo_key`` candidates whose
        norma-id portion is a well-formed BOE id.
    """
    keys: list[str] = []
    seen: set[str] = set()
    for m in _ARTICULO_KEY_RE.finditer(query):
        candidate = m.group(0)
        norma_part = candidate.split(":", 1)[0]
        if candidate in seen or not is_valid_boe_id(norma_part):
            continue
        seen.add(candidate)
        keys.append(candidate)
    return keys


async def graph_retrieve(store: Any, ctx: Any, query: str, as_of: date) -> list[dict[str, Any]]:
    """Resolve retrieval candidates: explicit ids first, then BM25 search.

    Args:
        store: The tenant's graph store.
        ctx: Tenant context.
        query: The user's query text.
        as_of: The date to resolve in-force wordings for.

    Returns:
        A list of hit dicts (``articulo_key``, ``norma_ref``, ``numero``,
        ``version``, ``basis``, ``score``) — explicit-id hits first, then
        BM25 hits in the AQL's score order, both deduplicated by
        ``articulo_key``.
    """
    hits: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for key in _extract_explicit_articulo_keys(query):
        version = await article_in_force(store, ctx, key, as_of)
        if version is None or version.text is None:
            continue
        norma_ref, _, numero = key.partition(":")
        hits.append(
            {
                "articulo_key": key,
                "norma_ref": norma_ref,
                "numero": numero,
                "version": version,
                "basis": "traversal",
                "score": None,
            }
        )
        seen_keys.add(key)

    for hit in await search_articles(store, ctx, query, as_of, limit=_DOSSIER_LIMIT):
        if hit.articulo_key in seen_keys or hit.version.text is None:
            continue
        hits.append(
            {
                "articulo_key": hit.articulo_key,
                "norma_ref": hit.norma_ref,
                "numero": hit.numero,
                "version": hit.version,
                "basis": "retrieval",
                "score": hit.score,
            }
        )
        seen_keys.add(hit.articulo_key)

    return hits


# ---------------------------------------------------------------------------
# Stage 3: dossier_build
# ---------------------------------------------------------------------------


def _format_payload_text(text: str) -> str:
    """Format one payload's text for the prompt enumeration (>4000 chars truncated).

    Args:
        text: The full, stored normalized payload text.

    Returns:
        The full text, or a flagged head+tail truncation for long
        payloads — the verifier always checks against the FULL payload,
        never this truncated view.
    """
    if len(text) <= _TRUNCATE_AT:
        return text
    return (
        text[:_HEAD_CHARS]
        + "\n[...]\n"
        + text[-_TAIL_CHARS:]
        + "\n(texto truncado en la muestra; la verificación usa el texto íntegro)"
    )


def dossier_build(
    hits: list[dict[str, Any]], as_of: date, *, limit: int = _DOSSIER_LIMIT
) -> tuple[dict[str, PayloadEntry], str, dict[str, float | None]]:
    """Assemble the retrieval set and its prompt enumeration.

    Args:
        hits: ``graph_retrieve`` output — explicit-id hits first, then
            BM25 hits.
        as_of: The date resolved for this turn.
        limit: Maximum number of entries to include.

    Returns:
        A tuple of: the ``retrieval_set`` (``payload_key -> PayloadEntry``,
        precedence-ordered), the prompt-formatted enumeration string, and
        a ``payload_key -> score`` map (``None`` for explicit/traversal
        entries) used to order the final dossier.
    """
    retrieval_set: dict[str, PayloadEntry] = {}
    scores: dict[str, float | None] = {}
    lines: list[str] = []

    for hit in hits[:limit]:
        version = hit["version"]
        payload_key = f"{hit['articulo_key']}:{version.n}"
        title = f"{hit['norma_ref']} art. {hit['numero']}"
        entry = PayloadEntry(
            payload_key=payload_key,
            payload=version.text,
            content_hash=version.content_hash,
            title=title,
            url=f"https://www.boe.es/buscar/act.php?id={hit['norma_ref']}",
            as_of=as_of,
            version_n=version.n,
            articulo_key=hit["articulo_key"],
            basis=hit["basis"],
        )
        retrieval_set[payload_key] = entry
        scores[payload_key] = hit["score"]

        window = f"{version.valid_from.isoformat()} -> {version.valid_to.isoformat() if version.valid_to else 'actualidad'}"
        lines.append(
            f"### payload_key: {payload_key}\n{title} — vigente {window}\n"
            f"{_format_payload_text(version.text)}"
        )

    return retrieval_set, "\n\n".join(lines), scores


# ---------------------------------------------------------------------------
# Stage 5: span_verify (post-processing: final dossier order)
# ---------------------------------------------------------------------------


def _sort_dossier(dossier: list[SpanRef], scores: dict[str, float | None]) -> list[SpanRef]:
    """Order the final dossier: explicit-id spans first, then BM25 desc.

    Args:
        dossier: The verified, deduplicated dossier.
        scores: ``payload_key -> score`` map from ``dossier_build``
            (``None`` for explicit-id/traversal entries).

    Returns:
        The dossier re-ordered: ``basis == "traversal"`` first, then
        ``basis == "retrieval"`` by score descending; stable tiebreak by
        payload key.
    """

    def _key(ref: SpanRef) -> tuple[int, float, str]:
        payload_key = f"{ref.id}:{ref.version_n}"
        if ref.basis == "traversal":
            return (0, 0.0, payload_key)
        return (1, -(scores.get(payload_key) or 0.0), payload_key)

    return sorted(dossier, key=_key)


# ---------------------------------------------------------------------------
# Stage 6: ground
# ---------------------------------------------------------------------------


def _build_evidence_index(retrieval_set: dict[str, PayloadEntry]) -> EvidenceIndex:
    """Build an ``EvidenceIndex`` from the dossier payloads.

    Args:
        retrieval_set: The turn's retrieval set.

    Returns:
        The populated evidence index (one synthetic ``ToolCall`` per
        dossier payload).
    """
    tool_calls = [
        ToolCall(id=key, name="dossier_payload", arguments={}, result={"text": entry.payload})
        for key, entry in retrieval_set.items()
    ]
    return EvidenceIndex.from_tool_calls(tool_calls, GroundednessPolicy())


def _join_reading_guide(notes: list[ReadingNote]) -> tuple[str, list[tuple[int, int]]]:
    """Join reading-guide sentences and track each one's offset span.

    Args:
        notes: The surviving reading-guide notes.

    Returns:
        The joined text (newline-separated) and each note's
        ``(start, end)`` offset within it, in the same order.
    """
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    for note in notes:
        start = pos
        parts.append(note.text)
        end = start + len(note.text)
        offsets.append((start, end))
        pos = end + 1  # +1 for the "\n" joiner
    return "\n".join(parts), offsets


def _note_index_for_offset(offsets: list[tuple[int, int]], position: int) -> int | None:
    """Find which note's span an atom offset falls within.

    Args:
        offsets: Per-note ``(start, end)`` spans from ``_join_reading_guide``.
        position: The atom's start offset in the joined text.

    Returns:
        The note's index, or ``None`` if the offset falls outside every span.
    """
    for i, (start, end) in enumerate(offsets):
        if start <= position < end:
            return i
    return None


async def ground(
    answer: LegalAnswer,
    retrieval_set: dict[str, PayloadEntry],
    *,
    execution_id: str,
    user_id: str | None,
    log: SuppressionLog,
) -> LegalAnswer:
    """Suppress any reading-guide sentence whose atoms contradict the evidence.

    Complementary check to ``span_verify`` — a CONTRADICTED numeric/
    identifier atom in a (span-anchored) sentence means the LLM's
    narration around a valid citation misstated a fact; the citation
    (dossier span) remains valid, only the sentence is suppressed.

    Args:
        answer: The span-verified ``LegalAnswer`` (post ``span_verify``).
        retrieval_set: The turn's retrieval set (evidence source).
        execution_id: The flow execution id, threaded into suppression
            records.
        user_id: User attributed to the execution, when known.
        log: The append-only suppression log.

    Returns:
        ``answer`` with any atom-contradicted sentences removed from
        ``reading_guide`` and ``suppressed_count`` incremented accordingly.
    """
    if not answer.reading_guide:
        return answer

    evidence = _build_evidence_index(retrieval_set)
    guide_text, offsets = _join_reading_guide(answer.reading_guide)
    report = GroundednessScorer().score(guide_text, evidence)
    if not report.contradicted:
        return answer

    contradicted_indices: set[int] = set()
    for verdict in report.contradicted:
        idx = _note_index_for_offset(offsets, verdict.atom.start)
        if idx is not None:
            contradicted_indices.add(idx)
    if not contradicted_indices:
        return answer

    surviving_notes: list[ReadingNote] = []
    suppressed_count = answer.suppressed_count
    for i, note in enumerate(answer.reading_guide):
        if i not in contradicted_indices:
            surviving_notes.append(note)
            continue
        suppressed_count += 1
        await log.append(
            SuppressionRecord(
                execution_id=execution_id,
                suppressed_text=note.text,
                claimed_anchors=list(note.spans),
                reason="atom_contradicted",
                user_id=user_id,
                created_at=datetime.now(UTC),
            )
        )

    return answer.model_copy(
        update={"reading_guide": surviving_notes, "suppressed_count": suppressed_count}
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def answer(
    query: str,
    *,
    agent: LibrarianLike,
    store: Any,
    ctx: Any,
    log: SuppressionLog,
    user_id: str | None = None,
    materias: list[str] | None = None,
) -> LegalAnswer:
    """Run the retrieval DAG end-to-end for one query (§2 Overview flow).

    Direct sequential invocation of the six stages — see this module's
    docstring for why ``AgentCrew.run_flow``'s ``ToolNode`` template
    plumbing was not used as the executed path.

    Args:
        query: The user's query text.
        agent: The librarian agent (``LegalLibrarianAgent`` or a test
            double satisfying ``LibrarianLike``).
        store: The tenant's graph store.
        ctx: Tenant context.
        log: The append-only suppression log.
        user_id: User attributed to the execution, when known.
        materias: Materias searched (single-materia corpus in v1 —
            defaults to empty; multi-materia routing is out of scope).

    Returns:
        The final, span-verified, groundedness-checked ``LegalAnswer``.
    """
    execution_id = uuid4().hex

    stage1 = await as_of_extract(query, llm_ask=agent.ask)
    as_of = stage1["as_of"]

    hits = await graph_retrieve(store, ctx, query, as_of)
    retrieval_set, enumerated_dossier, scores = dossier_build(hits, as_of)

    draft = await agent.draft(enumerated_dossier, query, as_of)

    verified, suppressions = SpanVerifier().verify(
        draft,
        retrieval_set,
        as_of=as_of,
        materias=materias or [],
        execution_id=execution_id,
        user_id=user_id,
    )
    for record in suppressions:
        await log.append(record)

    verified = verified.model_copy(update={"dossier": _sort_dossier(verified.dossier, scores)})

    return await ground(verified, retrieval_set, execution_id=execution_id, user_id=user_id, log=log)


# ---------------------------------------------------------------------------
# AgentCrew builder (structural artifact — see module docstring)
# ---------------------------------------------------------------------------


class _CallableTool(AbstractTool):
    """Thin ``AbstractTool`` adapter wrapping a plain async callable.

    Used only by ``build_legal_librarian_crew`` to register each
    deterministic stage as a ``ToolNode`` — NOT part of ``answer()``'s
    executed path (see module docstring).
    """

    def __init__(self, fn, *, name: str, description: str) -> None:
        self._fn = fn
        super().__init__(name=name, description=description)

    async def _execute(self, **kwargs: Any) -> Any:
        return await self._fn(**kwargs)


def build_legal_librarian_crew(
    agent: LibrarianLike, store: Any, ctx: Any, log: SuppressionLog
) -> AgentCrew:
    """Build a structurally faithful ``AgentCrew`` for the retrieval DAG.

    Registers all six stages as crew members (five deterministic
    ``ToolNode``s + the librarian LLM agent node) with their dependency
    edges wired, for inspection/discoverability. ``answer()`` — NOT this
    crew's ``run_flow`` — is the tested/executed path; see the module
    docstring for why.

    Args:
        agent: The librarian agent.
        store: The tenant's graph store.
        ctx: Tenant context.
        log: The append-only suppression log.

    Returns:
        The assembled ``AgentCrew``.
    """
    crew = AgentCrew(
        name="legal_librarian_crew",
        auto_configure=False,
        persist_results=False,
        enable_execution_wiki=False,
    )

    crew.add_tool_node(
        _CallableTool(
            lambda **kw: as_of_extract(kw["query"], llm_ask=agent.ask),
            name="as_of_extract",
            description="Resolve the as_of date for a query (R9).",
        ),
        node_id="as_of_extract",
    )
    crew.add_tool_node(
        _CallableTool(
            lambda **kw: graph_retrieve(store, ctx, kw["query"], kw["as_of"]),
            name="graph_retrieve",
            description="Explicit-id resolution then search_articles BM25 retrieval.",
        ),
        node_id="graph_retrieve",
    )
    crew.add_tool_node(
        _CallableTool(
            lambda **kw: dossier_build(kw["hits"], kw["as_of"]),
            name="dossier_build",
            description="Assemble the retrieval set and its prompt enumeration.",
        ),
        node_id="dossier_build",
    )
    crew.add_agent(agent, agent_id="librarian")
    # add_agent() only registers into crew.agents; flow-mode DAG participation
    # additionally requires a workflow_graph entry (mirrors what __init__
    # does for agents passed via the `agents=[...]` constructor list).
    crew.workflow_graph["librarian"] = CrewAgentNode(agent=agent, node_id="librarian")
    crew.add_tool_node(
        _CallableTool(
            lambda **kw: SpanVerifier().verify(
                kw["draft"],
                kw["retrieval_set"],
                as_of=kw["as_of"],
                materias=kw.get("materias") or [],
                execution_id=kw["execution_id"],
                user_id=kw.get("user_id"),
            ),
            name="span_verify",
            description="Deterministic existence gate + suppression records (R4).",
        ),
        node_id="span_verify",
    )
    crew.add_tool_node(
        _CallableTool(
            lambda **kw: ground(
                kw["answer"],
                kw["retrieval_set"],
                execution_id=kw["execution_id"],
                user_id=kw.get("user_id"),
                log=log,
            ),
            name="ground",
            description="GroundednessScorer atom check over the surviving guide.",
        ),
        node_id="ground",
    )

    # Wiring: linear dependency chain matching the §2 flow order.
    crew.workflow_graph["graph_retrieve"].dependencies.add("as_of_extract")
    crew.workflow_graph["dossier_build"].dependencies.update({"as_of_extract", "graph_retrieve"})
    crew.workflow_graph["librarian"].dependencies.add("dossier_build")
    crew.workflow_graph["span_verify"].dependencies.update({"librarian", "dossier_build"})
    crew.workflow_graph["ground"].dependencies.add("span_verify")

    return crew
