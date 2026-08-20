"""Regression tests for the FEAT-300 code-review fixes (C1, C2, H1–H5, M1–M3).

Each test class maps to one finding from the pre-merge review:

- C1 — SQL injection guard on QuestionBankService identifiers.
- C2 — DELETE /forms/{id} blocked (409) when the form has responses.
- H1 — version history survives a process restart (storage reconstruction).
- H3 — storage failures during publish propagate (no silent in-memory fallback).
- H4 — concurrent-publish unique violation surfaces as ValueError.
- H5 — safe_delete uses the public registry API.
- M1 — PUT/PATCH cannot clobber published_version.
- M2 — formula placeholder HTML-escapes field_id and title.
- M5 — backfill propagates storage errors instead of reporting changed=0.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from parrot_formdesigner.api._utils import _bump_version
from parrot_formdesigner.core.schema import FormField, FormSchema
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.services.form_version import FormVersionService
from parrot_formdesigner.services.question_bank import QuestionBankService
from parrot_formdesigner.services.registry import FormRegistry, FormStorage

from tests.unit.test_api_feat300 import _make_form, _make_handler, _make_request


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class InMemoryStorage(FormStorage):
    """Dict-backed FormStorage honoring UNIQUE(form_uid, version) (FEAT-389).

    Rekeyed from form_id to form_uid to mirror the production
    PostgresFormStorage rekey (TASK-1974) — FormVersionService now calls
    load/save/delete with form_uid, and save() must key by the same
    identity or get_published()/list_versions() would never find what
    publish() just wrote.
    """

    def __init__(self) -> None:
        # (tenant, form_uid) → {version: FormSchema}; insertion order = save order
        self._rows: dict[tuple[str, str], dict[str, FormSchema]] = {}

    async def save(self, form: FormSchema, style=None, *, tenant=None) -> str:
        """UPSERT semantics (FEAT-433 TASK-2269): mirrors production's
        ``ON CONFLICT (form_uid, version) DO UPDATE`` — a duplicate
        ``(form_uid, version)`` overwrites, it does NOT raise. This double
        used to raise here, making it STRICTER than ``PostgresFormStorage``
        (the divergence Module 6 exists to close). ``publish()`` no longer
        uses this path at all (it uses :meth:`promote`), so ``save()`` now
        exclusively serves the editor's legitimate "rewrite a draft in
        place" path, which production also just overwrites."""
        versions = self._rows.setdefault((tenant, form.form_uid), {})
        versions[form.version] = form.model_copy(deep=True)
        return form.form_uid

    async def promote(self, form_uid, version, schema_json, *, tenant=None) -> bool:
        """Guarded promote (FEAT-433 Module 6) — mirrors
        ``PostgresFormStorage._promote_sql()``'s upsert-with-conditionally-
        skipped-update: a version with no existing row is written normally
        (the form's very first publish — nothing published yet to
        protect); a version whose existing row is ALREADY published is
        rejected (the guard). Aligns this double with production for the
        write path ``publish()`` actually uses."""
        versions = self._rows.setdefault((tenant, form_uid), {})
        existing = versions.get(version)
        if existing is not None and existing.published_version == version:
            return False
        versions[version] = FormSchema.model_validate_json(schema_json)
        return True

    async def load(self, form_uid, version=None, *, tenant=None):
        versions = self._rows.get((tenant, form_uid), {})
        if not versions:
            return None
        if version is not None:
            snap = versions.get(version)
            return snap.model_copy(deep=True) if snap else None
        latest = list(versions.values())[-1]
        return latest.model_copy(deep=True)

    async def delete(self, form_uid, *, tenant=None) -> bool:
        return self._rows.pop((tenant, form_uid), None) is not None

    async def list_forms(self, *, tenant=None) -> list[dict[str, Any]]:
        return [
            {"form_uid": fuid, "version": list(v.keys())[-1], "tenant": t}
            for (t, fuid), v in self._rows.items()
            if t == tenant
        ]

    async def list_versions(self, form_uid, *, tenant=None) -> list[dict[str, Any]]:
        """FEAT-433 Module 2 — mirrors PostgresFormStorage.list_versions()'s
        projected-dict shape so FormVersionService.list_versions() (which now
        calls this instead of probing) can reconstruct history from this
        double the same way it would from real Postgres."""
        versions = self._rows.get((tenant, form_uid), {})
        return [
            {
                "version": version,
                "created_at": snap.created_at,
                "updated_at": snap.created_at,
                "form_id": snap.form_id,
                "published_version": snap.published_version,
                "published_at": (snap.meta or {}).get("published_at"),
            }
            for version, snap in versions.items()
        ]


