"""Unit tests for FormRegistry public-toggle callback (FEAT-241 M6).

Tests cover:
- False→True transition invokes callback
- True→False transition invokes callback
- No change in is_public does NOT invoke callback
- Deleting a public form invokes callback with False
- Deleting a private form does NOT invoke callback
- No callback set: no error in register/unregister
"""
import pytest
from unittest.mock import AsyncMock
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.core.schema import FormSchema


@pytest.fixture
def registry():
    return FormRegistry(require_tenant=False)


@pytest.fixture
def public_form():
    return FormSchema(form_id="contact", title="Contact", sections=[], is_public=True)


@pytest.fixture
def private_form():
    return FormSchema(form_id="contact", title="Contact", sections=[], is_public=False)


@pytest.mark.asyncio
class TestPublicToggleOnRegister:
    async def test_false_to_true_invokes_callback(self, registry, public_form):
        callback = AsyncMock()
        registry.set_public_toggle_callback(callback)
        await registry.register(public_form)
        callback.assert_awaited_once_with("contact", True)

    async def test_true_to_false_invokes_callback(self, registry, public_form, private_form):
        callback = AsyncMock()
        registry.set_public_toggle_callback(callback)
        await registry.register(public_form)
        callback.reset_mock()
        await registry.register(private_form)
        callback.assert_awaited_once_with("contact", False)

    async def test_no_change_no_callback_false_false(self, registry, private_form):
        """False → False: no callback."""
        callback = AsyncMock()
        registry.set_public_toggle_callback(callback)
        await registry.register(private_form)
        # is_public started as False (default for new entry), still False
        callback.assert_not_awaited()

    async def test_no_change_no_callback_true_true(self, registry, public_form):
        """True → True: no callback on second register."""
        callback = AsyncMock()
        registry.set_public_toggle_callback(callback)
        await registry.register(public_form)
        callback.reset_mock()
        await registry.register(public_form)  # same is_public=True
        callback.assert_not_awaited()

    async def test_no_callback_no_error(self, registry, public_form):
        """No callback set: register must not raise."""
        await registry.register(public_form)

    async def test_callback_set_via_setter(self, registry, public_form):
        """set_public_toggle_callback stores the callback."""
        callback = AsyncMock()
        registry.set_public_toggle_callback(callback)
        assert registry._public_toggle_callback is callback


@pytest.mark.asyncio
class TestPublicToggleOnUnregister:
    async def test_delete_public_form_invokes_callback(self, registry, public_form):
        callback = AsyncMock()
        await registry.register(public_form)
        registry.set_public_toggle_callback(callback)
        await registry.unregister("contact")
        callback.assert_awaited_once_with("contact", False)

    async def test_delete_private_form_no_callback(self, registry, private_form):
        callback = AsyncMock()
        await registry.register(private_form)
        registry.set_public_toggle_callback(callback)
        await registry.unregister("contact")
        callback.assert_not_awaited()

    async def test_delete_nonexistent_form_no_callback(self, registry):
        """Unregistering a form that doesn't exist: no callback, returns False."""
        callback = AsyncMock()
        registry.set_public_toggle_callback(callback)
        result = await registry.unregister("nonexistent")
        assert result is False
        callback.assert_not_awaited()

    async def test_no_callback_no_error_on_unregister(self, registry, public_form):
        """No callback set: unregister must not raise."""
        await registry.register(public_form)
        await registry.unregister("contact")


@pytest.mark.asyncio
class TestToggleCallbackFailureSafety:
    async def test_callback_failure_does_not_raise(self, registry, public_form):
        """A failing callback must be caught and logged, not re-raised."""
        async def bad_callback(form_id: str, is_public: bool) -> None:
            raise RuntimeError("Auth service unreachable")

        registry.set_public_toggle_callback(bad_callback)
        # Must not raise
        await registry.register(public_form)
