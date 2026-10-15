"""Batched entity + concept resolution (FEAT-481, LLM cost optimization).

Replaces the per-candidate strong-tier calls (one LLM call per person /
product / company / concept) with a SINGLE cheap-tier extraction call for
the whole meeting, then applies each result deterministically via the
shared ``apply_*`` functions so the rendered pages are byte-identical to
the per-candidate path.

Why this is safe/correct:
  * **Tier (G7).** Entity/concept extraction is *bulk extraction*, not the
    "reconciliation / ambiguous classification / contradiction reasoning"
    the strong tier is reserved for. The match-before-create lookup is
    already deterministic (:func:`~.entities.find_matching_page`), so the
    strong tier was never needed for correctness here — only the cheap tier.
  * **Fan-out.** The contract mandates the OUTPUT pages, not one LLM call
    per entity; collapsing N calls into 1 is a pure implementation win.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient
from parrot.tools.obsidian import ObsidianToolkit

from . import concepts as concepts_node
from . import entities as entities_node
from .concepts import ConceptExtraction, ConceptResolveResult
from .entities import EntityExtraction, EntityResolveResult, _normalize

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are extracting entity and concept content for a governed knowledge "
    "base (contract §20/§21) from ONE meeting. For EACH candidate you are "
    "given, decide whether it is materially relevant to this meeting and, if "
    "so, produce its content. Set materially_relevant=false for a passing "
    "mention or 'every noun'. Never infer a role, relationship, definition, or "
    "significance the meeting does not support — use 'Unknown'/'Not "
    "established' when evidence is insufficient (rule #12). Return exactly one "
    "item per candidate you were given, keyed by its exact name; never invent "
    "candidates that were not listed."
)


class BatchEntityItem(EntityExtraction):
    """One entity's extraction within the batch (adds its identity keys)."""

    name: str
    entity_type: Literal["person", "company", "product"]


class BatchConceptItem(ConceptExtraction):
    """One concept's extraction within the batch (adds its identity key)."""

    name: str


class BatchExtraction(BaseModel):
    """The cheap-tier client's combined per-candidate extraction."""

    entities: list[BatchEntityItem] = Field(default_factory=list)
    concepts: list[BatchConceptItem] = Field(default_factory=list)


def _build_prompt(
    entity_order: list[tuple[str, str]],
    entity_ctx: dict[tuple[str, str], tuple[str, Any, Any, dict[str, Any]]],
    concept_order: list[str],
    concept_ctx: dict[str, tuple[str, Any, Any]],
    *,
    project_name: str | None,
    meeting_source_link: str,
    meeting_summary: str,
) -> str:
    """Build the single combined §20/§21 batch-extraction prompt."""
    lines = [
        f"Meeting: {meeting_source_link}",
        f"Primary project: {project_name or 'Unknown'}",
        "",
        "Fireflies summary:",
        meeting_summary or "(no summary available)",
        "",
        "Entity candidates (return one item per candidate; key by exact name + entity_type):",
    ]
    for name, entity_type in entity_order:
        _, _, state, _ = entity_ctx[(entity_type, _normalize(name))]
        existing = (state.summary if state else "") or "(new entity)"
        lines.append(f"- {name} ({entity_type}) [existing: {existing}]")
    lines.append("")
    lines.append("Concept candidates (return one item per candidate; key by exact name):")
    for name in concept_order:
        _, _, state = concept_ctx[_normalize(name)]
        existing = (state.definition if state else "") or "(new concept)"
        lines.append(f"- {name} [existing: {existing}]")
    return "\n".join(lines)


