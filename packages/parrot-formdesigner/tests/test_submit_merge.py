"""Unit tests for submit_data() merge_partials integration (TASK-1250).

Tests the optional ?merge_partials=true path in FormAPIHandler.submit_data().
All dependencies (registry, validator, store, storage) are mocked.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.partial import PartialFormData
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.validators import FormValidator, ValidationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_form(form_id: str = "test-form") -> FormSchema:
    return FormSchema(
        form_id=form_id,
        title="Test Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
                    FormField(field_id="age", field_type=FieldType.INTEGER, label="Age"),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
                ],
            )
        ],
    )


def _make_partial(
    form_id: str = "test-form",
    session_id: str = "sess-1",
    data: dict | None = None,
) -> PartialFormData:
    now = datetime.now(tz=timezone.utc)
    return PartialFormData(
        form_id=form_id,
        session_id=session_id,
        data=data or {},
        field_errors={},
        saved_at=now,
        expires_at=now + timedelta(seconds=3600),
    )


def _make_validation_result(is_valid: bool = True, data: dict | None = None) -> ValidationResult:
    return ValidationResult(
        is_valid=is_valid,
        errors={} if is_valid else {"name": ["Required"]},
        sanitized_data=data or {},
    )


def _make_request(
    form_id: str = "test-form",
    session_id: str | None = "sess-1",
    body: dict | None = None,
    merge_partials: bool = False,
) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_id": form_id}

    # Query params
    query_val = "true" if merge_partials else ""
    req.query = MagicMock()
    req.query.get = MagicMock(
        side_effect=lambda key, default="": query_val if key == "merge_partials" else default
    )

    # Session
    if session_id is not None:
        req.__contains__ = lambda self, key: key == "session"
        req.__getitem__ = lambda self, key: {"id": session_id} if key == "session" else None
    else:
        req.__contains__ = lambda self, key: False

    # Body
    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))

    return req


def _make_handler(
    form: FormSchema | None = None,
    partial_store: PartialSaveStore | None = None,
    validation_result: ValidationResult | None = None,
) -> FormAPIHandler:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)

    handler = FormAPIHandler(
        registry=registry,
        partial_store=partial_store,
    )

    if validation_result is not None:
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate = AsyncMock(return_value=validation_result)

    return handler


# ---------------------------------------------------------------------------
# TestSubmitMergePartials
# ---------------------------------------------------------------------------


class TestSubmitMergePartials:
    """Tests for merge_partials integration in submit_data()."""

    async def test_merge_combines_cached_and_submitted(self):
        """Cached partial merged with submitted data before validation."""
        form = _make_form()
        cached = _make_partial(data={"name": "Alice", "age": 30})
        store = MagicMock(spec=PartialSaveStore)
        store.get = AsyncMock(return_value=cached)
        store.delete = AsyncMock(return_value=True)

        # Capture data passed to validator
        captured_data: dict = {}

        async def fake_validate(frm, data, **kw):
            captured_data.update(data)
            return _make_validation_result(data=data)

        handler = _make_handler(form=form, partial_store=store)
        handler.validator.validate = fake_validate

        req = _make_request(
            body={"email": "alice@example.com"},
            merge_partials=True,
        )

        await handler.submit_data(req)

        # Validator should have received merged data
        assert "name" in captured_data
        assert "age" in captured_data
        assert "email" in captured_data

    async def test_merge_submitted_overrides_cached(self):
        """Submitted values take precedence over cached values."""
        form = _make_form()
        cached = _make_partial(data={"name": "Alice", "age": 25})
        store = MagicMock(spec=PartialSaveStore)
        store.get = AsyncMock(return_value=cached)
        store.delete = AsyncMock(return_value=True)

        captured_data: dict = {}

        async def fake_validate(frm, data, **kw):
            captured_data.update(data)
            return _make_validation_result(data=data)

        handler = _make_handler(form=form, partial_store=store)
        handler.validator.validate = fake_validate

        # Submit with a different age — should override cached age=25
        req = _make_request(
            body={"name": "Alice", "age": 30},
            merge_partials=True,
        )

        await handler.submit_data(req)

        assert captured_data["age"] == 30

    async def test_merge_cleanup_after_submit(self):
        """Cached partial deleted after successful submit."""
        form = _make_form()
        cached = _make_partial(data={"name": "Alice"})
        store = MagicMock(spec=PartialSaveStore)
        store.get = AsyncMock(return_value=cached)
        store.delete = AsyncMock(return_value=True)

        handler = _make_handler(
            form=form,
            partial_store=store,
            validation_result=_make_validation_result(data={"name": "Alice"}),
        )

        req = _make_request(body={"name": "Alice"}, merge_partials=True)
        await handler.submit_data(req)

        store.delete.assert_called_once_with("test-form", "sess-1")

    async def test_no_merge_flag_unchanged(self):
        """Without ?merge_partials=true, PartialSaveStore.get is never called."""
        form = _make_form()
        store = MagicMock(spec=PartialSaveStore)
        store.get = AsyncMock(return_value=None)

        handler = _make_handler(
            form=form,
            partial_store=store,
            validation_result=_make_validation_result(data={"name": "Bob"}),
        )

        req = _make_request(body={"name": "Bob"}, merge_partials=False)
        await handler.submit_data(req)

        store.get.assert_not_called()
        store.delete.assert_not_called()

    async def test_merge_no_cached_data(self):
        """When no cached partial exists, proceed with submitted data only."""
        form = _make_form()
        store = MagicMock(spec=PartialSaveStore)
        store.get = AsyncMock(return_value=None)
        store.delete = AsyncMock(return_value=False)

        captured_data: dict = {}

        async def fake_validate(frm, data, **kw):
            captured_data.update(data)
            return _make_validation_result(data=data)

        handler = _make_handler(form=form, partial_store=store)
        handler.validator.validate = fake_validate

        req = _make_request(body={"name": "Charlie"}, merge_partials=True)
        await handler.submit_data(req)

        # Only submitted data — nothing was merged from cached (cached was None)
        assert captured_data == {"name": "Charlie"}
        # delete is still called as cleanup (idempotent — returns False since nothing existed)
        store.delete.assert_called_once_with("test-form", "sess-1")

    async def test_merge_no_store_configured(self):
        """If partial_store is None, merge is skipped silently."""
        form = _make_form()
        captured_data: dict = {}

        async def fake_validate(frm, data, **kw):
            captured_data.update(data)
            return _make_validation_result(data=data)

        handler = _make_handler(form=form, partial_store=None)
        handler.validator.validate = fake_validate

        req = _make_request(body={"name": "Dave"}, merge_partials=True)
        resp = await handler.submit_data(req)

        # Should succeed normally without merge
        assert resp.status == 200
        assert captured_data == {"name": "Dave"}

    async def test_merge_no_session_id_skips_merge(self):
        """When session_id is missing, merge is skipped silently."""
        form = _make_form()
        store = MagicMock(spec=PartialSaveStore)
        store.get = AsyncMock(return_value=None)

        captured_data: dict = {}

        async def fake_validate(frm, data, **kw):
            captured_data.update(data)
            return _make_validation_result(data=data)

        handler = _make_handler(form=form, partial_store=store)
        handler.validator.validate = fake_validate

        req = _make_request(body={"name": "Eve"}, session_id=None, merge_partials=True)
        resp = await handler.submit_data(req)

        assert resp.status == 200
        # merge was skipped — get never called
        store.get.assert_not_called()

    async def test_submit_returns_200_on_success(self):
        """submit_data returns 200 with submission_id on success."""
        form = _make_form()
        handler = _make_handler(
            form=form,
            validation_result=_make_validation_result(data={"name": "Alice"}),
        )
        req = _make_request(body={"name": "Alice"}, merge_partials=False)

        resp = await handler.submit_data(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert "submission_id" in body
        assert body["is_valid"] is True

    async def test_delete_not_called_on_validation_failure(self):
        """Cached partial NOT deleted when validation fails."""
        form = _make_form()
        cached = _make_partial(data={"name": "Alice"})
        store = MagicMock(spec=PartialSaveStore)
        store.get = AsyncMock(return_value=cached)
        store.delete = AsyncMock(return_value=True)

        # Validation fails
        handler = _make_handler(
            form=form,
            partial_store=store,
            validation_result=_make_validation_result(is_valid=False),
        )

        req = _make_request(body={"name": "Alice"}, merge_partials=True)
        resp = await handler.submit_data(req)

        assert resp.status == 422
        store.delete.assert_not_called()
