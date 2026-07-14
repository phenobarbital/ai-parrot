"""Unit tests for PersistenceMixin save-path prompt/tenant enhancement (FEAT-307)."""
import asyncio

import pytest
from unittest.mock import MagicMock

from parrot.bots.flows.core.storage import PersistenceMixin
from parrot.bots.flows.core.storage.backends import ResultStorage


class _FakeStorage(ResultStorage):
    """Recording ResultStorage for tests."""

    def __init__(self) -> None:
        self.saves: list[tuple[str, dict]] = []
        self.closed = False

    async def save(self, collection: str, document: dict) -> None:
        self.saves.append((collection, document))

    async def close(self) -> None:
        self.closed = True


class _Host(PersistenceMixin):
    """Minimal host class that owns the four mixin attributes."""

    name = "TestCrew"

    def __init__(
        self,
        persist: bool = True,
        storage: "ResultStorage | None" = None,
    ) -> None:
        self._persist_results = persist
        self._result_storage_arg = storage
        self._result_storage: "ResultStorage | None" = (
            storage if isinstance(storage, ResultStorage) else None
        )
        self._persist_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


class TestPersistenceMixinSaveEnhancement:
    @pytest.mark.asyncio
    async def test_save_result_includes_tenant_default(self):
        """tenant defaults to 'global' when not provided."""
        fake = _FakeStorage()
        host = _Host(persist=True, storage=fake)

        await host._save_result(MagicMock(to_dict=lambda: {}), "run_flow")

        assert fake.saves[0][1]["tenant"] == "global"

    @pytest.mark.asyncio
    async def test_save_result_includes_tenant_explicit(self):
        """tenant is included when explicitly passed."""
        fake = _FakeStorage()
        host = _Host(persist=True, storage=fake)

        await host._save_result(
            MagicMock(to_dict=lambda: {}), "run_flow", tenant="acme"
        )

        assert fake.saves[0][1]["tenant"] == "acme"

    @pytest.mark.asyncio
    async def test_save_result_includes_prompt(self):
        """prompt is included when passed via kwargs."""
        fake = _FakeStorage()
        host = _Host(persist=True, storage=fake)

        await host._save_result(
            MagicMock(to_dict=lambda: {}), "run_flow", prompt="Analyze trends"
        )

        assert fake.saves[0][1]["prompt"] == "Analyze trends"

    @pytest.mark.asyncio
    async def test_save_result_prompt_none_when_not_provided(self):
        """prompt is absent/None when not provided (backwards compat)."""
        fake = _FakeStorage()
        host = _Host(persist=True, storage=fake)

        await host._save_result(MagicMock(to_dict=lambda: {}), "run_flow")

        assert fake.saves[0][1].get("prompt") is None

    def test_named_columns_includes_tenant_and_prompt(self):
        """_NAMED_COLUMNS frozenset includes tenant and prompt."""
        from parrot.bots.flows.core.storage.backends.postgres import _NAMED_COLUMNS

        assert "tenant" in _NAMED_COLUMNS
        assert "prompt" in _NAMED_COLUMNS
