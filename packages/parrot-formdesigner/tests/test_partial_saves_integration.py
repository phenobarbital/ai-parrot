"""Integration tests for the full partial saves feature (TASK-1252).

Tests the end-to-end partial save lifecycle combining PartialFormData,
PartialSaveStore, FormAPIHandler, and submit_data() merge integration.

All Redis interactions are mocked (no live Redis required). These tests
exercise the full component chain rather than individual units.

Test classes:
- TestPartialSaveLifecycle   — full save → retrieve → submit with merge → cleanup
- TestSessionIsolation       — two sessions, same form, independent data
- TestMergeOnSubmit          — merge override, cleanup after submit
- TestEdgeCases              — empty answers, form not found, no session, no store
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.partial import PartialFormData
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.validators import FormValidator, ValidationResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_form() -> FormSchema:
    """Minimal form schema matching the spec's test fixture."""
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Name",
                        required=True,
                    ),
                    FormField(
                        field_id="age",
                        field_type=FieldType.INTEGER,
                        label="Age",
                        constraints=FieldConstraints(min_value=18, max_value=120),
                    ),
                    FormField(
                        field_id="email",
                        field_type=FieldType.EMAIL,
                        label="Email",
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def in_memory_store() -> "InMemoryPartialStore":
    """A PartialSaveStore backed by an in-memory dict (no Redis needed)."""
    return InMemoryPartialStore(ttl_seconds=3600)


class InMemoryPartialStore(PartialSaveStore):
    """PartialSaveStore backed by an in-memory dict for testing.

    Overrides _get_redis to return a fake Redis-like client that operates
    on a plain dict. This allows integration tests without a live Redis.
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        super().__init__(ttl_seconds=ttl_seconds, redis_url=None)
        self._store: dict[str, str] = {}

    async def _get_redis(self) -> Any:
        """Return a fake in-memory Redis client."""
        return _FakeRedis(self._store)


class _FakeRedis:
    """Minimal fake Redis client backed by a plain dict."""

    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            return 1
        return 0

    async def close(self) -> None:
        pass


def _make_registry(form: FormSchema | None) -> FormRegistry:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    return registry


def _make_request(
    form_id: str = "test-form",
    session_id: str | None = "sess-1",
    body: dict | None = None,
    merge_partials: bool = False,
    method: str = "POST",
) -> MagicMock:
    from aiohttp import web

    req = MagicMock(spec=web.Request)
    req.match_info = {"form_id": form_id}
    req.method = method

    if session_id is not None:
        req.__contains__ = lambda self, key: key == "session"
        req.__getitem__ = lambda self, key: {"id": session_id} if key == "session" else None
    else:
        req.__contains__ = lambda self, key: False

    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))

    query_val = "true" if merge_partials else ""
    req.query = MagicMock()
    req.query.get = MagicMock(
        side_effect=lambda key, default="": query_val if key == "merge_partials" else default
    )

    return req


def _make_valid_result(data: dict) -> ValidationResult:
    return ValidationResult(is_valid=True, errors={}, sanitized_data=data)


# ---------------------------------------------------------------------------
# TestPartialSaveLifecycle
# ---------------------------------------------------------------------------


class TestPartialSaveLifecycle:
    """Full end-to-end partial save lifecycle tests."""

    async def test_full_lifecycle(self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore):
        """Save fields incrementally → retrieve → submit with merge → cleanup."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(
            registry=registry,
            partial_store=in_memory_store,
        )
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate_field = AsyncMock(return_value=[])
        handler.validator.validate = AsyncMock(
            side_effect=lambda frm, data, **kw: _make_valid_result(data)
        )

        # Step 1: save name
        req1 = _make_request(body={"answers": {"name": "Alice"}})
        resp1 = await handler.save_partial(req1)
        assert resp1.status == 200
        body1 = json.loads(resp1.body)
        assert body1["data"]["name"] == "Alice"

        # Step 2: save age (incremental — name should persist)
        req2 = _make_request(body={"answers": {"age": 30}})
        resp2 = await handler.save_partial(req2)
        assert resp2.status == 200
        body2 = json.loads(resp2.body)
        assert body2["data"]["name"] == "Alice"
        assert body2["data"]["age"] == 30

        # Step 3: retrieve
        req3 = _make_request(method="GET")
        resp3 = await handler.get_partial(req3)
        assert resp3.status == 200
        body3 = json.loads(resp3.body)
        assert body3["data"]["name"] == "Alice"
        assert body3["data"]["age"] == 30

        # Step 4: submit with merge (add email in submit, merge with cached)
        req4 = _make_request(body={"email": "alice@example.com"}, merge_partials=True)
        resp4 = await handler.submit_data(req4)
        assert resp4.status == 200

        # Step 5: verify cleanup — partial should be gone
        req5 = _make_request(method="GET")
        resp5 = await handler.get_partial(req5)
        assert resp5.status == 404

    async def test_crash_recovery(self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore):
        """Save partial, simulate disconnect, retrieve within TTL window."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(
            registry=registry,
            partial_store=in_memory_store,
        )
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate_field = AsyncMock(return_value=[])

        # Save partial (simulating user filling out form before crash)
        req_save = _make_request(body={"answers": {"name": "Bob", "age": 25}})
        await handler.save_partial(req_save)

        # Simulate reconnect — use a new handler instance sharing the same store
        handler2 = FormAPIHandler(
            registry=registry,
            partial_store=in_memory_store,
        )
        req_get = _make_request(method="GET")
        resp = await handler2.get_partial(req_get)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["data"]["name"] == "Bob"
        assert body["data"]["age"] == 25

    async def test_delete_clears_partial(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """DELETE /partial removes the cached entry."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(
            registry=registry,
            partial_store=in_memory_store,
        )
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate_field = AsyncMock(return_value=[])

        # Save first
        await handler.save_partial(_make_request(body={"answers": {"name": "Carol"}}))

        # Delete
        resp_del = await handler.delete_partial(_make_request(method="DELETE"))
        assert resp_del.status == 204

        # Get should now return 404
        resp_get = await handler.get_partial(_make_request(method="GET"))
        assert resp_get.status == 404


