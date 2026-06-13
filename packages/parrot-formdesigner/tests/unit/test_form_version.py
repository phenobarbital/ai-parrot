"""Unit tests for FormVersionService (FEAT-300 TASK-004)."""

import pytest

from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.form_version import (
    FormVersionService,
    VersionMeta,
    _bump,
    _parse_major_minor,
)
from parrot_formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_form(form_id: str = "form1", version: str = "1.0") -> FormSchema:
    return FormSchema(
        form_id=form_id,
        version=version,
        title="Test Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1")],
            )
        ],
        tenant="t1",
    )


@pytest.fixture
def registry():
    """FormRegistry with one in-memory form registered."""
    reg = FormRegistry()
    return reg


@pytest.fixture
async def svc(registry):
    """FormVersionService with no Postgres backend (in-memory)."""
    form = _minimal_form()
    await registry.register(form, tenant="t1")
    return FormVersionService(registry, storage=None)


@pytest.fixture
async def form(registry):
    """The registered form fixture (matching svc fixture)."""
    return _minimal_form()


# ---------------------------------------------------------------------------
# Semver helpers
# ---------------------------------------------------------------------------


def test_parse_major_minor_normal():
    assert _parse_major_minor("1.0") == (1, 0)
    assert _parse_major_minor("2.5") == (2, 5)


def test_parse_major_minor_invalid_falls_back():
    assert _parse_major_minor("not-semver") == (1, 0)
    assert _parse_major_minor("") == (1, 0)
    assert _parse_major_minor(None) == (1, 0)


def test_bump_minor():
    assert _bump("1.0") == "1.1"
    assert _bump("1.1") == "1.2"
    assert _bump("2.9") == "2.10"


def test_bump_major():
    assert _bump("1.0", bump="major") == "2.0"
    assert _bump("1.5", bump="major") == "2.0"


def test_bump_twice():
    assert _bump(_bump("1.0")) == "1.2"


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


async def test_form_version_publish_sets_flag(svc, form):
    """publish() returns the new version tag and sets published_version."""
    tag = await svc.publish(form.form_id, tenant="t1")
    assert tag == "1.1"

    published = await svc.get_published(form.form_id, version=tag, tenant="t1")
    assert published is not None
    assert published.published_version == tag


async def test_form_version_publish_version_tag_correct(svc, form):
    """First publish of a 1.0 form yields 1.1."""
    tag = await svc.publish(form.form_id, tenant="t1")
    assert tag == "1.1"


async def test_form_version_publish_twice_increments(svc, form):
    """Second publish increments minor again: 1.1 → 1.2."""
    tag1 = await svc.publish(form.form_id, tenant="t1")
    tag2 = await svc.publish(form.form_id, tenant="t1")
    assert tag1 == "1.1"
    assert tag2 == "1.2"


async def test_form_version_publish_major_bump(svc, form):
    """Major bump resets minor to 0."""
    tag = await svc.publish(form.form_id, tenant="t1", bump="major")
    assert tag == "2.0"


async def test_form_version_publish_unknown_form_raises(svc):
    """publish() raises KeyError when form_id is not in registry."""
    with pytest.raises(KeyError):
        await svc.publish("no-such-form", tenant="t1")


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


async def test_form_version_immutable_on_edit(svc, form):
    """Attempting to re-publish an already-published version raises ValueError.

    Strategy:
    1. Publish once → live form bumped to 1.1; snapshot 1.1 stored.
    2. Force the live form's version back to 1.0 so the next publish
       would try to create 1.1 again.
    3. publish() must detect the existing 1.1 snapshot and raise ValueError.
    """
    tag = await svc.publish(form.form_id, tenant="t1")
    assert tag == "1.1"

    # Force live form back to 1.0 to trigger the guard on re-publish
    live = await svc._registry.get(form.form_id, tenant="t1")
    rolled_back = live.model_copy(update={"version": "1.0"})
    await svc._registry.register(rolled_back, overwrite=True, tenant="t1")

    # Now publishing again will try to create 1.1 which already exists
    with pytest.raises(ValueError, match="frozen"):
        await svc.publish(form.form_id, tenant="t1")


# ---------------------------------------------------------------------------
# List versions
# ---------------------------------------------------------------------------


async def test_form_version_list_versions(svc, form):
    """list_versions() returns the published snapshot(s)."""
    await svc.publish(form.form_id, tenant="t1")
    versions = await svc.list_versions(form.form_id, tenant="t1")
    assert len(versions) == 1
    assert isinstance(versions[0], VersionMeta)
    assert versions[0].version == "1.1"


async def test_form_version_list_versions_empty(svc, form):
    """list_versions() returns [] when no publishes have been done."""
    versions = await svc.list_versions(form.form_id, tenant="t1")
    assert versions == []


async def test_form_version_list_versions_multiple(svc, form):
    """list_versions() accumulates entries across multiple publishes."""
    await svc.publish(form.form_id, tenant="t1")
    await svc.publish(form.form_id, tenant="t1")
    versions = await svc.list_versions(form.form_id, tenant="t1")
    assert len(versions) == 2
    assert [v.version for v in versions] == ["1.1", "1.2"]


# ---------------------------------------------------------------------------
# RF-06: snapshot isolation
# ---------------------------------------------------------------------------


async def test_publish_then_edit_isolation(registry):
    """RF-06: v1 snapshot is unchanged after v2 is published."""
    form = _minimal_form("form-rf06", version="1.0")
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=None)

    v1_tag = await svc.publish("form-rf06", tenant="t1")
    original_title = form.title

    # Simulate editing the live form (changing its title)
    live = await registry.get("form-rf06", tenant="t1")
    edited = live.model_copy(update={"title": "Edited Title"})
    await registry.register(edited, overwrite=True, tenant="t1")

    # Publish a second version
    v2_tag = await svc.publish("form-rf06", tenant="t1")
    assert v2_tag != v1_tag

    # v1 snapshot must be unchanged
    snap_v1 = await svc.get_published("form-rf06", version=v1_tag, tenant="t1")
    assert snap_v1 is not None
    assert snap_v1.title == original_title  # untouched


# ---------------------------------------------------------------------------
# Deletion guard
# ---------------------------------------------------------------------------


async def test_form_version_delete_with_responses_blocked():
    """safe_delete raises ValueError when has_responses returns True."""
    registry = FormRegistry()
    form = _minimal_form("form-del")
    await registry.register(form, tenant="t1")

    async def _has_responses(form_id: str, tenant: str) -> bool:
        return True

    svc = FormVersionService(registry, has_responses=_has_responses)

    with pytest.raises(ValueError, match="responses"):
        await svc.safe_delete("form-del", tenant="t1")


async def test_form_version_delete_without_responses_allowed():
    """safe_delete succeeds when has_responses returns False."""
    registry = FormRegistry()
    form = _minimal_form("form-del2")
    await registry.register(form, tenant="t1")

    async def _no_responses(form_id: str, tenant: str) -> bool:
        return False

    svc = FormVersionService(registry, has_responses=_no_responses)
    # Should not raise
    await svc.safe_delete("form-del2", tenant="t1")


async def test_form_version_delete_no_hook_allowed():
    """safe_delete is always allowed when no has_responses hook is provided."""
    registry = FormRegistry()
    form = _minimal_form("form-del3")
    await registry.register(form, tenant="t1")

    svc = FormVersionService(registry)
    # No hook → deletion is always allowed
    await svc.safe_delete("form-del3", tenant="t1")
