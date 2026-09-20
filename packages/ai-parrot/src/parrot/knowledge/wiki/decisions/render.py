"""Budgeted dossier packing and rendering (FEAT-578 Module 4).

The packing invariant (spec §2): a hit is emitted only WITH its
origin/status/freshness labels and at least one citation. When the budget
cannot hold that minimum, the hit is omitted and ``truncated`` is set — the
labels are never dropped to make room, because an unlabeled candidate reads
like a documented decision (AC3, AC9).
"""

from __future__ import annotations

from parrot.knowledge.wiki.decisions.models import DecisionDiagnostic, DecisionDossier, DecisionHit
from parrot.knowledge.wiki.store import estimate_tokens

#: Spec §2 "Retrieval and freshness" — ADR dossier defaults and bounds.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 50
DEFAULT_BUDGET_TOKENS = 3000
MIN_BUDGET_TOKENS = 256


def clamp_limit(limit: int) -> int:
    """Clamp ``limit`` into ``1..50`` (spec §2)."""
    return max(MIN_LIMIT, min(MAX_LIMIT, limit))


def clamp_budget(budget_tokens: int) -> int:
    """Raise ``budget_tokens`` to the 256-token floor (spec §2)."""
    return max(MIN_BUDGET_TOKENS, budget_tokens)


def labels_of(hit: DecisionHit) -> str:
    """The mandatory label prefix, e.g. ``[INFERRED / UNREVIEWED / stale]``."""
    origin = "DOCUMENTED" if hit.origin == "documented" else "INFERRED"
    status = hit.source_status.upper() if hit.origin == "documented" else hit.review_status.upper()
    return f"[{origin} / {status} / {hit.freshness}]"


def _citation_line(hit: DecisionHit) -> str:
    """Render the first citation as ``rel_path:start-end``; '' when there is none."""
    if not hit.citations:
        return ""
    first = hit.citations[0]
    return f"{first.rel_path}:{first.start_line}-{first.end_line}"


def minimum_cost(hit: DecisionHit) -> int:
    """Token cost of the shortest LEGAL rendering of ``hit``.

    That floor is labels + decision id + one citation reference, with the
    excerpt fully elided. A hit that does not fit this is omitted, never
    emitted without its labels.
    """
    return estimate_tokens(f"{labels_of(hit)} {hit.decision_id} {_citation_line(hit)}")


def _full_cost(hit: DecisionHit) -> int:
    """Token cost of ``hit`` rendered with its decision text and excerpt intact."""
    return estimate_tokens(_render_hit_line(hit))


def _render_hit_line(hit: DecisionHit) -> str:
    """One rendered line for ``hit``: labels, id, title, decision, citation, excerpt."""
    citation = _citation_line(hit)
    excerpt = hit.citations[0].excerpt if hit.citations else ""
    parts = [labels_of(hit), hit.decision_id]
    if hit.title:
        parts.append(hit.title)
    if hit.decision:
        parts.append(hit.decision)
    if citation:
        parts.append(citation)
    if excerpt:
        parts.append(excerpt)
    return " ".join(parts)


