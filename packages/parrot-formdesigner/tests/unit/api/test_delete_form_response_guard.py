"""``DELETE /api/v1/forms/{form_uid}`` — response guard and delete ordering.

Two contracts live here, both exercised over a real HTTP round trip against
an app built by the public ``setup_form_api()`` entry point:

1. **The FEAT-300 §8 response guard is reachable from the public API.**
   ``FormVersionService`` has always accepted a ``has_responses`` hook, but
   until ``setup_form_api()`` grew a way to supply one, ``can_delete()``
   returned ``True`` for every caller. Configuring ``submission_storage=``
   now derives the hook from
   ``FormSubmissionStorage.has_submissions``. A consumer that configures no
   submission storage keeps the old, unguarded behaviour.

2. **Storage is deleted before the registry is unregistered.**
   ``FormRegistry.unregister()`` is memory-only, so unregistering first and
   swallowing a storage error reports ``204`` for a form that returns on the
   next restart or hydration.

Why this module goes through ``setup_form_api`` instead of calling the
handler directly (the dominant pattern in this suite, documented in
``tests/test_form_uid_integration.py``): the behaviour under test IS the
wiring that ``setup_form_api`` performs. A direct
``FormAPIHandler(has_responses=...)`` construction, or an injected private
``_version_service``, would pass even if ``setup_form_api`` forwarded
nothing. Reaching the handler over HTTP means neutralising the
navigator-auth decorators that ``_wrap_auth`` applies at registration time;
the ``_noop_auth`` fixture below does that and nothing else.

The submission storage is a real ``FormSubmissionStorage`` driven by the
recording asyncpg stubs the rest of the suite uses, so the guard is proved
through the production query path rather than a hand-written double.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from aiohttp import web

from parrot_formdesigner.api import routes as routes_module
from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry, FormStorage
from parrot_formdesigner.services.submissions import FormSubmissionStorage

from tests.unit.test_storage_schema_tenant import _RecordingPool
from tests.unit.test_submission_revisions import _RowsPool

TENANT = "t1"
FORM_UID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def _noop_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the navigator-auth route decorators with pass-throughs.

    ``api/routes.py`` binds ``is_authenticated`` / ``user_session`` with a
    ``from ... import`` at module load, so the names must be patched on the
    ``routes`` module itself, and before ``setup_form_api()`` runs.
    """

    def _factory(*_args: Any, **_kwargs: Any):
        def _passthrough(handler):
            return handler

        return _passthrough

    monkeypatch.setattr(routes_module, "is_authenticated", _factory)
    monkeypatch.setattr(routes_module, "user_session", _factory)


def _make_form() -> FormSchema:
    """A minimal form pinned to a fixed ``form_uid``."""
    return FormSchema(
        form_id="guarded-form",
        title="Guarded Form",
        version="1.0",
        tenant=TENANT,
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1")],
            )
        ],
    ).model_copy(update={"form_uid": FORM_UID})


async def _make_client(aiohttp_client, registry: FormRegistry, **kwargs):
    """Mount the REST surface via the public seam and return a test client."""
    app = web.Application()
    setup_form_api(app, registry, **kwargs)
    return await aiohttp_client(app)


async def _registry_with_form(
    storage: FormStorage | None = None,
) -> tuple[FormRegistry, FormSchema]:
    registry = FormRegistry(storage, default_tenant=TENANT, require_tenant=False)
    form = _make_form()
    # persist=False — the form is seeded straight into the in-memory index so
    # no storage write is attempted here.
    await registry.register(form, persist=False, tenant=TENANT)
    return registry, form


def _storage_with_submissions() -> FormSubmissionStorage:
    """A real submission storage whose probe finds a row."""
    return FormSubmissionStorage(pool=_RowsPool(row={"exists": 1}))


def _storage_without_submissions() -> FormSubmissionStorage:
    """A real submission storage whose probe finds nothing."""
    return FormSubmissionStorage(pool=_RecordingPool())


# ---------------------------------------------------------------------------
# Form storage doubles
# ---------------------------------------------------------------------------