# ---------------------------------------------------------------------------
# TestSessionIsolation
# ---------------------------------------------------------------------------


class TestSessionIsolation:
    """Tests that different session IDs are fully independent."""

    async def test_two_sessions_independent(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """Two sessions saving to same form have separate data."""
        registry = _make_registry(sample_form)

        handler_a = FormAPIHandler(
            registry=registry, partial_store=in_memory_store
        )
        handler_a.validator = MagicMock(spec=FormValidator)
        handler_a.validator.validate_field = AsyncMock(return_value=[])

        handler_b = FormAPIHandler(
            registry=registry, partial_store=in_memory_store
        )
        handler_b.validator = MagicMock(spec=FormValidator)
        handler_b.validator.validate_field = AsyncMock(return_value=[])

        # Session A saves data
        req_a = _make_request(body={"answers": {"name": "Alice"}}, session_id="session-A")
        await handler_a.save_partial(req_a)

        # Session B saves different data
        req_b = _make_request(body={"answers": {"name": "Bob"}}, session_id="session-B")
        await handler_b.save_partial(req_b)

        # Retrieve session A — should have Alice
        resp_a = await handler_a.get_partial(
            _make_request(method="GET", session_id="session-A")
        )
        assert resp_a.status == 200
        body_a = json.loads(resp_a.body)
        assert body_a["data"]["name"] == "Alice"

        # Retrieve session B — should have Bob (not Alice)
        resp_b = await handler_b.get_partial(
            _make_request(method="GET", session_id="session-B")
        )
        assert resp_b.status == 200
        body_b = json.loads(resp_b.body)
        assert body_b["data"]["name"] == "Bob"

    async def test_delete_one_session_leaves_other_intact(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """Deleting one session's partial does not affect another session."""
        registry = _make_registry(sample_form)

        handler = FormAPIHandler(registry=registry, partial_store=in_memory_store)
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate_field = AsyncMock(return_value=[])

        # Both sessions save data
        await handler.save_partial(
            _make_request(body={"answers": {"x": 1}}, session_id="s-keep")
        )
        await handler.save_partial(
            _make_request(body={"answers": {"x": 2}}, session_id="s-delete")
        )

        # Delete s-delete
        await handler.delete_partial(_make_request(method="DELETE", session_id="s-delete"))

        # s-keep should still be there
        resp = await handler.get_partial(_make_request(method="GET", session_id="s-keep"))
        assert resp.status == 200

        # s-delete should be gone
        resp2 = await handler.get_partial(_make_request(method="GET", session_id="s-delete"))
        assert resp2.status == 404


# ---------------------------------------------------------------------------
# TestMergeOnSubmit
# ---------------------------------------------------------------------------


class TestMergeOnSubmit:
    """Integration tests for the ?merge_partials=true submit path."""

    async def test_merge_combines_data(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """Cached + submitted data merged correctly."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(registry=registry, partial_store=in_memory_store)
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate_field = AsyncMock(return_value=[])

        captured_data: dict = {}

        async def capture_validate(frm, data, **kw):
            captured_data.update(data)
            return _make_valid_result(data)

        handler.validator.validate = capture_validate

        # Cache partial: name + age
        await handler.save_partial(
            _make_request(body={"answers": {"name": "Dave", "age": 22}})
        )

        # Submit with only email — merge should add name+age from cache
        await handler.submit_data(
            _make_request(body={"email": "dave@example.com"}, merge_partials=True)
        )

        assert "name" in captured_data
        assert "age" in captured_data
        assert "email" in captured_data

    async def test_submitted_overrides_cached(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """Overlapping keys: submitted value wins over cached value."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(registry=registry, partial_store=in_memory_store)
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate_field = AsyncMock(return_value=[])

        captured_data: dict = {}

        async def capture_validate(frm, data, **kw):
            captured_data.update(data)
            return _make_valid_result(data)

        handler.validator.validate = capture_validate

        # Cache age=20
        await handler.save_partial(
            _make_request(body={"answers": {"age": 20, "name": "Eve"}})
        )

        # Submit age=25 — should override cached 20
        await handler.submit_data(
            _make_request(body={"age": 25}, merge_partials=True)
        )

        assert captured_data["age"] == 25
        assert captured_data["name"] == "Eve"

    async def test_cleanup_after_submit(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """Cached partial deleted after successful submit."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(registry=registry, partial_store=in_memory_store)
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate_field = AsyncMock(return_value=[])
        handler.validator.validate = AsyncMock(
            side_effect=lambda frm, data, **kw: _make_valid_result(data)
        )

        # Cache some data
        await handler.save_partial(
            _make_request(body={"answers": {"name": "Frank"}})
        )

        # Submit with merge
        await handler.submit_data(
            _make_request(body={"email": "frank@example.com"}, merge_partials=True)
        )

        # Partial should be cleaned up
        resp = await handler.get_partial(_make_request(method="GET"))
        assert resp.status == 404


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case integration tests."""

    async def test_empty_answers(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """Saving empty answers dict stores an empty partial."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(registry=registry, partial_store=in_memory_store)
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate_field = AsyncMock(return_value=[])

        req = _make_request(body={"answers": {}})
        resp = await handler.save_partial(req)

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["data"] == {}

    async def test_form_not_found(self, in_memory_store: InMemoryPartialStore):
        """save_partial returns 404 when form not in registry."""
        registry = _make_registry(form=None)
        handler = FormAPIHandler(registry=registry, partial_store=in_memory_store)

        req = _make_request(body={"answers": {"name": "X"}})
        resp = await handler.save_partial(req)

        assert resp.status == 404

    async def test_no_session_id_returns_400(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """All partial endpoints return 400 when session_id is absent."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(registry=registry, partial_store=in_memory_store)

        # save_partial
        req = _make_request(session_id=None, body={"answers": {}})
        resp = await handler.save_partial(req)
        assert resp.status == 400

        # get_partial
        req2 = _make_request(method="GET", session_id=None)
        resp2 = await handler.get_partial(req2)
        assert resp2.status == 400

        # delete_partial
        req3 = _make_request(method="DELETE", session_id=None)
        resp3 = await handler.delete_partial(req3)
        assert resp3.status == 400

    async def test_no_store_configured(self, sample_form: FormSchema):
        """All partial endpoints return 503 when partial_store is None."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(registry=registry, partial_store=None)

        req = _make_request(body={"answers": {}})
        resp = await handler.save_partial(req)
        assert resp.status == 503

        req2 = _make_request(method="GET")
        resp2 = await handler.get_partial(req2)
        assert resp2.status == 503

        req3 = _make_request(method="DELETE")
        resp3 = await handler.delete_partial(req3)
        assert resp3.status == 503

    async def test_merge_partials_without_store_does_not_break_submit(
        self, sample_form: FormSchema
    ):
        """?merge_partials=true with no store still submits normally."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(registry=registry, partial_store=None)
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate = AsyncMock(
            side_effect=lambda frm, data, **kw: _make_valid_result(data)
        )

        req = _make_request(body={"name": "Grace"}, merge_partials=True)
        resp = await handler.submit_data(req)

        assert resp.status == 200

    async def test_last_write_wins_overwrite(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """Saving the same field twice: second value overwrites first."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(registry=registry, partial_store=in_memory_store)
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate_field = AsyncMock(return_value=[])

        await handler.save_partial(_make_request(body={"answers": {"age": 18}}))
        await handler.save_partial(_make_request(body={"answers": {"age": 30}}))

        resp = await handler.get_partial(_make_request(method="GET"))
        body = json.loads(resp.body)
        assert body["data"]["age"] == 30

    async def test_get_nonexistent_partial_returns_404(
        self, sample_form: FormSchema, in_memory_store: InMemoryPartialStore
    ):
        """GET /partial returns 404 when nothing has been saved."""
        registry = _make_registry(sample_form)
        handler = FormAPIHandler(registry=registry, partial_store=in_memory_store)

        resp = await handler.get_partial(_make_request(method="GET"))
        assert resp.status == 404

    async def test_partial_data_model_json_round_trip(self):
        """PartialFormData round-trips correctly through JSON."""
        now = datetime.now(tz=timezone.utc)
        original = PartialFormData(
            form_id="f1",
            session_id="s1",
            data={"name": "Alice", "nested": {"key": "value"}},
            field_errors={"email": ["Invalid"]},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        restored = PartialFormData.model_validate_json(original.model_dump_json())
        assert restored.form_id == original.form_id
        assert restored.data == original.data
        assert restored.field_errors == original.field_errors
        assert restored.saved_at == original.saved_at