class FailingStorage(InMemoryStorage):
    """Storage whose save/promote/list always fail — simulates an
    unreachable DB. promote() is overridden too (FEAT-433 TASK-2269):
    publish() now writes via promote(), not save() — without this
    override, test_storage_failure_propagates would hit InMemoryStorage's
    inherited (successful) promote() instead of a simulated failure."""

    async def save(self, form, style=None, *, tenant=None) -> str:
        raise ConnectionError("database unreachable")

    async def promote(self, form_uid, version, schema_json, *, tenant=None) -> bool:
        raise ConnectionError("database unreachable")

    async def list_forms(self, *, tenant=None):
        raise ConnectionError("database unreachable")


# FEAT-389: fixed default so two independent calls to _registry_with_form()
# (e.g. simulating a process restart against the same underlying storage in
# TestH1) can refer to "the same conceptual form" via a shared form_uid —
# _make_form() alone would generate a fresh random UUID each call.
_FIXED_FORM_UID = "22222222-2222-2222-2222-222222222222"


async def _registry_with_form(
    form_id: str = "f1", tenant: str = "t1", form_uid: str = _FIXED_FORM_UID
) -> tuple[FormRegistry, FormSchema]:
    registry = FormRegistry()
    # model_copy(update=...) bypasses Pydantic validation/coercion — pass a
    # real uuid.UUID so the registry's primary index (keyed by
    # FormSchema.form_uid, uuid.UUID since FEAT-393) actually matches.
    form = _make_form(form_id, tenant).model_copy(
        update={"form_uid": uuid.UUID(form_uid)}
    )
    await registry.register(form, tenant=tenant)
    return registry, form


# ---------------------------------------------------------------------------
# C1 — SQL injection guard
# ---------------------------------------------------------------------------


class TestC1IdentifierValidation:
    def test_malicious_tenant_rejected(self):
        with pytest.raises(ValueError, match="Invalid tenant"):
            QuestionBankService(None, tenant='public"; DROP TABLE epson.field_bank; --')

    def test_malicious_table_rejected(self):
        with pytest.raises(ValueError, match="Invalid table"):
            QuestionBankService(None, tenant="t1", table="field_bank; DROP TABLE x")

    def test_valid_identifiers_quoted(self):
        svc = QuestionBankService(None, tenant="t1", table="field_bank")
        assert svc._qualified == '"t1"."field_bank"'


# ---------------------------------------------------------------------------
# C2 — delete_form blocked when responses exist
# ---------------------------------------------------------------------------


class TestC2DeleteGuard:
    async def test_delete_blocked_with_responses(self):
        registry, form = await _registry_with_form()

        async def has_responses(form_uid: str, tenant: str) -> bool:
            return True

        handler = _make_handler(registry)
        handler._version_service = FormVersionService(
            registry, has_responses=has_responses
        )

        resp = await handler.delete_form(
            _make_request(method="DELETE", form_uid=form.form_uid)
        )
        assert resp.status == 409
        assert await registry.get(form.form_uid, tenant="t1") is not None  # untouched

    async def test_delete_allowed_without_responses(self):
        registry, form = await _registry_with_form()

        async def has_responses(form_uid: str, tenant: str) -> bool:
            return False

        handler = _make_handler(registry)
        handler._version_service = FormVersionService(
            registry, has_responses=has_responses
        )

        resp = await handler.delete_form(
            _make_request(method="DELETE", form_uid=form.form_uid)
        )
        assert resp.status == 204


# ---------------------------------------------------------------------------
# H1 — version history survives restart
# ---------------------------------------------------------------------------


class TestH1HistorySurvivesRestart:
    async def test_list_versions_reconstructed_from_storage(self):
        storage = InMemoryStorage()
        registry, form = await _registry_with_form()
        svc = FormVersionService(registry, storage=storage)

        v1 = await svc.publish(form.form_uid, tenant="t1")  # promotes "1.0" in place

        # FEAT-433 Q5: publish() no longer bumps — an editor SAVE is what
        # produces a new draft to publish next (mirrors the real PUT/PATCH
        # handler: bump the version, write directly to storage).
        live = await registry.get(form.form_uid, tenant="t1")
        bumped = live.model_copy(deep=True, update={"version": _bump_version(live.version)})
        await storage.save(bumped, tenant="t1")
        await registry.register(bumped, overwrite=True, tenant="t1")

        v2 = await svc.publish(form.form_uid, tenant="t1")  # promotes the new draft
        assert v2 != v1

        # Simulate process restart: fresh service, same storage, empty _meta.
        # registry2's form shares the same fixed form_uid default as
        # registry's form (FEAT-389) — the storage rekey is what history
        # reconstruction actually depends on.
        registry2, _form2 = await _registry_with_form()
        svc2 = FormVersionService(registry2, storage=storage)

        versions = [
            m.version for m in await svc2.list_versions(form.form_uid, tenant="t1")
        ]
        assert versions == [v1, v2]

    async def test_published_at_recovered_from_stamp(self):
        storage = InMemoryStorage()
        registry, form = await _registry_with_form()
        svc = FormVersionService(registry, storage=storage)
        await svc.publish(form.form_uid, tenant="t1")

        svc2 = FormVersionService(FormRegistry(), storage=storage)
        metas = await svc2.list_versions(form.form_uid, tenant="t1")
        assert metas and metas[0].published_at is not None