class _BaseStorage(FormStorage):
    """No-op FormStorage; subclasses override the one method under test."""

    async def save(self, form, style=None, *, tenant=None) -> str:
        return str(form.form_uid)

    async def load(self, form_uid, version=None, *, tenant=None):
        return None

    async def delete(self, form_uid, *, tenant=None) -> bool:
        return True

    async def list_forms(self, *, tenant=None) -> list[dict[str, Any]]:
        return []


class _DeleteFailsStorage(_BaseStorage):
    """Storage whose delete always fails — simulates an unreachable DB."""

    async def delete(self, form_uid, *, tenant=None) -> bool:
        raise ConnectionError("database unreachable")


class _OrderRecordingStorage(_BaseStorage):
    """Storage that records whether the form was still registered on delete.

    This is how the ordering contract is observed rather than assumed: the
    registry is queried from inside ``storage.delete()``, so a handler that
    unregistered first would record ``False``.
    """

    def __init__(self) -> None:
        self.registry: FormRegistry | None = None
        self.form_present_at_delete: bool | None = None

    async def delete(self, form_uid, *, tenant=None) -> bool:
        assert self.registry is not None
        found = await self.registry.get(form_uid, tenant=TENANT)
        self.form_present_at_delete = found is not None
        return True


# ---------------------------------------------------------------------------
# 1. The response guard, through setup_form_api
# ---------------------------------------------------------------------------


class TestResponseGuardViaPublicSeam:
    async def test_form_with_submissions_is_refused(self, aiohttp_client, _noop_auth) -> None:
        """409 — FEAT-300 §8: deactivate a form with responses, never delete."""
        registry, form = await _registry_with_form()
        client = await _make_client(
            aiohttp_client,
            registry,
            submission_storage=_storage_with_submissions(),
        )

        resp = await client.delete(f"/api/v1/forms/{FORM_UID}")

        assert resp.status == 409
        body = await resp.json()
        assert "cannot be deleted" in body["error"]
        # The form survives the refusal.
        assert await registry.get(FORM_UID, tenant=TENANT) is not None

    async def test_form_without_submissions_is_deleted(self, aiohttp_client, _noop_auth) -> None:
        """204 — the guard permits deletion when the probe finds no rows."""
        registry, form = await _registry_with_form()
        client = await _make_client(
            aiohttp_client,
            registry,
            submission_storage=_storage_without_submissions(),
        )

        resp = await client.delete(f"/api/v1/forms/{FORM_UID}")

        assert resp.status == 204
        assert await registry.get(FORM_UID, tenant=TENANT) is None

    async def test_explicit_hook_overrides_the_derived_one(self, aiohttp_client, _noop_auth) -> None:
        """An explicit ``has_responses=`` wins over ``submission_storage``.

        The storage here reports a submission, so the derived hook would
        refuse; the override permits, and the override is what applies.
        """
        registry, form = await _registry_with_form()

        async def _never_has_responses(form_uid, tenant) -> bool:
            return False

        client = await _make_client(
            aiohttp_client,
            registry,
            submission_storage=_storage_with_submissions(),
            has_responses=_never_has_responses,
        )

        resp = await client.delete(f"/api/v1/forms/{FORM_UID}")

        assert resp.status == 204

    async def test_explicit_hook_works_without_submission_storage(self, aiohttp_client, _noop_auth) -> None:
        """A consumer may enforce its own policy with no submission storage."""
        registry, form = await _registry_with_form()

        async def _always_has_responses(form_uid, tenant) -> bool:
            return True

        client = await _make_client(aiohttp_client, registry, has_responses=_always_has_responses)

        resp = await client.delete(f"/api/v1/forms/{FORM_UID}")

        assert resp.status == 409
        assert await registry.get(FORM_UID, tenant=TENANT) is not None

    async def test_hook_receives_the_request_tenant(self, aiohttp_client, _noop_auth) -> None:
        """The hook is called with the form_uid and the resolved tenant."""
        registry, form = await _registry_with_form()
        seen: list[tuple[Any, Any]] = []

        async def _record(form_uid, tenant) -> bool:
            seen.append((form_uid, tenant))
            return False

        client = await _make_client(aiohttp_client, registry, has_responses=_record)

        resp = await client.delete(f"/api/v1/forms/{FORM_UID}")

        assert resp.status == 204
        assert seen == [(FORM_UID, TENANT)]


