"""Unit tests for FormRegistry and FormStorage."""

import logging
import pytest
from parrot.forms import (
    FieldType,
    FormField,
    FormRegistry,
    FormSchema,
    FormSection,
    FormStorage,
    StyleSchema,
)


@pytest.fixture
def registry():
    """FormRegistry instance (no storage)."""
    return FormRegistry()


@pytest.fixture
def sample_form():
    """Sample FormSchema."""
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(field_id="f", field_type=FieldType.TEXT, label="F")
                ],
            )
        ],
    )


@pytest.fixture
def another_form():
    """Second sample FormSchema."""
    return FormSchema(
        form_id="another-form",
        title="Another Form",
        sections=[
            FormSection(
                section_id="s2",
                fields=[
                    FormField(field_id="g", field_type=FieldType.EMAIL, label="G")
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Mock storage
# ---------------------------------------------------------------------------

class InMemoryStorage(FormStorage):
    """Simple in-memory FormStorage for testing."""

    def __init__(self):
        self._store: dict[str, FormSchema] = {}

    async def save(self, form: FormSchema, style: StyleSchema | None = None) -> str:
        self._store[form.form_id] = form
        return form.form_id

    async def load(self, form_id: str, version: str | None = None) -> FormSchema | None:
        return self._store.get(form_id)

    async def delete(self, form_id: str) -> bool:
        if form_id in self._store:
            del self._store[form_id]
            return True
        return False

    async def list_forms(self) -> list[dict[str, str]]:
        return [
            {"form_id": fid, "title": str(f.title)}
            for fid, f in self._store.items()
        ]


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class TestFormRegistryRegister:
    """Tests for register() and get()."""

    async def test_register_and_get(self, registry, sample_form):
        """Register a form and retrieve it by ID."""
        await registry.register(sample_form)
        result = await registry.get("test-form")
        assert result is not None
        assert result.form_id == "test-form"

    async def test_get_nonexistent(self, registry):
        """Getting an unregistered form returns None."""
        result = await registry.get("nonexistent")
        assert result is None

    async def test_register_multiple(self, registry, sample_form, another_form):
        """Multiple forms can be registered."""
        await registry.register(sample_form)
        await registry.register(another_form)
        forms = await registry.list_forms()
        assert len(forms) == 2

    async def test_overwrite_default_true(self, registry, sample_form):
        """By default, re-registering overwrites the existing entry."""
        await registry.register(sample_form)
        new_form = sample_form.model_copy(update={"title": "Updated"})
        await registry.register(new_form)
        result = await registry.get("test-form")
        assert result.title == "Updated"

    async def test_overwrite_false_keeps_original(self, registry, sample_form):
        """overwrite=False skips if already registered."""
        await registry.register(sample_form)
        new_form = sample_form.model_copy(update={"title": "Should Not Appear"})
        await registry.register(new_form, overwrite=False)
        result = await registry.get("test-form")
        assert result.title == "Test Form"


# ---------------------------------------------------------------------------
# Unregister tests
# ---------------------------------------------------------------------------

class TestFormRegistryUnregister:
    """Tests for unregister()."""

    async def test_unregister(self, registry, sample_form):
        """Unregistering removes the form from the registry."""
        await registry.register(sample_form)
        removed = await registry.unregister("test-form")
        assert removed is True
        result = await registry.get("test-form")
        assert result is None

    async def test_unregister_nonexistent(self, registry):
        """Unregistering a nonexistent form returns False."""
        removed = await registry.unregister("nonexistent")
        assert removed is False


# ---------------------------------------------------------------------------
# List tests
# ---------------------------------------------------------------------------

class TestFormRegistryList:
    """Tests for list_forms() and list_form_ids()."""

    async def test_list_empty(self, registry):
        """Empty registry returns empty list."""
        forms = await registry.list_forms()
        assert forms == []

    async def test_list_forms(self, registry, sample_form, another_form):
        """list_forms() returns all registered forms."""
        await registry.register(sample_form)
        await registry.register(another_form)
        forms = await registry.list_forms()
        ids = [f.form_id for f in forms]
        assert "test-form" in ids
        assert "another-form" in ids

    async def test_list_form_ids(self, registry, sample_form, another_form):
        """list_form_ids() returns all form IDs."""
        await registry.register(sample_form)
        await registry.register(another_form)
        ids = await registry.list_form_ids()
        assert "test-form" in ids
        assert "another-form" in ids

    async def test_contains(self, registry, sample_form):
        """contains() returns True for registered form."""
        await registry.register(sample_form)
        assert await registry.contains("test-form") is True
        assert await registry.contains("other") is False

    async def test_clear(self, registry, sample_form, another_form):
        """clear() removes all forms."""
        await registry.register(sample_form)
        await registry.register(another_form)
        await registry.clear()
        forms = await registry.list_forms()
        assert forms == []


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

class TestFormRegistryPersist:
    """Tests for persist parameter and FormStorage integration."""

    async def test_persist_without_storage_warns(self, registry, sample_form, caplog):
        """persist=True without storage logs a warning but still registers in-memory."""
        with caplog.at_level(logging.WARNING):
            await registry.register(sample_form, persist=True)
        assert "no FormStorage configured" in caplog.text
        result = await registry.get("test-form")
        assert result is not None

    async def test_persist_with_storage(self, sample_form):
        """persist=True delegates to storage backend."""
        storage = InMemoryStorage()
        registry = FormRegistry(storage=storage)
        await registry.register(sample_form, persist=True)
        # Verify it was saved to storage
        saved = await storage.load("test-form")
        assert saved is not None
        assert saved.form_id == "test-form"

    async def test_load_from_storage(self, sample_form, another_form):
        """load_from_storage() hydrates registry from storage."""
        storage = InMemoryStorage()
        await storage.save(sample_form)
        await storage.save(another_form)

        registry = FormRegistry(storage=storage)
        count = await registry.load_from_storage()
        assert count == 2
        assert await registry.get("test-form") is not None
        assert await registry.get("another-form") is not None

    async def test_load_from_storage_no_storage_warns(self, registry, caplog):
        """load_from_storage() without storage logs warning and returns 0."""
        with caplog.at_level(logging.WARNING):
            count = await registry.load_from_storage()
        assert count == 0
        assert "no storage configured" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Callback tests
# ---------------------------------------------------------------------------

class TestFormRegistryCallbacks:
    """Tests for on_register and on_unregister callbacks."""

    async def test_on_register_callback_called(self, registry, sample_form):
        """on_register callback is invoked when a form is registered."""
        received = []

        async def handler(form):
            received.append(form.form_id)

        registry.on_register(handler)
        await registry.register(sample_form)
        assert "test-form" in received

    async def test_on_unregister_callback_called(self, registry, sample_form):
        """on_unregister callback is invoked when a form is unregistered."""
        removed = []

        async def handler(form_id):
            removed.append(form_id)

        registry.on_unregister(handler)
        await registry.register(sample_form)
        await registry.unregister("test-form")
        assert "test-form" in removed
