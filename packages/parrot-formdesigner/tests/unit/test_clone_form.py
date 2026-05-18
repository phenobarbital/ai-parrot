"""Unit tests for FormRegistry.clone_form (FEAT-183).

Tests exercise the clone_form method in isolation — no storage backend,
no HTTP layer.  All tests are async (asyncio_mode = "auto" in pyproject.toml).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_form() -> FormSchema:
    """A multi-section source form with version "2.3" and created_at set.

    Returns:
        FormSchema instance used as clone source throughout these tests.
    """
    return FormSchema(
        form_id="source-form",
        title="Source Form",
        version="2.3",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        sections=[
            FormSection(
                section_id="sec1",
                title="Section 1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Full Name",
                        required=True,
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
async def registry(sample_form: FormSchema) -> FormRegistry:
    """FormRegistry pre-populated with the sample_form fixture.

    Args:
        sample_form: Source form to register.

    Returns:
        Configured FormRegistry instance.
    """
    reg = FormRegistry()
    await reg.register(sample_form)
    return reg


# ---------------------------------------------------------------------------
# Basic clone behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_basic(registry: FormRegistry) -> None:
    """Clone produces a form with the given new_form_id."""
    clone = await registry.clone_form("source-form", "cloned-form")
    assert clone.form_id == "cloned-form"


@pytest.mark.asyncio
async def test_clone_resets_version(registry: FormRegistry) -> None:
    """Source has version "2.3"; clone always starts at "1.0"."""
    clone = await registry.clone_form("source-form", "cloned-form")
    assert clone.version == "1.0"


@pytest.mark.asyncio
async def test_clone_resets_created_at(registry: FormRegistry) -> None:
    """created_at is set to None on the clone (storage assigns a fresh value)."""
    clone = await registry.clone_form("source-form", "cloned-form")
    assert clone.created_at is None


@pytest.mark.asyncio
async def test_clone_sets_cloned_from_meta(registry: FormRegistry) -> None:
    """meta["cloned_from"] records the source form_id for provenance."""
    clone = await registry.clone_form("source-form", "cloned-form")
    assert clone.meta is not None
    assert clone.meta["cloned_from"] == "source-form"


@pytest.mark.asyncio
async def test_clone_preserves_sections(registry: FormRegistry) -> None:
    """All sections and fields from the source are present in the clone."""
    clone = await registry.clone_form("source-form", "cloned-form")
    assert len(clone.sections) == 1
    assert clone.sections[0].section_id == "sec1"
    assert clone.sections[0].fields[0].field_id == "name"


# ---------------------------------------------------------------------------
# Deep copy isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_deep_copy(registry: FormRegistry) -> None:
    """Mutating the clone does NOT affect the source form."""
    clone = await registry.clone_form("source-form", "cloned-form")
    # Mutate a nested object on the clone
    clone.sections[0].fields[0].label = "Changed Label"

    source = await registry.get("source-form")
    assert source is not None
    assert source.sections[0].fields[0].label == "Full Name"


# ---------------------------------------------------------------------------
# Patch application
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_with_patch(registry: FormRegistry) -> None:
    """Merge-patch overrides are applied to the cloned form."""
    clone = await registry.clone_form(
        "source-form",
        "patched-clone",
        patch={"title": "Patched Title"},
    )
    assert clone.form_id == "patched-clone"
    assert clone.title == "Patched Title"


@pytest.mark.asyncio
async def test_clone_patch_cannot_change_form_id(registry: FormRegistry) -> None:
    """A form_id key in the patch is ignored — new_form_id wins."""
    clone = await registry.clone_form(
        "source-form",
        "correct-id",
        patch={"form_id": "attacker-id"},
    )
    assert clone.form_id == "correct-id"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_source_not_found() -> None:
    """Raises KeyError when the source form does not exist in the registry."""
    registry = FormRegistry()
    with pytest.raises(KeyError, match="not found"):
        await registry.clone_form("nonexistent", "new-form")


@pytest.mark.asyncio
async def test_clone_duplicate_form_id(registry: FormRegistry) -> None:
    """Raises ValueError when new_form_id already exists in the registry."""
    existing = FormSchema(
        form_id="taken-id",
        title="Existing Form",
        sections=[],
    )
    await registry.register(existing)
    with pytest.raises(ValueError, match="already exists"):
        await registry.clone_form("source-form", "taken-id")


@pytest.mark.asyncio
async def test_clone_validation_error(registry: FormRegistry) -> None:
    """A patch that breaks schema structure raises ValueError."""
    # Patch 'sections' to an invalid value — FormSchema.sections must be a list
    # of FormSection dicts; providing a string triggers a ValidationError
    # inside clone_form which is caught and re-raised as ValueError.
    with pytest.raises(ValueError):
        await registry.clone_form(
            "source-form",
            "broken-clone",
            patch={"sections": "not-a-list"},
        )


# ---------------------------------------------------------------------------
# Tenant forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_with_tenant(registry: FormRegistry) -> None:
    """Tenant kwarg is applied to the cloned form."""
    clone = await registry.clone_form(
        "source-form",
        "tenant-clone",
        tenant="acme",
    )
    assert clone.tenant == "acme"


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_registers_new_form(registry: FormRegistry) -> None:
    """After cloning, the new form is retrievable from the registry."""
    await registry.clone_form("source-form", "registered-clone")
    clone = await registry.get("registered-clone")
    assert clone is not None
    assert clone.form_id == "registered-clone"


@pytest.mark.asyncio
async def test_clone_source_still_present(registry: FormRegistry) -> None:
    """Cloning does not remove or modify the source form in the registry."""
    await registry.clone_form("source-form", "new-clone")
    source = await registry.get("source-form")
    assert source is not None
    assert source.form_id == "source-form"
    assert source.version == "2.3"