# ---------------------------------------------------------------------------
# H3 / H4 — storage failures during publish
# ---------------------------------------------------------------------------


class TestH3H4PublishStorageFailures:
    async def test_storage_failure_propagates(self):
        """H3: a publish that cannot persist must NOT report success."""
        registry, form = await _registry_with_form()
        svc = FormVersionService(registry, storage=FailingStorage())

        with pytest.raises(ConnectionError):
            await svc.publish(form.form_uid, tenant="t1")

    async def test_publish_twice_without_edit_raises_frozen_error(self):
        """H4, reshaped by FEAT-433 Q5 (promote in place): re-publishing an
        already-published version (no editor save in between — so there is
        no new draft to promote, just the same already-frozen row) raises
        ValueError and leaves the stored row byte-identical. The old
        version of this test simulated a TOCTOU race assuming publish()
        bumps to a NEW tag each time; that assumption no longer holds — the
        guard below is the same guard, it just fires on a plain re-publish
        now, since that alone is enough to hit an already-published row."""
        storage = InMemoryStorage()
        registry, form = await _registry_with_form()
        svc = FormVersionService(registry, storage=storage)
        await svc.publish(form.form_uid, tenant="t1")  # promotes form.version

        stored_before = storage._rows[("t1", form.form_uid)][form.version].model_dump_json()

        with pytest.raises(ValueError, match="already exists and is frozen"):
            await svc.publish(form.form_uid, tenant="t1")

        stored_after = storage._rows[("t1", form.form_uid)][form.version].model_dump_json()
        assert stored_after == stored_before  # byte-identical — not overwritten

    async def test_promote_guard_rejects_already_published_row_directly(self):
        """The storage-level promote() guard — not just the service's
        (non-atomic) fast-path pre-check — is the atomic immutability
        guard: it rejects re-promoting an already-published row even when
        called directly, and leaves the row byte-identical."""
        storage = InMemoryStorage()
        registry, form = await _registry_with_form()
        svc = FormVersionService(registry, storage=storage)
        await svc.publish(form.form_uid, tenant="t1")

        stored_before = storage._rows[("t1", form.form_uid)][form.version].model_dump_json()

        promoted_again = await storage.promote(
            form.form_uid, form.version, stored_before, tenant="t1"
        )

        assert promoted_again is False
        stored_after = storage._rows[("t1", form.form_uid)][form.version].model_dump_json()
        assert stored_after == stored_before

    async def test_inmemory_double_matches_postgres_contract(self):
        """The InMemoryStorage double and PostgresFormStorage agree on
        duplicate-key behavior for BOTH write paths (Module 6): save()
        overwrites a duplicate (form_uid, version) — matching
        PostgresFormStorage._upsert_sql's ON CONFLICT DO UPDATE — while
        promote() (tested directly above) rejects re-promoting an
        already-published row. The double used to be stricter than
        production only on the first half; this closes that gap."""
        storage = InMemoryStorage()
        registry, form = await _registry_with_form()

        await storage.save(form, tenant="t1")
        edited = form.model_copy(deep=True, update={"title": "Edited"})
        await storage.save(edited, tenant="t1")  # same (form_uid, version) — must NOT raise

        loaded = await storage.load(form.form_uid, version=form.version, tenant="t1")
        assert str(loaded.title) == "Edited"


# ---------------------------------------------------------------------------
# H5 — safe_delete via public registry API
# ---------------------------------------------------------------------------


class TestH5PublicRegistryApi:
    async def test_safe_delete_unregisters_via_public_api(self):
        registry, form = await _registry_with_form()
        svc = FormVersionService(registry)

        await svc.safe_delete(form.form_uid, tenant="t1")
        assert await registry.get(form.form_uid, tenant="t1") is None


