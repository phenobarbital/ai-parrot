"""Unit tests for FormVersionService.backfill_published() (FEAT-300 TASK-005)."""

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.form_version import FormVersionService
from parrot_formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _legacy_form(form_id: str, version: str = "1.0") -> FormSchema:
    """Create a form with no published_version (legacy state)."""
    return FormSchema(
        form_id=form_id,
        version=version,
        title=f"Legacy Form {form_id}",
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1")],
            )
        ],
        tenant="t1",
        published_version=None,
    )


async def _registry_with_forms(*forms: FormSchema, tenant: str = "t1") -> FormRegistry:
    reg = FormRegistry()
    for form in forms:
        await reg.register(form, tenant=tenant)
    return reg


# ---------------------------------------------------------------------------
# Basic backfill
# ---------------------------------------------------------------------------


async def test_backfill_marks_existing_forms():
    """backfill_published() sets published_version on legacy forms."""
    reg = await _registry_with_forms(
        _legacy_form("form-a"),
        _legacy_form("form-b"),
    )
    svc = FormVersionService(reg)

    changed = await svc.backfill_published(tenant="t1")
    assert changed == 2

    a = await reg.get("form-a", tenant="t1")
    b = await reg.get("form-b", tenant="t1")
    assert a.published_version == "1.0"
    assert b.published_version == "1.0"


async def test_backfill_preserves_existing_version_string():
    """backfill_published() uses the form's existing version value, not always '1.0'."""
    reg = await _registry_with_forms(_legacy_form("form-v2", version="2.0"))
    svc = FormVersionService(reg)

    await svc.backfill_published(tenant="t1")

    form = await reg.get("form-v2", tenant="t1")
    assert form.published_version == "2.0"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_backfill_idempotent():
    """Running backfill twice: second run returns 0 (nothing to do)."""
    reg = await _registry_with_forms(
        _legacy_form("form-a"),
        _legacy_form("form-b"),
    )
    svc = FormVersionService(reg)

    first = await svc.backfill_published(tenant="t1")
    assert first == 2

    second = await svc.backfill_published(tenant="t1")
    assert second == 0


async def test_backfill_already_published_forms_skipped():
    """Forms with published_version already set are skipped."""
    already_published = FormSchema(
        form_id="form-pub",
        version="1.0",
        title="Published",
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1")],
            )
        ],
        tenant="t1",
        published_version="1.0",  # already published
    )
    reg = await _registry_with_forms(already_published, _legacy_form("form-new"))
    svc = FormVersionService(reg)

    changed = await svc.backfill_published(tenant="t1")
    assert changed == 1  # only form-new


async def test_backfill_empty_tenant_returns_zero():
    """backfill_published() returns 0 when no forms exist for the tenant."""
    reg = FormRegistry()
    svc = FormVersionService(reg)

    changed = await svc.backfill_published(tenant="t1")
    assert changed == 0


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


async def test_backfill_dry_run_persists_nothing():
    """dry_run=True returns a positive count but does not set published_version."""
    reg = await _registry_with_forms(
        _legacy_form("form-a"),
        _legacy_form("form-b"),
    )
    svc = FormVersionService(reg)

    changed = await svc.backfill_published(tenant="t1", dry_run=True)
    assert changed == 2

    # published_version must remain None after a dry-run
    a = await reg.get("form-a", tenant="t1")
    b = await reg.get("form-b", tenant="t1")
    assert a.published_version is None
    assert b.published_version is None


async def test_backfill_dry_run_then_real_run():
    """A dry-run followed by the real run correctly backfills."""
    reg = await _registry_with_forms(_legacy_form("form-a"))
    svc = FormVersionService(reg)

    dry = await svc.backfill_published(tenant="t1", dry_run=True)
    real = await svc.backfill_published(tenant="t1", dry_run=False)

    assert dry == 1
    assert real == 1

    # Real run idempotency
    second = await svc.backfill_published(tenant="t1", dry_run=False)
    assert second == 0


# ---------------------------------------------------------------------------
# Version metadata
# ---------------------------------------------------------------------------


async def test_backfill_records_version_meta():
    """After backfill, list_versions() returns the backfilled version entry."""
    reg = await _registry_with_forms(_legacy_form("form-a"))
    svc = FormVersionService(reg)

    await svc.backfill_published(tenant="t1")

    versions = await svc.list_versions("form-a", tenant="t1")
    assert len(versions) == 1
    assert versions[0].version == "1.0"
    assert versions[0].is_frozen is True
