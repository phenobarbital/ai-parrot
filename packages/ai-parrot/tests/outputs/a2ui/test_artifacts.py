"""Core-side tests for RenderedArtifact/DeepLink + bake dep hygiene (TASK-1728)."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot.outputs.a2ui import baking
from parrot.outputs.a2ui.artifacts import DeepLink, RenderedArtifact
from parrot.outputs.a2ui.models import Component, CreateSurface


class TestRenderedArtifact:
    def test_model_fields_match_spec(self):
        art = RenderedArtifact(
            artifact_id="a1",
            mime_type="application/pdf",
            content=b"%PDF",
            filename="out.pdf",
            title="Report",
            surface="pdf",
        )
        assert art.source_envelope_ref is None
        assert art.deep_links == []
        assert art.metadata == {}

    def test_content_xor_path_enforced(self):
        with pytest.raises(ValueError):
            RenderedArtifact(
                artifact_id="a1",
                mime_type="text/html",
                filename="x",
                title="t",
                surface="ssr_html",
            )  # neither
        with pytest.raises(ValueError):
            RenderedArtifact(
                artifact_id="a1",
                mime_type="text/html",
                content=b"x",
                path=Path("/tmp/x"),
                filename="x",
                title="t",
                surface="ssr_html",
            )  # both

    def test_deep_link_model(self):
        dl = DeepLink(
            action_label="Approve",
            url="https://x/resume?token=abc",
            token_id="abc",
            expires_at=datetime.now(timezone.utc),
        )
        assert dl.token_id == "abc"

    async def test_source_envelope_persisted_via_artifact_store(self):
        store = AsyncMock()
        envelope = CreateSurface(
            surfaceId="main",
            catalogId="https://parrot.dev/catalogs/v1",
            components=[Component(id="blk-0", component="Card")],
        )
        ref = await baking.persist_envelope(
            envelope,
            store,
            user_id="u",
            agent_id="a",
            session_id="s",
            artifact_id="fixed-id",
        )
        assert ref == "fixed-id"
        store.save_artifact.assert_awaited_once()
        kwargs = store.save_artifact.await_args.kwargs
        assert kwargs["artifact"].artifact_id == "fixed-id"

    def test_bake_missing_jsonpointer_raises_actionable_error(self, monkeypatch):
        def _boom():
            raise ImportError("no jsonpointer")

        monkeypatch.setattr(baking, "_import_jsonpointer", _boom)
        envelope = CreateSurface(
            surfaceId="main",
            catalogId="c",
            components=[
                Component(id="b", component="Chart", properties={"d": {"$bind": "/x"}})
            ],
            dataModel={"x": 1},
        )
        with pytest.raises(ImportError) as exc:
            baking.bake_envelope(envelope)
        assert "ai-parrot-visualizations[a2ui]" in str(exc.value)

    def test_baking_module_imports_without_satellite(self):
        # Importing the module must not require jsonpointer (G8).
        import importlib

        importlib.import_module("parrot.outputs.a2ui.baking")
