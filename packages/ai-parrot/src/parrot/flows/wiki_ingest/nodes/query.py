"""§28 Query workflow (FEAT-481, spec Module 13).

**Retrieve via GraphIndex/PageIndex (primary) → verify against Obsidian
pages (content authority).** The derived wiki plane (``graph.py``) never
supplies the answer directly — it only ranks candidate pages; this node
re-reads each candidate from the **Obsidian vault** (via this
subsystem's own :class:`ObsidianToolkit`, spec Module 4) before handing
anything to the LLM, and the final answer explicitly separates supported
facts, inferences, unknowns, and unresolved contradictions (§28 step 7).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
from parrot.tools.obsidian import ObsidianToolkit

from ..graph import WIKI_KB_GRAPH_WIKI_NAME
from ..models import SynthesisFrontmatter
from ..naming import now_iso, title_case_name

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are answering a question from a governed knowledge base (contract "
    "§28). GraphIndex/PageIndex retrieval only ranks candidate pages — it is "
    "NEVER quoted as authority. Answer only from the provided Obsidian page "
    "contents, with inline [[wikilinks]] to supporting pages. You MUST "
    "separate: supported facts (directly stated in a page), inferences "
    "(reasonable but not explicit), unknowns (not covered by any page), and "
    "unresolved contradictions (linked contradiction pages). Do not use "
    "external knowledge (rule #15) — only the supplied page contents."
)


class QueryCandidate(BaseModel):
    """One retrieved-then-verified candidate page.

    Attributes:
        node_id: The wiki plane's stable node/page id.
        title: The candidate's title (as ranked by retrieval).
        score: Normalized relevance score, ``[0, 1]``.
        vault_path: The resolved Obsidian vault path, when found.
        content: The vault page's content, when read successfully —
            ``None`` means retrieval ranked it but verification could not
            locate/read the underlying Obsidian page (dropped from the
            answer prompt, never guessed).
    """

    node_id: str
    title: str
    score: float
    vault_path: str | None = None
    content: str | None = None


class QueryAnswer(BaseModel):
    """The §28 step 7 answer, with fact-type distinctions.

    Attributes:
        supported_facts: Claims directly stated in a verified page, each
            citing its source (rule #10).
        inferences: Reasonable but not explicitly stated conclusions.
        unknowns: Aspects of the question no page addresses.
        unresolved_contradictions: Linked contradiction pages relevant
            to the question.
    """

    supported_facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    unresolved_contradictions: list[str] = Field(default_factory=list)


class QueryResult(BaseModel):
    """Result of one §28 query.

    Attributes:
        question: The original question.
        answer: The :class:`QueryAnswer`.
        candidates: Every retrieved-then-verified candidate (for
            provenance/debugging — not all necessarily cited).
    """

    question: str
    answer: QueryAnswer
    candidates: list[QueryCandidate] = Field(default_factory=list)


async def _resolve_and_read(vault_toolkit: ObsidianToolkit, title: str) -> tuple[str | None, str | None]:
    """Resolve a retrieved candidate's title back to a live Obsidian page.

    Both planes are built from the same vault content, so a candidate's
    title should resolve via the vault's own search — this is the §28
    step 3 "read the compiled Obsidian pages" verification, never a
    GraphIndex/PageIndex body quoted directly.

    Args:
        vault_toolkit: This subsystem's own :class:`ObsidianToolkit`.
        title: The candidate's title, as ranked by retrieval.

    Returns:
        ``(vault_path, content)`` — both ``None`` when nothing in the
        vault matches (the candidate is then dropped from the answer
        prompt, never guessed).
    """
    try:
        search_result = await vault_toolkit.search_notes(title, limit=1)
        hits = search_result.get("hits", [])
        if not hits:
            return None, None
        path = hits[0]["path"]
        note = await vault_toolkit.read_note(path)
        return path, note.get("content")
    except Exception:
        logger.warning("Could not resolve/read candidate %r from the vault", title, exc_info=True)
        return None, None


async def run_query(
    strong_client: AbstractClient,
    wiki_toolkit: LLMWikiToolkit,
    vault_toolkit: ObsidianToolkit,
    question: str,
    *,
    wiki_name: str = WIKI_KB_GRAPH_WIKI_NAME,
    top_k: int = 5,
) -> QueryResult:
    """Run the §28 query workflow: retrieve → verify → answer.

    Args:
        strong_client: The strong-tier :class:`AbstractClient` (spec G7).
        wiki_toolkit: This subsystem's :class:`LLMWikiToolkit`
            (``graph.py``'s derived plane).
        vault_toolkit: This subsystem's own :class:`ObsidianToolkit`
            (spec Module 4) — the content authority.
        question: The natural-language question.
        wiki_name: The wiki plane name.
        top_k: Max candidates read for verification.

    Returns:
        The :class:`QueryResult`.
    """
    raw_results = await wiki_toolkit.search(wiki_name, question, mode="combined")

    candidates: list[QueryCandidate] = []
    for hit in raw_results[:top_k]:
        vault_path, content = await _resolve_and_read(vault_toolkit, hit["title"])
        candidates.append(
            QueryCandidate(
                node_id=hit["node_id"], title=hit["title"], score=hit["score"], vault_path=vault_path, content=content
            )
        )

    verified = [c for c in candidates if c.content is not None]
    if not verified:
        return QueryResult(
            question=question,
            answer=QueryAnswer(unknowns=["No verified Obsidian page content was found for this question."]),
            candidates=candidates,
        )

    prompt = "\n".join(
        [
            f"Question: {question}",
            "",
            "Verified Obsidian page contents (content authority):",
            *[f"--- {c.vault_path} ---\n{c.content}" for c in verified],
        ]
    )
    result = await strong_client.invoke(prompt, output_type=QueryAnswer, system_prompt=_SYSTEM_PROMPT, temperature=0.0)

    return QueryResult(question=question, answer=result.output, candidates=candidates)


def build_synthesis_page(
    query_result: QueryResult, *, related_pages: list[str] | None = None
) -> tuple[SynthesisFrontmatter, str]:
    """§28 step 10 — render a synthesis page, ONLY when explicitly requested.

    This function is never called automatically by :func:`run_query` —
    an ordinary query never modifies the Wiki (§28 step 9); the caller
    (agent façade) invokes this only on an explicit save/file request.

    Args:
        query_result: The :class:`QueryResult` to save.
        related_pages: Entity/concept/project links for
            ``## Related Knowledge``.

    Returns:
        ``(frontmatter, content)``.
    """
    title = title_case_name(query_result.question[:60])
    now = now_iso()

    evidence = "\n".join(f"- {fact}" for fact in query_result.answer.supported_facts) or "- Not established"
    limitations = (
        "\n".join(
            f"- {item}" for item in [*query_result.answer.unknowns, *query_result.answer.unresolved_contradictions]
        )
        or "- None identified"
    )
    related = "\n".join(f"- [[{p}]]" for p in (related_pages or [])) or "- None identified"
    answer_body = "\n".join(query_result.answer.supported_facts + query_result.answer.inferences) or "Not established"

    content = f"""# {title}

## Question
{query_result.question}

## Answer
{answer_body}

## Evidence
{evidence}

## Contradictions and Limitations
{limitations}

## Related Knowledge
{related}
"""
    frontmatter = SynthesisFrontmatter(
        id=f"synthesis:{title.lower().replace(' ', '-')}",
        title=title,
        question=query_result.question,
        source_pages=[c.vault_path for c in query_result.candidates if c.vault_path],
        created=now,
        updated=now,
    )
    return frontmatter, content