# ---------------------------------------------------------------------------
# M1 — published_version immutable through PUT/PATCH
# ---------------------------------------------------------------------------


class TestM1PublishedVersionImmutable:
    async def _published_handler(self):
        registry = FormRegistry()
        form = _make_form().model_copy(
            deep=True, update={"published_version": "1.0"}
        )
        await registry.register(form, tenant="t1")
        return _make_handler(registry), registry, form

    async def test_put_cannot_clear_published_version(self):
        handler, registry, form = await self._published_handler()
        # FEAT-389: PUT requires body["form_uid"] == the URL's form_uid — use
        # the SAME registered form's dump, not a freshly-generated one (which
        # would have a different random form_uid and get rejected 400).
        body = form.model_dump(mode="json")
        body["published_version"] = None  # attempted unfreeze

        resp = await handler.update_form(
            _make_request(method="PUT", form_uid=form.form_uid, body=body)
        )
        assert resp.status == 200
        assert json.loads(resp.body)["published_version"] == "1.0"

    async def test_patch_cannot_clear_published_version(self):
        handler, registry, form = await self._published_handler()

        resp = await handler.patch_form(
            _make_request(
                method="PATCH",
                form_uid=form.form_uid,
                body={"published_version": None},
            )
        )
        assert resp.status == 200
        assert json.loads(resp.body)["published_version"] == "1.0"


# ---------------------------------------------------------------------------
# FEAT-389 code-review fix — PUT rename cannot steal another form's slug
# ---------------------------------------------------------------------------


class TestPutRenameSlugCollision:
    """register()'s slug-uniqueness check must fire for ANY register() call
    with a DIFFERENT form_uid than the slug's current owner — not just when
    overwrite=False. PUT (update_form) always calls register(overwrite=True),
    which used to skip the check entirely, letting a rename silently steal
    another form's slug and corrupt both forms' index state."""

    async def test_put_rename_to_other_forms_slug_returns_409(self) -> None:
        registry = FormRegistry()
        victim = _make_form("victim-slug", "t1")
        await registry.register(victim, tenant="t1")
        renamer = _make_form("renamer-slug", "t1")
        await registry.register(renamer, tenant="t1")

        handler = _make_handler(registry)
        body = renamer.model_dump(mode="json")
        body["form_id"] = "victim-slug"  # attempt to steal victim's slug

        resp = await handler.update_form(
            _make_request(method="PUT", form_uid=renamer.form_uid, body=body)
        )

        assert resp.status == 409
        # Neither form's state was corrupted by the rejected rename.
        assert (await registry.get_by_slug("victim-slug", tenant="t1")).form_uid == victim.form_uid
        assert (await registry.get_by_slug("renamer-slug", tenant="t1")).form_uid == renamer.form_uid

    async def test_put_rename_to_free_slug_still_succeeds(self) -> None:
        """The fix must not block legitimate renames to an unclaimed slug."""
        registry = FormRegistry()
        form = _make_form("old-slug", "t1")
        await registry.register(form, tenant="t1")

        handler = _make_handler(registry)
        body = form.model_dump(mode="json")
        body["form_id"] = "new-free-slug"

        resp = await handler.update_form(
            _make_request(method="PUT", form_uid=form.form_uid, body=body)
        )

        assert resp.status == 200
        assert await registry.get_by_slug("old-slug", tenant="t1") is None
        renamed = await registry.get_by_slug("new-free-slug", tenant="t1")
        assert renamed is not None and renamed.form_uid == form.form_uid


# ---------------------------------------------------------------------------
# M2 — formula placeholder escapes HTML
# ---------------------------------------------------------------------------


class TestM2FormulaEscaping:
    def test_field_id_and_expression_escaped(self):
        field = FormField(
            field_id='x" onmouseover="alert(1)',
            field_type=FieldType.FORMULA,
            label="XSS",
            meta={"expression": '"><script>alert(1)</script>'},
        )
        html_out = HTML5Renderer()._render_formula_placeholder(field)
        assert "<script>" not in html_out
        assert 'onmouseover="alert' not in html_out
        assert "&quot;" in html_out or "&gt;" in html_out


# ---------------------------------------------------------------------------
# M5 — backfill propagates storage errors
# ---------------------------------------------------------------------------


class TestM5BackfillStorageErrors:
    async def test_backfill_raises_when_storage_unreachable(self):
        registry = FormRegistry()  # nothing in-memory to backfill
        svc = FormVersionService(registry, storage=FailingStorage())

        with pytest.raises(ConnectionError):
            await svc.backfill_published(tenant="t1")
