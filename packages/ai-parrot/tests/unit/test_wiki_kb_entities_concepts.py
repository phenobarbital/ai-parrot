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
