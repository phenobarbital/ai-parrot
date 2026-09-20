"""ADR discovery and idempotent source refresh (FEAT-578 Module 3).

The only writer of ``adr:doc:`` records. Candidate (``adr:candidate:``)
records are read to resolve links but NEVER written here — a documented
refresh must not disturb independently reviewed candidates (spec §2, AC7).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from parrot.knowledge.graphindex.cli import discover_python_files
from parrot.knowledge.scan_excludes import SCAN_EXCLUDE_DIRS
from parrot.knowledge.wiki.decisions.codec import content_fingerprint
from parrot.knowledge.wiki.decisions.evidence import build_evidence, extract_python_citations
from parrot.knowledge.wiki.decisions.models import (
    ADR_REFERENCE_AMBIGUOUS,
    ADR_REFERENCE_MISSING,
    ADR_SOURCE_UNAVAILABLE,
    DecisionConfig,
    DecisionDiagnostic,
    DecisionError,
    DecisionLink,
    DecisionRecord,
    EvidenceRef,
    SyncResult,
)
from parrot.knowledge.wiki.decisions.parser import parse_adr
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.store import BaseWikiStore

logger = logging.getLogger(__name__)

#: The link resolution pass returns, per decision_id, the extra EvidenceRefs
#: to append to that record and the DecisionLinks whose evidence_indexes
#: already point into that same (record-relative, zero-based) addition list
#: — see _resolve_citations for why this differs from a bare list[DecisionLink].
_ResolvedLinks = dict[str, tuple[list[EvidenceRef], list[DecisionLink]]]


def discover_adr_sources(root: Path, config: DecisionConfig) -> list[str]:
    """Repository-relative POSIX paths of every eligible ADR document.

    Applies ``config.adr_globs`` AND the project's normal relevance /
    exclusion rules — a matching glob inside an excluded directory is still
    excluded (spec §2).
    """
    found: set[Path] = set()
    for pattern in config.adr_globs:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(root).parts
            if any(part in SCAN_EXCLUDE_DIRS for part in rel_parts):
                continue
            found.add(path)
    return sorted(p.relative_to(root).as_posix() for p in found)


def _alias_index(inventory: list[DecisionRecord]) -> tuple[dict[str, str], set[str]]:
    """Map ``ADR-42`` -> decision_id, plus the set of ambiguous aliases.

    Built per call: spec §2 forbids a persistent cache without an
    invalidation contract.
    """
    mapping: dict[str, str] = {}
    ambiguous: set[str] = set()
    for record in inventory:
        alias = record.external_id
        if not alias:
            continue
        existing = mapping.get(alias)
        if existing is not None and existing != record.decision_id:
            ambiguous.add(alias)
        else:
            mapping[alias] = record.decision_id
    for alias in ambiguous:
        mapping.pop(alias, None)
    return mapping, ambiguous


async def _resolve_citations(
    root: Path,
    code_paths: list[str],
    inventory: list[DecisionRecord],
) -> tuple[_ResolvedLinks, list[DecisionDiagnostic]]:
    """Resolve Python ADR citations into per-decision ``explains`` links.

    Args:
        code_paths: EVERY indexed Python target, not only changed files —
            changing an ADR must repair links in unchanged citing code
            (spec §2 Module 3).

    Returns:
        ``(resolved, diagnostics)``. ``resolved[decision_id]`` is
        ``(extra_evidence, links)`` where each link's ``evidence_indexes``
        already addresses ``extra_evidence`` (zero-based) — the caller must
        shift them by ``len(record.evidence)`` before appending, since a
        ``DecisionLink.evidence_indexes`` entry must address the record's
        OWN evidence list (the ``DecisionRecord`` model invariant), not a
        list scoped to this function alone. An alias with no record is
        ``ADR_REFERENCE_MISSING``; a duplicated alias is
        ``ADR_REFERENCE_AMBIGUOUS``. Both stay unresolved.
    """
    alias_map, ambiguous_aliases = _alias_index(inventory)
    # decision_id -> target_id -> evidence refs citing that target
    grouped: dict[str, dict[str, list[EvidenceRef]]] = {}
    diagnostics: list[DecisionDiagnostic] = []

    for rel_path in code_paths:
        try:
            text = await asyncio.to_thread((root / rel_path).read_text, encoding="utf-8")
        except OSError as exc:
            diagnostics.append(DecisionDiagnostic(code=ADR_SOURCE_UNAVAILABLE, message=str(exc), path=rel_path))
            continue
        citations, cite_diagnostics = extract_python_citations(rel_path, text)
        diagnostics.extend(cite_diagnostics)
        for citation in citations:
            if citation.alias in ambiguous_aliases:
                diagnostics.append(
                    DecisionDiagnostic(
                        code=ADR_REFERENCE_AMBIGUOUS,
                        message=f"{citation.alias!r} is claimed by more than one ADR source",
                        path=rel_path,
                    )
                )
                continue
            decision_id = alias_map.get(citation.alias)
            if decision_id is None:
                diagnostics.append(
                    DecisionDiagnostic(
                        code=ADR_REFERENCE_MISSING,
                        message=f"no ADR source resolves alias {citation.alias!r}",
                        path=rel_path,
                    )
                )
                continue
            ref = build_evidence(
                citation.rel_path, text, citation.page_id, citation.start_line, citation.end_line, citation.kind
            )
            grouped.setdefault(decision_id, {}).setdefault(citation.page_id, []).append(ref)

    resolved: _ResolvedLinks = {}
    for decision_id, by_target in grouped.items():
        extra_evidence: list[EvidenceRef] = []
        links: list[DecisionLink] = []
        for target_id, refs in by_target.items():
            start = len(extra_evidence)
            extra_evidence.extend(refs)
            links.append(
                DecisionLink(
                    target_id=target_id,
                    relation="explains",
                    provenance="extracted",
                    evidence_indexes=list(range(start, start + len(refs))),
                )
            )
        resolved[decision_id] = (extra_evidence, links)
    return resolved, diagnostics


def _strip_extracted_explains(record: DecisionRecord) -> tuple[list[EvidenceRef], list[DecisionLink]]:
    """``record``'s evidence/links with stale extracted ``explains`` citation
    links removed, ready for a fresh ``_resolve_citations`` result to be
    appended in their place.

    Only citation-derived links are eligible for removal here: an
    ``explains`` link with ``provenance="extracted"`` is exactly what
    ``_resolve_citations`` produces (see above) and nothing else does. An
    ADR's own ``supersedes`` header is also parsed with
    ``provenance="extracted"`` (``parser.py``) but a different ``relation``,
    so it — and every ``asserted``/``inferred`` link — survives untouched.
    Evidence not referenced by ANY link (e.g. the ADR body's own citation)
    also survives; only evidence referenced EXCLUSIVELY by a removed
    ``explains`` link is dropped.
    """
    keep_links = [link for link in record.links if not (link.relation == "explains" and link.provenance == "extracted")]
    all_referenced = {idx for link in record.links for idx in link.evidence_indexes}
    kept_referenced = {idx for link in keep_links for idx in link.evidence_indexes}
    keep_indexes = sorted(
        idx for idx in range(len(record.evidence)) if idx not in all_referenced or idx in kept_referenced
    )
    remap = {old: new for new, old in enumerate(keep_indexes)}
    new_evidence = [record.evidence[i] for i in keep_indexes]
    new_links = [
        DecisionLink(
            target_id=link.target_id,
            relation=link.relation,
            provenance=link.provenance,
            evidence_indexes=[remap[idx] for idx in link.evidence_indexes],
        )
        for link in keep_links
    ]
    return new_evidence, new_links


async def _persist_if_changed(repo: DecisionRepository, record: DecisionRecord, result: SyncResult) -> None:
    """Save ``record`` when it differs from the stored version; update ``result`` counters."""
    existing = await repo.get(record.decision_id)
    expected_hash = existing[1] if existing is not None else None
    if existing is not None and content_fingerprint(existing[0]) == content_fingerprint(record):
        result.unchanged += 1
        return
    try:
        await repo.save(record, expected_hash)
    except DecisionError as exc:
        result.diagnostics.append(DecisionDiagnostic(code=exc.code, message=str(exc), decision_id=exc.decision_id))
        return
    if existing is None:
        result.created += 1
    else:
        result.updated += 1


async def refresh_decisions(
    store: BaseWikiStore,
    root: Path,
    config: DecisionConfig,
    paths: list[str] | None = None,
) -> SyncResult:
    """Refresh documented ADR records and their links, idempotently.

    Args:
        paths: Repository-relative paths to refresh, or ``None`` for the full
            configured inventory. An incremental run still re-resolves
            aliases against the FULL stored inventory.

    Returns:
        Counts plus diagnostics. Never raises for a per-record failure —
        writes are per-record atomic, so a retry converges (spec §2).
    """
    repo = DecisionRepository(store, max_records=config.max_records)
    result = SyncResult()
    if not config.enabled:
        return result

    inventory = await repo.inventory()
    result.diagnostics.extend(repo.last_diagnostics)

    sources = paths if paths is not None else await asyncio.to_thread(discover_adr_sources, root, config)

    parsed_by_source: dict[str, DecisionRecord] = {}
    for source in sources:
        try:
            text = await asyncio.to_thread((root / source).read_text, encoding="utf-8")
        except OSError as exc:
            result.diagnostics.append(DecisionDiagnostic(code=ADR_SOURCE_UNAVAILABLE, message=str(exc), path=source))
            continue
        record, parse_diagnostics = parse_adr(source, text)
        result.diagnostics.extend(parse_diagnostics)
        if record is None:
            continue
        parsed_by_source[source] = record

    # Resolve code citations against the full stored inventory PLUS every
    # freshly (re)parsed record this pass — a brand-new or renamed ADR must
    # be resolvable by code already citing its alias, in the same pass that
    # creates it.
    by_decision_id = {r.decision_id: r for r in inventory}
    for record in parsed_by_source.values():
        by_decision_id[record.decision_id] = record
    combined_inventory = list(by_decision_id.values())

    # Nothing in the inventory can be the target of a citation unless some
    # record carries an alias, so the whole code walk -- read, tokenize and
    # ast.parse EVERY Python file in the repository -- would resolve to the
    # empty set. Skipping it is what keeps `wikitoolkit build` from paying
    # ~30s per run for a decision plane that is simply empty, which is the
    # state of every project that has not written an ADR yet.
    alias_map, ambiguous_aliases = _alias_index(combined_inventory)
    resolved_links: _ResolvedLinks = {}
    if alias_map or ambiguous_aliases:
        python_files = await asyncio.to_thread(discover_python_files, root)
        code_paths = [p.relative_to(root).as_posix() for p in python_files]
        resolved_links, link_diagnostics = await _resolve_citations(root, code_paths, combined_inventory)
        result.diagnostics.extend(link_diagnostics)

    for record in parsed_by_source.values():
        extra_evidence, links = resolved_links.get(record.decision_id, ([], []))
        base_index = len(record.evidence)
        shifted_links = [
            DecisionLink(
                target_id=link.target_id,
                relation=link.relation,
                provenance=link.provenance,
                evidence_indexes=[idx + base_index for idx in link.evidence_indexes],
            )
            for link in links
        ]
        record = record.model_copy(
            update={"evidence": [*record.evidence, *extra_evidence], "links": [*record.links, *shifted_links]}
        )
        await _persist_if_changed(repo, record, result)

    # `resolved_links` was just recomputed against the FULL current code
    # state above, even for records whose OWN ADR source was not named in
    # `paths` this pass. A partial sync must still propagate that result to
    # every affected record — otherwise a citation removed from unrelated,
    # unchanged code never gets its stale `explains` link retracted here
    # (spec §2, AC7). Records already handled above (fresh reparse) are
    # skipped — their fresh parse already excludes any stale extracted link.
    for record in inventory:
        if record.decision_id in parsed_by_source:
            continue
        stripped_evidence, stripped_links = _strip_extracted_explains(record)
        extra_evidence, links = resolved_links.get(record.decision_id, ([], []))
        base_index = len(stripped_evidence)
        shifted_links = [
            DecisionLink(
                target_id=link.target_id,
                relation=link.relation,
                provenance=link.provenance,
                evidence_indexes=[idx + base_index for idx in link.evidence_indexes],
            )
            for link in links
        ]
        candidate = record.model_copy(
            update={"evidence": [*stripped_evidence, *extra_evidence], "links": [*stripped_links, *shifted_links]}
        )
        if candidate == record:
            continue
        await _persist_if_changed(repo, candidate, result)

    # A source that vanished is retained, never deleted (spec §2, AC7) — just
    # counted, using the PRE-refresh inventory so a rename's old record is
    # caught even though it was never in `sources` this pass.
    for record in inventory:
        if record.origin != "documented" or not record.source_path:
            continue
        if not (root / record.source_path).exists():
            result.missing += 1

    result.unresolved = sum(1 for d in result.diagnostics if d.code in (ADR_REFERENCE_MISSING, ADR_REFERENCE_AMBIGUOUS))

    return result


async def project_links(store: BaseWikiStore, records: list[DecisionRecord]) -> int:
    """Rebuild the navigational edge projection for ``records``.

    Edges are a rebuildable cache, never authority: retrieval validates the
    corresponding record link, so a stale projected edge can never establish
    applicability (spec §2). Safe to re-run.
    """
    edges = [
        (record.decision_id, link.target_id, link.relation, link.provenance)
        for record in records
        for link in record.links
    ]
    if not edges:
        return 0
    return await store.add_edges(edges)
