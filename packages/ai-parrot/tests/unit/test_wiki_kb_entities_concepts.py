"""Unit tests for the entity + concept resolvers (FEAT-481, spec Module 10
/ TASK-2668): match-before-create, §20/§21 template fidelity, materiality
gating.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest.nodes.concepts import (
    ConceptExtraction,
    run_concept_resolve,
)
from parrot.flows.wiki_ingest.nodes.entities import (
    EntityExtraction,
    find_matching_page,
    run_entity_resolve,
)
from parrot.tools.obsidian import ObsidianToolkit


class _FakeInvokeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


def _fake_client(output: Any) -> AsyncMock:
    client = AsyncMock()
    client.invoke = AsyncMock(return_value=_FakeInvokeResult(output))
    return client


def _toolkit(vault_path: Path) -> ObsidianToolkit:
    return ObsidianToolkit(
        vault_path=str(vault_path),
        allowed_operations={"read", "list", "search", "create", "update", "move", "delete"},
    )


@pytest.mark.asyncio
async def test_match_before_create_alias(tmp_path: Path) -> None:
    """An existing entity matched by alias/spelling variant is reused,
    not duplicated."""
    companies_dir = tmp_path / "Wiki" / "Entities" / "Companies"
    companies_dir.mkdir(parents=True)
    (companies_dir / "Acme Corporation.md").write_text(
        "---\ntitle: Acme Corporation\naliases: [Acme, Acme Corp]\n---\n\n# Acme Corporation\n",
        encoding="utf-8",
    )
    toolkit = _toolkit(tmp_path)

    match = await find_matching_page(toolkit, "Acme", folder="Wiki/Entities/Companies")

    assert match is not None
    assert match.path.startswith("Wiki/Entities/Companies/Acme Corporation")
    assert match.canonical_name == "Acme Corporation"


@pytest.mark.asyncio
async def test_match_before_create_exact_filename(tmp_path: Path) -> None:
    people_dir = tmp_path / "Wiki" / "Entities" / "People"
    people_dir.mkdir(parents=True)
    (people_dir / "Jane Doe.md").write_text("# Jane Doe\n", encoding="utf-8")
    toolkit = _toolkit(tmp_path)

    match = await find_matching_page(toolkit, "jane doe", folder="Wiki/Entities/People")

    assert match is not None
    assert match.canonical_name == "Jane Doe"


@pytest.mark.asyncio
async def test_no_match_returns_none(tmp_path: Path) -> None:
    toolkit = _toolkit(tmp_path)
    match = await find_matching_page(toolkit, "Nonexistent Co", folder="Wiki/Entities/Companies")
    assert match is None


@pytest.mark.asyncio
async def test_entity_resolve_updates_existing_not_duplicate(tmp_path: Path) -> None:
    companies_dir = tmp_path / "Wiki" / "Entities" / "Companies"
    companies_dir.mkdir(parents=True)
    (companies_dir / "Acme Corporation.md").write_text(
        "---\ntitle: Acme Corporation\naliases: [Acme]\n---\n\n"
        "# Acme Corporation\n\n## Summary\nAn existing client.\n\n"
        "## Known Roles or Characteristics\n- Not established\n\n"
        "## Project Relationships\n- None identified\n\n"
        "## Related Entities\n- None identified\n\n"
        "## Open Questions or Ambiguities\n- None identified\n\n"
        "## Sources\n- None identified\n\n## Human Notes\n(none)\n",
        encoding="utf-8",
    )
    toolkit = _toolkit(tmp_path)
    client = _fake_client(
        EntityExtraction(
            materially_relevant=True, summary="A key client for the rollout.", known_roles=["Primary client"]
        )
    )

    result = await run_entity_resolve(
        client,
        toolkit,
        "Acme",
        "company",
        project_name="Acme Rollout",
        meeting_source_link="Wiki/Sources/Meetings/new",
        meeting_summary="Discussed rollout with Acme.",
    )

    assert result.action == "updated"
    assert result.vault_path == "Wiki/Entities/Companies/Acme Corporation.md"
    assert "Primary client" in result.content


@pytest.mark.asyncio
async def test_entity_update_preserves_created_and_merges_projects(tmp_path: Path) -> None:
    """§10.3 — updating a matched entity for a NEW project must preserve
    the original ``created`` timestamp and MERGE ``projects``/``aliases``
    (never overwrite them). Regression: the update previously reset
    ``created`` to now and set ``projects`` to only the current meeting's
    project, silently erasing prior associations."""
    companies_dir = tmp_path / "Wiki" / "Entities" / "Companies"
    companies_dir.mkdir(parents=True)
    (companies_dir / "Acme Corporation.md").write_text(
        "---\n"
        "id: company:acme-corporation\n"
        "type: company\n"
        "title: Acme Corporation\n"
        "aliases: [Acme]\n"
        "projects: [Legacy Rollout]\n"
        "source_pages: [Wiki/Sources/Meetings/old]\n"
        "created: '2020-01-01T00:00:00+00:00'\n"
        "updated: '2020-01-01T00:00:00+00:00'\n"
        "---\n\n"
        "# Acme Corporation\n\n## Summary\nAn existing client.\n\n"
        "## Known Roles or Characteristics\n- Not established\n\n"
        "## Project Relationships\n- None identified\n\n"
        "## Related Entities\n- None identified\n\n"
        "## Open Questions or Ambiguities\n- None identified\n\n"
        "## Sources\n- [[Wiki/Sources/Meetings/old]]\n\n## Human Notes\n(none)\n",
        encoding="utf-8",
    )
    toolkit = _toolkit(tmp_path)
    client = _fake_client(EntityExtraction(materially_relevant=True, summary="Still a key client.", known_roles=[]))

    result = await run_entity_resolve(
        client,
        toolkit,
        "Acme",
        "company",
        project_name="Acme Rollout",
        meeting_source_link="Wiki/Sources/Meetings/new",
        meeting_summary="Discussed the new rollout with Acme.",
    )

    assert result.action == "updated"
    assert result.frontmatter is not None
    # created preserved, updated advanced
    assert result.frontmatter.created == "2020-01-01T00:00:00+00:00"
    assert result.frontmatter.updated != "2020-01-01T00:00:00+00:00"
    # projects merged, not replaced
    assert "Legacy Rollout" in result.frontmatter.projects
    assert "Acme Rollout" in result.frontmatter.projects
    # aliases preserved even though we matched by the alias
    assert "Acme" in result.frontmatter.aliases


@pytest.mark.asyncio
async def test_entity_resolve_creates_new(tmp_path: Path) -> None:
    toolkit = _toolkit(tmp_path)
    client = _fake_client(EntityExtraction(materially_relevant=True, summary="A new person.", known_roles=["Attendee"]))

    result = await run_entity_resolve(
        client,
        toolkit,
        "Jane Doe",
        "person",
        project_name=None,
        meeting_source_link="Wiki/Sources/Meetings/new",
        meeting_summary="Jane joined the call.",
    )

    assert result.action == "created"
    assert result.vault_path == "Wiki/Entities/People/Jane Doe.md"
    assert "## Summary\nA new person." in result.content


@pytest.mark.asyncio
async def test_batch_resolves_entities_and_concepts_in_one_call(tmp_path: Path) -> None:
    """The batch resolver issues ONE (cheap-tier) extraction call for ALL of a
    meeting's entities + concepts and produces the same pages the per-candidate
    resolvers would — the core FEAT-481 LLM cost optimization."""
    from parrot.flows.wiki_ingest.nodes.entity_concept_batch import (
        BatchConceptItem,
        BatchEntityItem,
        BatchExtraction,
        run_entities_and_concepts,
    )

    toolkit = _toolkit(tmp_path)
    calls = {"n": 0}

    async def _invoke(prompt, *, output_type=None, **kwargs):
        calls["n"] += 1
        return _FakeInvokeResult(
            BatchExtraction(
                entities=[
                    BatchEntityItem(name="Jane Doe", entity_type="person", materially_relevant=True, summary="Attendee."),
                    BatchEntityItem(name="Acme Corp", entity_type="company", materially_relevant=True, summary="Client."),
                ],
                concepts=[
                    BatchConceptItem(
                        name="OAuth2", materially_relevant=True, definition="Auth pattern.", why_it_matters="SSO."
                    )
                ],
            )
        )

    client = AsyncMock()
    client.invoke = AsyncMock(side_effect=_invoke)

    entity_results, concept_results = await run_entities_and_concepts(
        client,
        toolkit,
        entity_candidates=[("Jane Doe", "person"), ("Acme Corp", "company")],
        concept_candidates=["OAuth2"],
        project_name="Acme Rollout",
        meeting_source_link="Wiki/Sources/Meetings/new",
        meeting_summary="Discussed OAuth2 SSO with Acme's Jane.",
    )

    assert calls["n"] == 1  # ONE call for all three candidates, not three
    assert {r.vault_path for r in entity_results} == {
        "Wiki/Entities/People/Jane Doe.md",
        "Wiki/Entities/Companies/Acme Corp.md",
    }
    assert all(r.action == "created" for r in entity_results)
    assert concept_results[0].vault_path == "Wiki/Concepts/OAuth2.md"


@pytest.mark.asyncio
async def test_batch_immaterial_items_not_created(tmp_path: Path) -> None:
    """A batch item flagged not materially relevant produces no page (§20/§21)."""
    from parrot.flows.wiki_ingest.nodes.entity_concept_batch import (
        BatchEntityItem,
        BatchExtraction,
        run_entities_and_concepts,
    )

    toolkit = _toolkit(tmp_path)

    async def _invoke(prompt, *, output_type=None, **kwargs):
        return _FakeInvokeResult(
            BatchExtraction(
                entities=[BatchEntityItem(name="Someone", entity_type="person", materially_relevant=False, summary="")]
            )
        )

    client = AsyncMock()
    client.invoke = AsyncMock(side_effect=_invoke)

    entity_results, _ = await run_entities_and_concepts(
        client,
        toolkit,
        entity_candidates=[("Someone", "person")],
        concept_candidates=[],
        project_name=None,
        meeting_source_link="Wiki/Sources/Meetings/new",
        meeting_summary="Someone said hi.",
    )
    assert entity_results[0].action == "not_created"
    assert entity_results[0].content is None


@pytest.mark.asyncio
async def test_batch_no_candidates_makes_no_call(tmp_path: Path) -> None:
    """No entity/concept candidates → no LLM call at all."""
    from parrot.flows.wiki_ingest.nodes.entity_concept_batch import run_entities_and_concepts

    toolkit = _toolkit(tmp_path)
    client = AsyncMock()
    client.invoke = AsyncMock()

    entity_results, concept_results = await run_entities_and_concepts(
        client,
        toolkit,
        entity_candidates=[],
        concept_candidates=[],
        project_name=None,
        meeting_source_link="Wiki/Sources/Meetings/new",
        meeting_summary="x",
    )
    assert entity_results == []
    assert concept_results == []
    client.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_no_concept_for_every_noun(tmp_path: Path) -> None:
    """materially_relevant=False produces no page (§21 — not every noun)."""
    toolkit = _toolkit(tmp_path)
    client = _fake_client(ConceptExtraction(materially_relevant=False, definition="x", why_it_matters="x"))

    result = await run_concept_resolve(
        client,
        toolkit,
        "Tuesday",
        project_name="Acme Rollout",
        meeting_source_link="Wiki/Sources/Meetings/new",
        meeting_summary="They met on Tuesday.",
    )

    assert result.action == "not_created"
    assert result.content is None
    assert not (tmp_path / "Wiki" / "Concepts").exists()


@pytest.mark.asyncio
async def test_concept_resolve_creates_material_concept(tmp_path: Path) -> None:
    toolkit = _toolkit(tmp_path)
    client = _fake_client(
        ConceptExtraction(
            materially_relevant=True,
            definition="A recurring technical pattern for auth.",
            why_it_matters="Central to the SSO rollout.",
            application_note="Used to implement SSO.",
        )
    )

    result = await run_concept_resolve(
        client,
        toolkit,
        "OAuth2",
        project_name="Acme Rollout",
        meeting_source_link="Wiki/Sources/Meetings/new",
        meeting_summary="Discussed OAuth2 for SSO.",
    )

    assert result.action == "created"
    assert result.vault_path == "Wiki/Concepts/OAuth2.md"
    assert "## Definition\nA recurring technical pattern for auth." in result.content
    assert "[[Projects/Acme Rollout/Acme Rollout|Acme Rollout]] - Used to implement SSO." in result.content
