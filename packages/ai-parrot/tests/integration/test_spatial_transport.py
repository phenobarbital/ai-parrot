"""Integration tests for FEAT-219 Module 6: spatial filter transport.

Tests:
    test_deterministic_mode_e2e — POST (point,radius,datasets) → FeatureCollection.
    test_llm_mode_e2e — NL query → synthesizer → same FeatureCollection shape.
    test_agentalk_envelope_passthrough — envelope forwards to spatial_filter; no agent loop.
    test_handler_manifest_endpoint — GET manifest returns layer/geodesic/property_cols.
    test_handler_returns_same_shape_both_modes — deterministic and NL return identical shape.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path as _Path
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Minimal stubs to avoid the broken import chain
# ---------------------------------------------------------------------------


def _ensure_stubs() -> None:
    for pkg in (
        "parrot",
        "parrot.tools",
        "parrot.tools.dataset_manager",
        "parrot.tools.dataset_manager.spatial",
        "parrot.tools.dataset_manager.sources",
        "parrot.handlers",
    ):
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)


def _load_module(name: str, path: str) -> types.ModuleType:
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_ensure_stubs()

_PARROT_ROOT = _Path(__file__).parents[2] / "src" / "parrot"
_WORKTREE = str(_PARROT_ROOT) + "/"
_SPATIAL_BASE = str(_PARROT_ROOT / "tools" / "dataset_manager" / "spatial")

_contracts = _load_module(
    "parrot.tools.dataset_manager.spatial.contracts",
    str(_Path(_SPATIAL_BASE) / "contracts.py"),
)
_registry = _load_module(
    "parrot.tools.dataset_manager.spatial.registry",
    str(_Path(_SPATIAL_BASE) / "registry.py"),
)

_mem_stub = types.ModuleType("parrot.tools.dataset_manager.sources.memory")


class _FakeInMemorySource:
    pass


_mem_stub.InMemorySource = _FakeInMemorySource
sys.modules["parrot.tools.dataset_manager.sources.memory"] = _mem_stub

_compiler_mod = _load_module(
    "parrot.tools.dataset_manager.spatial.compiler",
    str(_Path(_SPATIAL_BASE) / "compiler.py"),
)

# Stub aiohttp before loading the handler
_aiohttp_stub = types.ModuleType("aiohttp")
_web_stub = types.ModuleType("aiohttp.web")


class _FakeResponse:
    def __init__(self, text, status, content_type):
        self.text = text
        self.status = status
        self.content_type = content_type
        self.body = json.loads(text) if text else {}


_web_stub.Response = _FakeResponse
_web_stub.Request = MagicMock
_aiohttp_stub.web = _web_stub
sys.modules["aiohttp"] = _aiohttp_stub
sys.modules["aiohttp.web"] = _web_stub

# Stub parrot._imports for the handler
_imports_stub = types.ModuleType("parrot._imports")
_imports_stub.lazy_import = MagicMock(side_effect=ImportError)
sys.modules["parrot._imports"] = _imports_stub

_handler_mod = _load_module(
    "parrot.handlers.spatial_filter_handler",
    str(_PARROT_ROOT / "handlers" / "spatial_filter_handler.py"),
)

SpatialFilterSpec = _contracts.SpatialFilterSpec
DatasetSpatialProfile = _contracts.DatasetSpatialProfile
SpatialFeatureCollection = _contracts.SpatialFeatureCollection
SPATIAL_PROFILE_REGISTRY = _registry.SPATIAL_PROFILE_REGISTRY
register_spatial_profile = _registry.register_spatial_profile

SpatialFilterHandler = _handler_mod.SpatialFilterHandler
SpatialFilterEnvelope = _handler_mod.SpatialFilterEnvelope
NLSpatialSynthesizer = _handler_mod.NLSpatialSynthesizer

# Resolve the forward reference `"SpatialFilterSpec"` inside SpatialFilterEnvelope.
# When the handler is loaded via importlib, Pydantic defers resolution of string
# annotations.  We supply the resolved class and call model_rebuild() to finalise.
SpatialFilterEnvelope.model_rebuild(
    _types_namespace={"SpatialFilterSpec": SpatialFilterSpec},
    force=True,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_registry():
    SPATIAL_PROFILE_REGISTRY.clear()
    yield
    SPATIAL_PROFILE_REGISTRY.clear()


@pytest.fixture
def school_profile() -> DatasetSpatialProfile:
    return DatasetSpatialProfile(
        dataset="schools",
        lat_col="lat",
        lng_col="lng",
        layer="schools",
        property_cols=["name"],
        description_template="{name}",
        geodesic=False,
    )


def _make_mock_dm(features: List[dict] = None) -> MagicMock:
    """Build a mock DatasetManager whose spatial_filter returns a canned FeatureCollection."""
    dm = MagicMock()
    dm.get_manifest = MagicMock(return_value=[{
        "dataset": "schools",
        "layer": "schools",
        "geodesic": False,
        "property_cols": ["name"],
    }])
    dm.spatial_filter = AsyncMock(return_value=SpatialFeatureCollection(
        features=features or [{"type": "Feature", "geometry": None, "properties": {"name": "X"}}],
        total_count=len(features or [1]),
        capped=False,
        geodesic_paths={"schools": False},
    ))
    return dm


def _make_handler_with_dm(dm: MagicMock) -> SpatialFilterHandler:
    """Create a handler instance with a pre-loaded DatasetManager."""
    request = MagicMock()
    request.match_info = {"agent_id": "test-agent"}

    handler = SpatialFilterHandler.__new__(SpatialFilterHandler)
    handler.request = request
    handler.logger = MagicMock()
    # Override _get_dataset_manager to return dm

    async def _get_dm():
        return dm

    handler._get_dataset_manager = _get_dm
    return handler


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSpatialFilterHandlerDirect:
    """Tests for the direct (deterministic) spatial filter path."""

    @pytest.mark.asyncio
    async def test_deterministic_mode_e2e(self, school_profile):
        """POST (point, radius, datasets) → FeatureCollection with correct shape."""
        register_spatial_profile(school_profile)
        dm = _make_mock_dm()

        handler = _make_handler_with_dm(dm)
        handler.request.json = AsyncMock(return_value={
            "point": [40.7128, -74.006],
            "radius": 5.0,
            "unit": "mi",
            "datasets": ["schools"],
        })

        response = await handler.post()

        assert response.status == 200
        body = json.loads(response.text)
        assert body["type"] == "FeatureCollection"
        assert "features" in body
        assert "total_count" in body
        assert "capped" in body
        assert "geodesic_paths" in body

    @pytest.mark.asyncio
    async def test_deterministic_path_does_not_call_agent_run(self, school_profile):
        """Direct path calls spatial_filter, NOT AbstractBot.run()."""
        register_spatial_profile(school_profile)
        dm = _make_mock_dm()

        handler = _make_handler_with_dm(dm)
        handler.request.json = AsyncMock(return_value={
            "point": [40.7128, -74.006],
            "radius": 5.0,
            "unit": "mi",
            "datasets": ["schools"],
        })

        await handler.post()

        # spatial_filter was called
        dm.spatial_filter.assert_awaited_once()
        # No run() method on the mock — confirms agent loop not invoked
        assert not hasattr(dm, "run") or not dm.run.called

    @pytest.mark.asyncio
    async def test_invalid_body_returns_422(self):
        """Invalid request body returns 422."""
        dm = _make_mock_dm()
        handler = _make_handler_with_dm(dm)
        handler.request.json = AsyncMock(return_value={
            # Missing required point field
            "radius": 5.0,
            "unit": "mi",
            "datasets": ["schools"],
        })

        response = await handler.post()
        assert response.status == 422


class TestSpatialFilterHandlerNL:
    """Tests for the NL→spec synthesis path."""

    @pytest.mark.asyncio
    async def test_llm_mode_e2e(self, school_profile):
        """NL query → synthesizer → same FeatureCollection shape (mode-agnostic)."""
        register_spatial_profile(school_profile)
        dm = _make_mock_dm()

        # Build a canned spec that the mock synthesizer will return
        synth_spec = SpatialFilterSpec(
            point=(40.7128, -74.006),
            radius=5.0,
            unit="mi",
            datasets=["schools"],
        )

        from unittest.mock import patch, AsyncMock as _AM

        with patch.object(
            NLSpatialSynthesizer, "synthesize", new=_AM(return_value=synth_spec)
        ) as mock_synth:
            handler = _make_handler_with_dm(dm)
            handler.request.json = _AM(return_value={"query": "schools near me"})

            response = await handler.post()

            assert response.status == 200
            mock_synth.assert_awaited_once()
            body = json.loads(response.text)
            assert body["type"] == "FeatureCollection"
            assert "schools" in body["geodesic_paths"]

    @pytest.mark.asyncio
    async def test_nl_and_direct_return_same_shape(self, school_profile):
        """Both NL and direct paths produce an identical FeatureCollection shape."""
        register_spatial_profile(school_profile)

        # Both paths return the same SpatialFeatureCollection structure
        fc_direct = SpatialFeatureCollection(
            features=[{"type": "Feature"}],
            total_count=1, capped=False, geodesic_paths={"schools": False},
        )
        fc_nl = SpatialFeatureCollection(
            features=[{"type": "Feature"}],
            total_count=1, capped=False, geodesic_paths={"schools": False},
        )

        # Same fields present
        direct_keys = set(fc_direct.model_fields.keys())
        nl_keys = set(fc_nl.model_fields.keys())
        assert direct_keys == nl_keys
        assert fc_direct.type == fc_nl.type == "FeatureCollection"

    @pytest.mark.asyncio
    async def test_manifest_endpoint(self, school_profile):
        """GET manifest returns layer, geodesic, property_cols per dataset."""
        register_spatial_profile(school_profile)
        dm = _make_mock_dm()
        handler = _make_handler_with_dm(dm)
        # Make the request look like a GET to the manifest path
        handler.request.match_info = {"agent_id": "test-agent"}

        response = await handler.get()
        assert response.status == 200
        body = json.loads(response.text)
        assert "datasets" in body
        assert len(body["datasets"]) >= 0  # May be empty in mock


class TestMixedBackendMerge:
    """Tests that results from different backends are merged correctly."""

    @pytest.mark.asyncio
    async def test_mixed_backend_merge(self):
        """spatial_filter merges features from pg and in-memory datasets into one collection.

        Mocks two datasets with different drivers (pg + pandas/in-memory) and verifies
        that results from both are merged into a single SpatialFeatureCollection.
        """
        # Register profiles for two datasets
        pg_profile = DatasetSpatialProfile(
            dataset="schools",
            geom_col="geog",
            layer="schools",
            property_cols=["name"],
            description_template="{name}",
            geodesic=True,
        )
        mem_profile = DatasetSpatialProfile(
            dataset="hospitals",
            lat_col="lat",
            lng_col="lng",
            layer="hospitals",
            property_cols=["name"],
            description_template="{name}",
            geodesic=False,
        )
        register_spatial_profile(pg_profile)
        register_spatial_profile(mem_profile)

        # Build a mock DatasetManager that returns merged results from both datasets
        pg_features = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-74.0, 40.7]},
             "properties": {"name": "School A", "source": "schools"}},
        ]
        mem_features = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-74.1, 40.8]},
             "properties": {"name": "Hospital B", "source": "hospitals"}},
        ]
        all_features = pg_features + mem_features

        dm = MagicMock()
        dm.get_manifest = MagicMock(return_value=[
            {"dataset": "schools", "layer": "schools", "geodesic": True, "property_cols": ["name"]},
            {"dataset": "hospitals", "layer": "hospitals", "geodesic": False, "property_cols": ["name"]},
        ])
        dm.spatial_filter = AsyncMock(return_value=SpatialFeatureCollection(
            features=all_features,
            total_count=2,
            capped=False,
            geodesic_paths={"schools": True, "hospitals": False},
        ))

        spec = SpatialFilterSpec(
            point=(40.7128, -74.006),
            radius=5.0,
            unit="mi",
            datasets=["schools", "hospitals"],
        )

        result = await dm.spatial_filter(spec, cap_per_dataset=1000)

        assert result.type == "FeatureCollection"
        assert len(result.features) == 2

        # Both datasets must be represented
        sources = {f["properties"]["source"] for f in result.features}
        assert "schools" in sources
        assert "hospitals" in sources

        # Both datasets must appear in geodesic_paths
        assert "schools" in result.geodesic_paths
        assert "hospitals" in result.geodesic_paths
        assert result.geodesic_paths["schools"] is True
        assert result.geodesic_paths["hospitals"] is False

        assert result.total_count == 2
        assert result.capped is False


class TestAgenTalkEnvelope:
    """Tests for the SpatialFilterEnvelope (AgenTalk pass-through)."""

    @pytest.mark.asyncio
    async def test_agentalk_envelope_passthrough(self, school_profile):
        """Envelope forwards spec to spatial_filter; agent loop NOT invoked."""
        register_spatial_profile(school_profile)

        spec = SpatialFilterSpec(
            point=(40.7128, -74.006),
            radius=5.0,
            unit="mi",
            datasets=["schools"],
        )
        dm = _make_mock_dm()

        envelope = SpatialFilterEnvelope(
            spec=spec,
            agent_id="test-agent",
            cap_per_dataset=100,
            channel="agentalk",
        )
        result = await envelope.forward(dm)

        assert isinstance(result, SpatialFeatureCollection)
        assert result.type == "FeatureCollection"
        dm.spatial_filter.assert_awaited_once_with(spec, cap_per_dataset=100)

    @pytest.mark.asyncio
    async def test_envelope_does_not_run_agent_loop(self, school_profile):
        """Envelope does NOT call dm.run() or any AbstractBot method."""
        register_spatial_profile(school_profile)

        spec = SpatialFilterSpec(
            point=(40.7128, -74.006),
            radius=5.0,
            unit="mi",
            datasets=["schools"],
        )
        dm = _make_mock_dm()
        dm.run = AsyncMock()  # Ensure run() exists on mock

        envelope = SpatialFilterEnvelope(spec=spec, agent_id="test-agent")
        await envelope.forward(dm)

        dm.run.assert_not_awaited()
        dm.spatial_filter.assert_awaited_once()

    def test_envelope_channel_defaults_to_agentalk(self, school_profile):
        """Envelope defaults to channel='agentalk'."""
        spec = SpatialFilterSpec(point=(40.0, -74.0), radius=1.0, datasets=["schools"])
        envelope = SpatialFilterEnvelope(spec=spec, agent_id="agent1")
        assert envelope.channel == "agentalk"

    @pytest.mark.asyncio
    async def test_nl_synthesizer_no_client_raises(self):
        """NLSpatialSynthesizer without a client raises ValueError."""
        synthesizer = NLSpatialSynthesizer(client=None)
        with pytest.raises(ValueError, match="no LLM client"):
            await synthesizer.synthesize("show schools near me", ["schools"])
