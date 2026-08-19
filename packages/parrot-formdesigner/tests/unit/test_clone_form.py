"""Unit tests for FormRegistry.clone_form (FEAT-183, updated FEAT-389).

Tests exercise the clone_form method in isolation — no storage backend,
no HTTP layer.  All tests are async (asyncio_mode = "auto" in pyproject.toml).

FEAT-389: clone_form()'s first parameter is now ``source_form_uid`` (the
immutable primary key), not ``source_form_id`` (the mutable slug) — tests
pass ``sample_form.form_uid`` (or the returned clone's ``.form_uid``)
instead of the literal slug string.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    derive_stable_identities,
)
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
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
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

    Uses ``require_tenant=False`` so the fixture form (which carries no
    explicit tenant) is sealed to ``default_tenant`` instead of being
    rejected — keeps these tests focused on clone semantics, not on
    tenant scoping (covered separately in
    ``tests/unit/test_registry_multi_tenancy.py``).

    Args:
        sample_form: Source form to register.

    Returns:
        Configured FormRegistry instance.
    """
    reg = FormRegistry(require_tenant=False)
    await reg.register(sample_form)
    return reg


# ---------------------------------------------------------------------------
# Basic clone behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_basic(registry: FormRegistry, sample_form: FormSchema) -> None:
    """Clone produces a form with the given new_form_id."""
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")
    assert clone.form_id == "cloned-form"