# ---------------------------------------------------------------------------
# 2. Backward compatibility — no submission_storage means no guard
# ---------------------------------------------------------------------------


class TestNoSubmissionStorageKeepsOldBehaviour:
    async def test_delete_allowed_when_no_submission_storage_configured(self, aiohttp_client, _noop_auth) -> None:
        """The compatibility guarantee.

        A consumer that never passes ``submission_storage`` (and no explicit
        hook) must see exactly what it saw before the guard was wired up:
        deletion proceeds and returns 204. This is the test that fails if the
        default hook is ever made unconditional.
        """
        registry, form = await _registry_with_form()
        client = await _make_client(aiohttp_client, registry)

        resp = await client.delete(f"/api/v1/forms/{FORM_UID}")

        assert resp.status == 204
        assert await registry.get(FORM_UID, tenant=TENANT) is None

    async def test_version_service_has_no_hook_when_nothing_configured(
        self,
    ) -> None:
        """``can_delete`` stays permissive with nothing configured.

        Pins the resolution order at the unit level: no submission storage
        and no explicit hook must leave ``has_responses`` unset, which is
        what keeps ``FormVersionService.can_delete()`` returning ``True``.
        """
        from parrot_formdesigner.api.handlers import FormAPIHandler

        registry, _ = await _registry_with_form()
        handler = FormAPIHandler(registry=registry)

        assert handler._build_has_responses_hook() is None
        assert await handler._get_version_service().can_delete(FORM_UID, tenant=TENANT) is True


# ---------------------------------------------------------------------------
# 3. Delete ordering — storage first, registry second
# ---------------------------------------------------------------------------


class TestDeleteOrdering:
    async def test_storage_failure_returns_500_and_keeps_the_form(self, aiohttp_client, _noop_auth) -> None:
        """A failed storage delete must not report success.

        Before the fix the handler unregistered first and swallowed the
        exception, returning 204 for a form that reappeared on the next
        restart or registry hydration.
        """
        registry, form = await _registry_with_form(_DeleteFailsStorage())
        client = await _make_client(aiohttp_client, registry)

        resp = await client.delete(f"/api/v1/forms/{FORM_UID}")

        assert resp.status == 500
        body = await resp.json()
        assert "Failed to delete" in body["error"]
        # The registry is untouched, so memory and database still agree.
        assert await registry.get(FORM_UID, tenant=TENANT) is not None

    async def test_storage_delete_runs_before_unregister(self, aiohttp_client, _noop_auth) -> None:
        """Observed ordering, not assumed: the form is still registered when
        ``storage.delete()`` is called."""
        storage = _OrderRecordingStorage()
        registry, form = await _registry_with_form(storage)
        storage.registry = registry
        client = await _make_client(aiohttp_client, registry)

        resp = await client.delete(f"/api/v1/forms/{FORM_UID}")

        assert resp.status == 204
        assert storage.form_present_at_delete is True
        assert await registry.get(FORM_UID, tenant=TENANT) is None

    async def test_successful_delete_removes_form_with_storage_configured(self, aiohttp_client, _noop_auth) -> None:
        registry, form = await _registry_with_form(_BaseStorage())
        client = await _make_client(aiohttp_client, registry)

        resp = await client.delete(f"/api/v1/forms/{FORM_UID}")

        assert resp.status == 204
        assert await registry.get(FORM_UID, tenant=TENANT) is None

    async def test_unknown_form_still_404s(self, aiohttp_client, _noop_auth) -> None:
        """The reorder must not change the not-found path."""
        registry, _ = await _registry_with_form()
        client = await _make_client(aiohttp_client, registry)

        resp = await client.delete("/api/v1/forms/00000000-0000-0000-0000-000000000000")

        assert resp.status == 404