async def run_entities_and_concepts(
    client: AbstractClient,
    toolkit: ObsidianToolkit,
    *,
    entity_candidates: list[tuple[str, str]],
    concept_candidates: list[str],
    project_name: str | None,
    meeting_source_link: str,
    meeting_summary: str,
) -> tuple[list[EntityResolveResult], list[ConceptResolveResult]]:
    """Resolve every entity + concept for one meeting in ONE cheap LLM call.

    Args:
        client: The tier client to use (the cheap tier — this is bulk
            extraction, G7).
        toolkit: This subsystem's own :class:`ObsidianToolkit`.
        entity_candidates: ``(name, entity_type)`` pairs (person/company/
            product).
        concept_candidates: Concept names.
        project_name: The meeting's primary project (``None`` if unresolved).
        meeting_source_link: Wikilink target of the meeting source page.
        meeting_summary: The Fireflies summary text (extraction input).

    Returns:
        ``(entity_results, concept_results)`` — apply results ready to
        write (``action == "not_created"`` entries carry no content and are
        skipped by the caller). Empty lists when there are no candidates.
    """
    # 1. Deterministic gather (no LLM), de-duplicated by kind + normalized name.
    entity_ctx: dict[tuple[str, str], tuple[str, Any, Any, dict[str, Any]]] = {}
    entity_order: list[tuple[str, str]] = []
    for entity_name, entity_type in entity_candidates:
        ekey = (entity_type, _normalize(entity_name))
        if ekey in entity_ctx:
            continue
        e_match, e_state, e_frontmatter = await entities_node.resolve_existing_entity(
            toolkit, entity_name, entity_type  # type: ignore[arg-type]
        )
        entity_ctx[ekey] = (entity_name, e_match, e_state, e_frontmatter)
        entity_order.append((entity_name, entity_type))

    concept_ctx: dict[str, tuple[str, Any, Any]] = {}
    concept_order: list[str] = []
    for concept_name in concept_candidates:
        ckey = _normalize(concept_name)
        if ckey in concept_ctx:
            continue
        c_match, c_state = await concepts_node.resolve_existing_concept(toolkit, concept_name)
        concept_ctx[ckey] = (concept_name, c_match, c_state)
        concept_order.append(concept_name)

    if not entity_ctx and not concept_ctx:
        return [], []

    # 2. ONE shared extraction call (cheap tier).
    prompt = _build_prompt(
        entity_order,
        entity_ctx,
        concept_order,
        concept_ctx,
        project_name=project_name,
        meeting_source_link=meeting_source_link,
        meeting_summary=meeting_summary,
    )
    result = await client.invoke(prompt, output_type=BatchExtraction, system_prompt=_SYSTEM_PROMPT, temperature=0.0)
    batch = result.output if isinstance(result.output, BatchExtraction) else BatchExtraction()

    # 3. Apply each returned item to its gathered context (deterministic; the
    #    batch items subclass EntityExtraction/ConceptExtraction so they feed
    #    the shared apply_* functions directly — identical pages to the
    #    per-candidate path).
    entity_results: list[EntityResolveResult] = []
    for item in batch.entities:
        ent_ctx = entity_ctx.get((item.entity_type, _normalize(item.name)))
        if ent_ctx is None:
            logger.warning("Batch returned an unrequested entity %r (%s); ignoring", item.name, item.entity_type)
            continue
        ent_name, ent_match, ent_state, ent_frontmatter = ent_ctx
        entity_results.append(
            entities_node.apply_entity_extraction(
                item,
                candidate_name=ent_name,
                entity_type=item.entity_type,
                match=ent_match,
                existing_state=ent_state,
                existing_frontmatter=ent_frontmatter,
                project_name=project_name,
                meeting_source_link=meeting_source_link,
            )
        )

    concept_results: list[ConceptResolveResult] = []
    for concept_item in batch.concepts:
        con_ctx = concept_ctx.get(_normalize(concept_item.name))
        if con_ctx is None:
            logger.warning("Batch returned an unrequested concept %r; ignoring", concept_item.name)
            continue
        con_name, con_match, con_state = con_ctx
        concept_results.append(
            concepts_node.apply_concept_extraction(
                concept_item,
                candidate_name=con_name,
                match=con_match,
                existing_state=con_state,
                project_name=project_name,
                meeting_source_link=meeting_source_link,
            )
        )

    return entity_results, concept_results
