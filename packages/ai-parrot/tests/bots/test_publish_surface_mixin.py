"""Unit tests for ``InfographicAuthoringMixin.publish_surface`` (FEAT-492,
TASK-2704).

Mirrors ``tests/unit/bots/test_infographic_authoring_mixin.py``'s
composition idiom (``_AuthoringAgent(InfographicAuthoringMixin,
PandasAgent)``, module-scoped fixture — instantiation is heavy). The
``PgUISurfaceStore`` is always stubbed/injected — no live Postgres, no
dependency on ai-parrot-server actually being importable except for the one
test that exercises the lazy-import guard itself.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.bots.data import PandasAgent
from parrot.bots.mixins import InfographicAuthoringMixin
from parrot.outputs.a2ui.models import CreateSurface


class _AuthoringAgent(InfographicAuthoringMixin, PandasAgent):
    """Test composition: mixin before PandasAgent (cooperative MRO)."""


def _fake_artifact_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    return store


@pytest.fixture(scope="module")
def agent():
    """One composed agent for the whole module (instantiation is heavy)."""
    return _AuthoringAgent(name="reporter", artifact_store=_fake_artifact_store())


@pytest.fixture
def fake_surface_store():
    store = MagicMock()
    store.save = AsyncMock(return_value="surface-1")
    return store


def _sample_envelope(surface_id="surface-1") -> CreateSurface:
    return CreateSurface(
        surfaceId=surface_id,
        components=[],
        dataModel={"filters": {"window": "all"}},
    )


class TestPublishSurfaceInjectedStore:
    async def test_publish_surface_with_injected_store(self, agent, fake_surface_store):
        surface_id = await agent.publish_surface(
            kind="dashboard",
            title="Q3 Revenue",
            envelope=_sample_envelope(),
            surface_store=fake_surface_store,
        )

        assert surface_id == "surface-1"
        fake_surface_store.save.assert_awaited_once()
        record, kwargs = fake_surface_store.save.call_args.args, fake_surface_store.save.call_args.kwargs
        saved_record = record[0]
        # Code-review fix: the row PK is ALWAYS a freshly-minted UUID — never
        # envelope_model.surface_id (a renderer-scoped identifier that is
        # very often not a UUID at all, e.g. every recipe-backed envelope's
        # surfaceId is "{recipe_name}-infographic" — see
        # UISurfaceRecord.surface_id being a Postgres UUID column, TASK-2700).
        assert uuid.UUID(saved_record.surface_id)  # raises ValueError if not a real UUID
        assert saved_record.kind.value == "dashboard"
        assert saved_record.title == "Q3 Revenue"
        assert saved_record.agent_id == "reporter"
        assert saved_record.user_id == "reporter"  # no explicit user_id -> falls back to agent_id
        assert kwargs["overwrite"] is False

    async def test_publish_surface_accepts_instance_and_dict(self, agent, fake_surface_store):
        instance_id = await agent.publish_surface(
            kind="widget",
            title="From instance",
            envelope=_sample_envelope("surface-instance"),
            surface_store=fake_surface_store,
        )
        assert instance_id == "surface-1"  # store stub always returns this
        instance_record = fake_surface_store.save.call_args.args[0]
        # Row PK is a fresh UUID, independent of the envelope's own surfaceId
        # (preserved verbatim INSIDE the stored envelope dump, just below).
        assert uuid.UUID(instance_record.surface_id)
        assert instance_record.envelope["surfaceId"] == "surface-instance"

        dict_envelope = _sample_envelope("surface-dict").model_dump(by_alias=True, mode="json")
        await agent.publish_surface(
            kind="widget",
            title="From dict",
            envelope=dict_envelope,
            surface_store=fake_surface_store,
        )
        dict_record = fake_surface_store.save.call_args.args[0]
        assert uuid.UUID(dict_record.surface_id)
        assert dict_record.envelope == dict_envelope

    async def test_publish_surface_mints_fresh_uuid_even_with_non_uuid_envelope_id(self, agent, fake_surface_store):
        """Regression test (code review CRITICAL finding): a recipe-backed
        envelope's surfaceId is `{recipe_name}-infographic` — NOT a UUID.
        The row PK must always be a real UUID regardless, or `store.save()`
        fails against a real Postgres `UUID` column."""
        recipe_style_envelope = CreateSurface(surfaceId="daily-budget-infographic", components=[], dataModel={})
        await agent.publish_surface(
            kind="dashboard",
            title="Recipe-style id",
            envelope=recipe_style_envelope,
            surface_store=fake_surface_store,
        )
        record = fake_surface_store.save.call_args.args[0]
        assert uuid.UUID(record.surface_id)  # raises ValueError if not a real UUID
        assert record.envelope["surfaceId"] == "daily-budget-infographic"

    async def test_publish_surface_mints_uuid_when_surface_id_absent(self, agent, fake_surface_store):
        envelope_no_id = CreateSurface(surfaceId="", components=[], dataModel={})
        await agent.publish_surface(
            kind="widget",
            title="No id",
            envelope=envelope_no_id,
            surface_store=fake_surface_store,
        )
        record = fake_surface_store.save.call_args.args[0]
        assert uuid.UUID(record.surface_id)

    async def test_publish_surface_derives_recipe_ref_fields(self, agent, fake_surface_store):
        await agent.publish_surface(
            kind="dashboard",
            title="Recipe-backed",
            envelope=_sample_envelope("surface-recipe"),
            recipe_name="daily-budget",
            recipe_owner="reporter",
            recipe_params={"window": "7d"},
            surface_store=fake_surface_store,
        )
        record = fake_surface_store.save.call_args.args[0]
        assert record.recipe_name == "daily-budget"
        assert record.recipe_owner == "reporter"
        assert record.recipe_params == {"window": "7d"}
        assert record.refreshable is True

    async def test_publish_surface_overwrite_flag_forwarded(self, agent, fake_surface_store):
        await agent.publish_surface(
            kind="dashboard",
            title="X",
            envelope=_sample_envelope("surface-overwrite"),
            overwrite=True,
            surface_store=fake_surface_store,
        )
        assert fake_surface_store.save.call_args.kwargs["overwrite"] is True

    async def test_publish_surface_explicit_user_and_session(self, agent, fake_surface_store):
        await agent.publish_surface(
            kind="dashboard",
            title="X",
            envelope=_sample_envelope("surface-user"),
            user_id="alice",
            session_id="sess-9",
            surface_store=fake_surface_store,
        )
        record = fake_surface_store.save.call_args.args[0]
        assert record.user_id == "alice"
        assert record.session_id == "sess-9"


class TestPublishSurfaceStoreResolution:
    async def test_publish_surface_uses_bound_surface_store_attribute(self, agent, fake_surface_store):
        agent._surface_store = fake_surface_store
        try:
            await agent.publish_surface(
                kind="dashboard",
                title="Bound store",
                envelope=_sample_envelope("surface-bound"),
            )
        finally:
            del agent._surface_store
        fake_surface_store.save.assert_awaited_once()

    async def test_publish_surface_missing_store_actionable_error(self, agent, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name == "parrot.handlers.models.ui_surfaces":
                raise ImportError("simulated: ai-parrot-server not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        with pytest.raises(RuntimeError, match="ai-parrot-server"):
            await agent.publish_surface(
                kind="dashboard",
                title="X",
                envelope=_sample_envelope("surface-no-store"),
            )


class TestModuleImportWithoutServerPackage:
    def test_module_import_without_server_package(self):
        """The AC's literal command: the core module imports cleanly on its
        own — no top-level dependency on the server package."""
        result = subprocess.run(
            [sys.executable, "-c", "import parrot.bots.mixins.infographic_authoring"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