def _shorten_hit(hit: DecisionHit, available_tokens: int) -> DecisionHit:
    """Return a copy whose decision text and excerpts are shortened to fit.

    The citation's ``rel_path``/line range is always retained; only the
    ``decision`` text and citation ``excerpt`` fields are cut, longest
    first (spec §2 "shorten the excerpt while retaining the citation"),
    never ``origin``/``source_status``/``review_status``/``freshness``.
    """
    shortened = hit.model_copy(deep=True)
    while _full_cost(shortened) > available_tokens:
        # Candidates are (setter, current_text) for every trimmable field:
        # the decision text itself, plus each citation's excerpt.
        trimmable: list[tuple[str, int]] = [("decision", len(shortened.decision))]
        for idx, ref in enumerate(shortened.citations):
            trimmable.append((f"excerpt:{idx}", len(ref.excerpt)))
        key, longest_len = max(trimmable, key=lambda kv: kv[1])
        if longest_len == 0:
            # Nothing left to trim; the floor (minimum_cost) is the
            # caller's responsibility to have already checked before
            # calling us.
            break
        new_len = max(0, longest_len - max(1, longest_len // 2))
        if key == "decision":
            shortened.decision = shortened.decision[:new_len]
        else:
            idx = int(key.split(":", 1)[1])
            shortened.citations[idx].excerpt = shortened.citations[idx].excerpt[:new_len]
    return shortened


def pack_dossier(
    documented: list[DecisionHit],
    candidates: list[DecisionHit],
    *,
    limit: int = DEFAULT_LIMIT,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    status: str = "ok",
    alternatives: list[str] | None = None,
    diagnostics: list[DecisionDiagnostic] | None = None,
) -> DecisionDossier:
    """Assemble a dossier within ``limit`` hits and ``budget_tokens``.

    Documented hits are packed before candidates, so a tight budget drops
    candidates first. ``truncated`` is set whenever any hit was omitted or
    any excerpt shortened.

    Args:
        documented: Already-ranked documented hits.
        candidates: Already-ranked inferred hits. Kept in their own group —
            never merged into ``documented`` (AC3).
        limit: Total hits across both groups, clamped to ``1..50``.
        budget_tokens: Estimated output budget, floored at 256.
    """
    limit = clamp_limit(limit)
    budget_tokens = clamp_budget(budget_tokens)

    packed_documented: list[DecisionHit] = []
    packed_candidates: list[DecisionHit] = []
    used_tokens = 0
    used_slots = 0
    truncated = False

    for group_hits, packed_group in ((documented, packed_documented), (candidates, packed_candidates)):
        for hit in group_hits:
            if used_slots >= limit:
                truncated = True
                continue
            remaining = budget_tokens - used_tokens
            full_cost = _full_cost(hit)
            if full_cost <= remaining:
                packed_group.append(hit)
                used_tokens += full_cost
                used_slots += 1
                continue
            floor_cost = minimum_cost(hit)
            if floor_cost <= remaining:
                shortened = _shorten_hit(hit, remaining)
                packed_group.append(shortened)
                used_tokens += _full_cost(shortened)
                used_slots += 1
                truncated = True
                continue
            # Neither the full nor the minimum legal rendering fits — the
            # hit is omitted rather than emitted without its labels/citation.
            truncated = True

    result_status = status
    if truncated and status == "ok":
        result_status = "partial"

    return DecisionDossier(
        status=result_status,
        documented=packed_documented,
        candidates=packed_candidates,
        alternatives=alternatives or [],
        diagnostics=diagnostics or [],
        truncated=truncated,
    )


def render_dossier_text(dossier: DecisionDossier) -> str:
    """Human-readable rendering for CLI and tool text output.

    Emits two clearly separated sections. The candidate section is headed so
    that a reader cannot mistake it for documented history, even when the
    documented section is empty.
    """
    lines: list[str] = []

    lines.append("Documented decisions")
    if dossier.documented:
        for hit in dossier.documented:
            lines.append(_render_summary_line(hit))
    else:
        lines.append("(none)")

    lines.append("")
    lines.append("Candidates (INFERRED — not accepted history)")
    if dossier.candidates:
        for hit in dossier.candidates:
            lines.append(_render_summary_line(hit))
    else:
        lines.append("(none)")

    if dossier.diagnostics:
        lines.append("")
        lines.append("Diagnostics")
        for diag in dossier.diagnostics:
            suffix = f" ({diag.decision_id})" if diag.decision_id else ""
            lines.append(f"- {diag.code}: {diag.message}{suffix}")

    if dossier.truncated:
        lines.append("")
        lines.append(
            "Note: output was truncated to fit the token budget; some hits or excerpts were shortened or omitted."
        )

    return "\n".join(lines)


def _render_summary_line(hit: DecisionHit) -> str:
    """One line per hit: labels, id, title, and its first citation."""
    citation = _citation_line(hit)
    parts = [labels_of(hit), hit.decision_id]
    if hit.title:
        parts.append(hit.title)
    if citation:
        parts.append(f"({citation})")
    return "- " + " ".join(parts)
