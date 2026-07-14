"""Token-efficient context packing for wiki retrieval results.

The wiki optimises for what the LLM actually pays for: tokens.  Instead
of dumping full page bodies (or raw model dumps) into context, search
results are packed as **compact stubs** — one line per page with its
identity, title, lead sentence, score, and token cost — under an
explicit token budget.  The model then *progressively discloses* only
what it needs via ``wiki_read`` (full body, optionally truncated) and
``wiki_expand`` (edge neighbours).

All token accounting uses the per-page ``token_count`` stored in the
WikiStore at ingest time plus :func:`estimate_tokens` for the stub
lines themselves — nothing is re-tokenised at query time.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.store import estimate_tokens

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s")

DEFAULT_BUDGET_TOKENS = 1200
_MAX_LEAD_CHARS = 240


class PackedContext(BaseModel):
    """A budgeted, LLM-ready packing of wiki search results.

    Attributes:
        text: Compact context block — one stub line per result.
        stubs: Structured stubs (id, title, lead, score, token cost of
            the FULL page — what ``wiki_read`` would spend).
        tokens_used: Estimated tokens of ``text``.
        results_packed: Number of results that fit the budget.
        total_available: Number of results before budgeting.
        truncated: ``True`` when the budget cut results off.
    """

    text: str = ""
    stubs: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int = 0
    results_packed: int = 0
    total_available: int = 0
    truncated: bool = False


def first_sentence(text: str, max_chars: int = _MAX_LEAD_CHARS) -> str:
    """Return the lead sentence of ``text``, hard-capped at ``max_chars``.

    Args:
        text: Source text (summary or body).
        max_chars: Maximum characters returned.

    Returns:
        The first sentence (or the truncated text when no sentence
        boundary is found), single-line.
    """
    lead = " ".join(text.strip().split())
    if not lead:
        return ""
    parts = _SENTENCE_END_RE.split(lead, maxsplit=1)
    lead = parts[0]
    if len(lead) > max_chars:
        lead = lead[: max_chars - 1].rstrip() + "…"
    return lead


def stub_line(result: dict[str, Any]) -> str:
    """Render one search result as a compact single-line stub.

    Format::

        - [<id>] <title> — <lead sentence> (score=0.87, ~120tok)

    The token figure is the cost of reading the FULL page via
    ``wiki_read`` — it lets the model budget its next move.

    Args:
        result: Result dict with at least an id field; ``score``,
            ``snippet``/``summary``, and ``token_count`` are optional.

    Returns:
        The rendered stub line.
    """
    rid = str(
        result.get("concept_id") or result.get("node_id") or result.get("page_id") or "?"
    )
    title = str(result.get("title") or "").strip() or rid
    lead = first_sentence(str(result.get("snippet") or result.get("summary") or ""))
    meta: list[str] = []
    score = result.get("score")
    if score is not None:
        meta.append(f"score={float(score):.2f}")
    tokens = result.get("token_count")
    if tokens:
        meta.append(f"~{int(tokens)}tok")
    suffix = f" ({', '.join(meta)})" if meta else ""
    body = f"- [{rid}] {title}"
    if lead:
        body += f" — {lead}"
    return body + suffix


def pack_results(
    results: Iterable[Any],
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> PackedContext:
    """Pack search results into a token-budgeted context block.

    Results are consumed in ranked order; packing stops as soon as the
    next stub would exceed ``budget_tokens``.  Duplicate ids are
    skipped.

    Args:
        results: ``WikiSearchResult`` models or plain result dicts, in
            ranked order.
        budget_tokens: Hard token ceiling for the packed text.

    Returns:
        A :class:`PackedContext`.
    """
    items: list[dict[str, Any]] = []
    for r in results:
        items.append(r.model_dump() if hasattr(r, "model_dump") else dict(r))

    lines: list[str] = []
    stubs: list[dict[str, Any]] = []
    seen: set[str] = set()
    used = 0
    truncated = False

    for item in items:
        rid = str(
            item.get("concept_id") or item.get("node_id") or item.get("page_id") or ""
        )
        if not rid or rid in seen:
            continue
        line = stub_line(item)
        cost = estimate_tokens(line)
        if used + cost > budget_tokens and lines:
            truncated = True
            break
        if cost > budget_tokens and not lines:
            # A single stub over budget still gets included (never
            # return an empty pack for a non-empty result set).
            truncated = True
        seen.add(rid)
        lines.append(line)
        used += cost
        stubs.append(
            {
                "id": rid,
                "title": item.get("title") or "",
                "lead": first_sentence(
                    str(item.get("snippet") or item.get("summary") or "")
                ),
                "score": item.get("score"),
                "token_count": item.get("token_count"),
                "category": item.get("category"),
            }
        )

    return PackedContext(
        text="\n".join(lines),
        stubs=stubs,
        tokens_used=used,
        results_packed=len(lines),
        total_available=len(items),
        truncated=truncated or len(lines) < len(items),
    )


def truncate_to_tokens(text: str, max_tokens: Optional[int]) -> tuple[str, bool]:
    """Deterministically truncate ``text`` to approximately ``max_tokens``.

    Uses the same 4-chars-per-token heuristic as the fallback estimator
    so truncation never requires a tokenizer; cuts on a whitespace
    boundary where possible.

    Args:
        text: Text to truncate.
        max_tokens: Token ceiling; ``None`` disables truncation.

    Returns:
        ``(text, truncated_flag)``.
    """
    if max_tokens is None or max_tokens <= 0:
        return text, False
    if estimate_tokens(text) <= max_tokens:
        return text, False
    max_chars = max_tokens * 4
    cut = text[:max_chars]
    last_space = cut.rfind(" ")
    if last_space > max_chars // 2:
        cut = cut[:last_space]
    return cut.rstrip() + "\n\n[…truncated]", True