@pytest.mark.asyncio
async def test_clone_generates_new_uid(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """The clone always gets a fresh form_uid, distinct from the source."""
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")
    assert clone.form_uid != sample_form.form_uid


@pytest.mark.asyncio
async def test_clone_resets_version(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Source has version "2.3"; clone always starts at "1.0"."""
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")
    assert clone.version == "1.0"


@pytest.mark.asyncio
async def test_clone_resets_created_at(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """created_at is set to None on the clone (storage assigns a fresh value)."""
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")
    assert clone.created_at is None


@pytest.mark.asyncio
async def test_clone_sets_cloned_from_meta(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """meta["cloned_from"] records the source form_uid for provenance."""
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")
    assert clone.meta is not None
    assert clone.meta["cloned_from"] == sample_form.form_uid


@pytest.mark.asyncio
async def test_clone_preserves_sections(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """All sections and fields from the source are present in the clone."""
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")
    assert len(clone.sections) == 1
    assert clone.sections[0].section_id == "sec1"
    assert clone.sections[0].fields[0].field_id == "name"


# ---------------------------------------------------------------------------
# Deep copy isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_deep_copy(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Mutating the clone does NOT affect the source form."""
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")
    # Mutate a nested object on the clone
    clone.sections[0].fields[0].label = "Changed Label"

    source = await registry.get(sample_form.form_uid)
    assert source is not None
    assert source.sections[0].fields[0].label == "Full Name"


# ---------------------------------------------------------------------------
# Patch application
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_with_patch(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Merge-patch overrides are applied to the cloned form."""
    clone = await registry.clone_form(
        sample_form.form_uid,
        "patched-clone",
        patch={"title": "Patched Title"},
    )
    assert clone.form_id == "patched-clone"
    assert clone.title == "Patched Title"


@pytest.mark.asyncio
async def test_clone_patch_cannot_change_form_id(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """A form_id key in the patch is ignored — new_form_id wins."""
    clone = await registry.clone_form(
        sample_form.form_uid,
        "correct-id",
        patch={"form_id": "attacker-id"},
    )
    assert clone.form_id == "correct-id"


@pytest.mark.asyncio
async def test_clone_patch_cannot_change_form_uid(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """A form_uid key in the patch is ignored — the freshly generated
    form_uid always wins (FEAT-389)."""
    clone = await registry.clone_form(
        sample_form.form_uid,
        "uid-patch-attempt",
        patch={"form_uid": "attacker-uid"},
    )
    assert clone.form_uid != "attacker-uid"
    assert clone.form_uid != sample_form.form_uid


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_source_not_found() -> None:
    """Raises KeyError when the source form does not exist in the registry."""
    registry = FormRegistry(require_tenant=False)
    with pytest.raises(KeyError, match="not found"):
        await registry.clone_form("nonexistent-uid", "new-form")


@pytest.mark.asyncio
async def test_clone_duplicate_form_id(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Raises FormAlreadyExistsError (a ValueError) when new_form_id (slug)
    is already taken by a different form_uid."""
    from parrot_formdesigner.services.registry import FormAlreadyExistsError

    existing = FormSchema(
        form_id="taken-id",
        title="Existing Form",
        sections=[],
    )
    await registry.register(existing)
    with pytest.raises(FormAlreadyExistsError, match="already exists"):
        await registry.clone_form(sample_form.form_uid, "taken-id")


@pytest.mark.asyncio
async def test_clone_validation_error(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """A patch that breaks schema structure raises ValueError."""
    # Patch 'sections' to an invalid value — FormSchema.sections must be a list
    # of FormSection dicts; providing a string triggers a ValidationError
    # inside clone_form which is caught and re-raised as ValueError.
    with pytest.raises(ValueError):
        await registry.clone_form(
            sample_form.form_uid,
            "broken-clone",
            patch={"sections": "not-a-list"},
        )


# ---------------------------------------------------------------------------
# Tenant forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_with_tenant(sample_form: FormSchema) -> None:
    """Tenant kwarg scopes both source lookup and clone destination."""
    reg = FormRegistry()
    sample_form.tenant = "acme"
    await reg.register(sample_form)

    clone = await reg.clone_form(
        sample_form.form_uid,
        "tenant-clone",
        tenant="acme",
    )
    assert clone.tenant == "acme"
    assert await reg.contains(clone.form_uid, tenant="acme")


# ---------------------------------------------------------------------------
# Registry state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_registers_new_form(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """After cloning, the new form is retrievable from the registry."""
    clone = await registry.clone_form(sample_form.form_uid, "registered-clone")
    result = await registry.get(clone.form_uid)
    assert result is not None
    assert result.form_id == "registered-clone"


@pytest.mark.asyncio
async def test_clone_source_still_present(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Cloning does not remove or modify the source form in the registry."""
    await registry.clone_form(sample_form.form_uid, "new-clone")
    source = await registry.get(sample_form.form_uid)
    assert source is not None
    assert source.form_id == "source-form"
    assert source.version == "2.3"


# ---------------------------------------------------------------------------
# Slug collision against STORAGE (cold cache) — regression for the silent
# rename: a slug living only in the persisted table must 409, never become
# an unrequested "<slug>-2".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_slug_taken_in_storage_only_raises(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """A slug persisted in storage but absent from the in-memory index is
    still a collision: clone_form raises FormAlreadyExistsError (HTTP 409
    at the handler), instead of falling through to register()'s free-slug
    renaming."""
    from parrot_formdesigner.services.registry import FormAlreadyExistsError

    persisted_owner = FormSchema(
        form_id="taken-in-db",
        title="Persisted Elsewhere",
        sections=[],
    )

    class _ColdCacheStorage:
        async def load(self, *a, **kw):  # noqa: ANN001, ANN003
            return None

        async def load_by_slug(self, form_id, tenant, *a, **kw):  # noqa: ANN001, ANN003
            if form_id == "taken-in-db":
                return persisted_owner
            return None

    registry.set_storage(_ColdCacheStorage())
    with pytest.raises(FormAlreadyExistsError, match="already exists"):
        await registry.clone_form(
            sample_form.form_uid, "taken-in-db", persist=False
        )


@pytest.mark.asyncio
async def test_clone_storage_probe_fault_is_fail_soft(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """A storage probe that raises must not turn a working clone into an
    error: the probe reads as "no owner" and the clone proceeds."""

    class _ExplodingStorage:
        async def load(self, *a, **kw):  # noqa: ANN001, ANN003
            raise RuntimeError("pool is down")

        async def load_by_slug(self, *a, **kw):  # noqa: ANN001, ANN003
            raise RuntimeError("pool is down")

    registry.set_storage(_ExplodingStorage())
    clone = await registry.clone_form(
        sample_form.form_uid, "survives-probe-fault", persist=False
    )
    assert clone.form_id == "survives-probe-fault"


# ---------------------------------------------------------------------------
# Stable child identity on clone (field_uid / section_uid / subsection_uid)
# ---------------------------------------------------------------------------


async def test_clone_regenerates_field_uids(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """A clone must not share a single field_uid with its source.

    A deep copy inherits them verbatim; FormSchema's validator only checks
    uniqueness WITHIN a form, so nothing else catches the collision.
    """
    await registry.register(sample_form)
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")

    source_uids = {f.field_uid for f in sample_form.iter_fields_recursive()}
    clone_uids = {f.field_uid for f in clone.iter_fields_recursive()}

    assert source_uids, "fixture must expose at least one field"
    assert len(clone_uids) == len(source_uids)
    assert source_uids.isdisjoint(clone_uids)


async def test_clone_regenerates_section_uids(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Section identities are re-derived too, not carried over."""
    await registry.register(sample_form)
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")

    source_uids = {s.section_uid for s in sample_form.sections}
    clone_uids = {s.section_uid for s in clone.sections}

    assert source_uids
    assert source_uids.isdisjoint(clone_uids)


async def test_clone_field_uids_are_derived_from_the_clone_form_uid(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Each uid is uuid5(clone.form_uid, "field:<field_id>") — deterministic.

    Pinning the derivation (not merely "it changed") is what makes the
    identity reproducible: re-deriving must be a no-op.
    """
    await registry.register(sample_form)
    clone = await registry.clone_form(sample_form.form_uid, "cloned-form")

    for field in clone.iter_fields_recursive():
        assert field.field_uid == uuid.uuid5(
            clone.form_uid, f"field:{field.field_id}"
        )


async def test_clone_of_a_clone_has_distinct_uids(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """Cloning transitively keeps identities distinct at every generation."""
    await registry.register(sample_form)
    first = await registry.clone_form(sample_form.form_uid, "clone-one")
    second = await registry.clone_form(first.form_uid, "clone-two")

    a = {f.field_uid for f in sample_form.iter_fields_recursive()}
    b = {f.field_uid for f in first.iter_fields_recursive()}
    c = {f.field_uid for f in second.iter_fields_recursive()}

    assert a.isdisjoint(b) and b.isdisjoint(c) and a.isdisjoint(c)


async def test_clone_with_patch_still_derives_stable_uids(
    registry: FormRegistry, sample_form: FormSchema
) -> None:
    """The invariant holds on the patched path too, not just the plain one."""
    await registry.register(sample_form)
    clone = await registry.clone_form(
        sample_form.form_uid,
        "patched-clone",
        patch={"title": "Patched Clone"},
    )

    assert clone.title == "Patched Clone"
    source_uids = {f.field_uid for f in sample_form.iter_fields_recursive()}
    for field in clone.iter_fields_recursive():
        assert field.field_uid not in source_uids
        assert field.field_uid == uuid.uuid5(
            clone.form_uid, f"field:{field.field_id}"
        )


async def test_derive_stable_identities_is_idempotent(
    sample_form: FormSchema,
) -> None:
    """Applying the derivation twice changes nothing the second time."""
    derive_stable_identities(sample_form, sample_form.form_uid)
    first = {f.field_id: f.field_uid for f in sample_form.iter_fields_recursive()}
    derive_stable_identities(sample_form, sample_form.form_uid)
    second = {f.field_id: f.field_uid for f in sample_form.iter_fields_recursive()}

    assert first == second
