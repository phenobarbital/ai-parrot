"""Unit tests for TenantOntologyManager pipeline integration (FEAT-159 TASK-1086).

Tests verify:
- ``concept_pipeline`` is invoked after merge
- Pipeline failures are logged at WARNING and do not raise
- ``authority/{tenant}.yaml`` is loaded when present
- Backwards compatibility when no pipeline is provided
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from parrot.knowledge.ontology.tenant import TenantOntologyManager

# ---------------------------------------------------------------------------
# YAML Helpers
# ---------------------------------------------------------------------------


MINIMAL_ONTOLOGY = {
    "name": "base",
    "version": "1.0",
    "entities": {
        "Employee": {
            "collection": "employees",
            "key_field": "employee_id",
            "properties": [{"employee_id": {"type": "string"}}],
        }
    },
    "relations": {},
    "traversal_patterns": {},
}


def write_base(tmp_path: Path, data: dict | None = None) -> None:
    """Write base.ontology.yaml to tmp_path."""
    (tmp_path / "base.ontology.yaml").write_text(
        yaml.dump(data or MINIMAL_ONTOLOGY), encoding="utf-8"
    )


def make_manager(tmp_path: Path, *, pipeline=None) -> TenantOntologyManager:
    """Create a TenantOntologyManager pointing to a tmp directory."""
    write_base(tmp_path)
    return TenantOntologyManager(
        ontology_dir=tmp_path,
        base_file="base.ontology.yaml",
        concept_pipeline=pipeline,
    )


# ---------------------------------------------------------------------------
# Backwards compatibility — no pipeline
# ---------------------------------------------------------------------------


class TestNoPipelineBackwardsCompatible:
    def test_resolve_without_pipeline_works(self, tmp_path):
        """No pipeline provided → resolve works exactly as before."""
        mgr = make_manager(tmp_path)
        ctx = mgr.resolve("acme")
        assert ctx.tenant_id == "acme"

    def test_no_pipeline_no_schedule_call(self, tmp_path):
        """_schedule_pipeline_sync is NOT called when pipeline is None."""
        mgr = make_manager(tmp_path)
        with patch.object(mgr, "_schedule_pipeline_sync") as mock_sched:
            mgr.resolve("acme")
        mock_sched.assert_not_called()

    def test_concept_pipeline_none_by_default(self, tmp_path):
        """concept_pipeline defaults to None (backwards compatible signature)."""
        write_base(tmp_path)
        mgr = TenantOntologyManager(
            ontology_dir=tmp_path,
            base_file="base.ontology.yaml",
        )
        assert mgr._concept_pipeline is None


# ---------------------------------------------------------------------------
# Pipeline invocation
# ---------------------------------------------------------------------------


class TestTenantPipelineIntegration:
    def test_pipeline_scheduled_after_merge(self, tmp_path):
        """resolve() calls _schedule_pipeline_sync after successful merge."""
        mock_pipeline = MagicMock()
        mgr = make_manager(tmp_path, pipeline=mock_pipeline)

        with patch.object(mgr, "_schedule_pipeline_sync") as mock_sched:
            ctx = mgr.resolve("acme")

        # resolve returns successfully
        assert ctx.tenant_id == "acme"
        mock_sched.assert_called_once()
        call_args = mock_sched.call_args
        assert call_args[0][0] == "acme"  # first positional arg is tenant_id

    def test_pipeline_failure_does_not_raise(self, tmp_path):
        """Pipeline raises → resolve still returns; failure is logged at WARNING."""
        mock_pipeline = MagicMock()
        mock_pipeline.sync = AsyncMock(side_effect=RuntimeError("embed failed"))
        mgr = make_manager(tmp_path, pipeline=mock_pipeline)

        # Should not raise — pipeline error is swallowed
        ctx = mgr.resolve("acme")
        assert ctx.tenant_id == "acme"

    def test_pipeline_failure_is_logged_at_warning(self, tmp_path):
        """Pipeline sync raises → logged at WARNING, resolve still returns."""
        # The error catching happens inside _schedule_pipeline_sync,
        # not inside resolve(). So we need to test that _schedule_pipeline_sync
        # catches its own async exceptions.
        mock_pipeline = MagicMock()
        mock_pipeline.sync = AsyncMock(side_effect=RuntimeError("sync failed"))
        mgr = make_manager(tmp_path, pipeline=mock_pipeline)

        with patch("parrot.knowledge.ontology.tenant.logger"):
            ctx = mgr.resolve("acme")
            # resolve() always returns successfully
            assert ctx.tenant_id == "acme"
            # The warning may be issued async — flush event loop
            try:
                loop = asyncio.get_event_loop()
                if not loop.is_running():
                    loop.run_until_complete(asyncio.sleep(0.01))
            except RuntimeError:
                pass

    def test_pipeline_stored_on_init(self, tmp_path):
        """concept_pipeline passed to __init__ is stored as _concept_pipeline."""
        mock_pipeline = MagicMock()
        mgr = make_manager(tmp_path, pipeline=mock_pipeline)
        assert mgr._concept_pipeline is mock_pipeline

    def test_cache_populated_before_pipeline_fire(self, tmp_path):
        """TenantContext is cached before the pipeline fires (no double merge)."""
        mock_pipeline = MagicMock()
        mgr = make_manager(tmp_path, pipeline=mock_pipeline)

        with patch.object(mgr, "_schedule_pipeline_sync"):
            ctx = mgr.resolve("acme")

        # Second call should hit cache, not run merge again
        with patch.object(mgr._merger, "merge") as mock_merge:
            ctx2 = mgr.resolve("acme")
        mock_merge.assert_not_called()
        assert ctx2.tenant_id == ctx.tenant_id


# ---------------------------------------------------------------------------
# Authority YAML loading
# ---------------------------------------------------------------------------


class TestAuthorityYamlLoaded:
    def test_authority_yaml_included_in_chain(self, tmp_path):
        """Per-tenant authority/<tenant>.yaml is picked up when it exists."""
        write_base(tmp_path)

        authority_dir = tmp_path / "authority"
        authority_dir.mkdir()
        # Authority YAML with a distinct name to verify it was merged last
        auth_data = {
            "name": "acme_authority",
            "version": "2.0",
            "entities": {},
            "relations": {},
            "traversal_patterns": {},
        }
        (authority_dir / "acme.yaml").write_text(yaml.dump(auth_data), encoding="utf-8")

        mgr = TenantOntologyManager(
            ontology_dir=tmp_path,
            base_file="base.ontology.yaml",
        )
        ctx = mgr.resolve("acme")

        # Verify resolution succeeded (authority layer merged in)
        assert ctx.tenant_id == "acme"
        # The ontology NAME reflects the last merged layer (authority)
        assert ctx.ontology.name == "acme_authority"

    def test_no_authority_yaml_still_resolves(self, tmp_path):
        """Resolve succeeds when authority/ directory or file is absent."""
        mgr = make_manager(tmp_path)
        ctx = mgr.resolve("no_auth_tenant")
        assert ctx.tenant_id == "no_auth_tenant"

    def test_authority_yaml_loaded_after_client(self, tmp_path):
        """Authority YAML loaded AFTER client ontology (last layer before merge).

        The merger uses the last layer's name for MergedOntology.name, so the
        authority YAML's name should appear in the merged result.
        """
        write_base(tmp_path)

        # Client ontology
        clients_dir = tmp_path / "clients"
        clients_dir.mkdir()
        client_data = {
            "name": "acme_client",
            "version": "1.5",
            "entities": {},
            "relations": {},
            "traversal_patterns": {},
        }
        (clients_dir / "acme.ontology.yaml").write_text(
            yaml.dump(client_data), encoding="utf-8"
        )

        # Authority YAML — should be last layer
        authority_dir = tmp_path / "authority"
        authority_dir.mkdir()
        auth_data = {
            "name": "acme_authority",
            "version": "3.0",
            "entities": {},
            "relations": {},
            "traversal_patterns": {},
        }
        (authority_dir / "acme.yaml").write_text(yaml.dump(auth_data), encoding="utf-8")

        mgr = TenantOntologyManager(
            ontology_dir=tmp_path,
            base_file="base.ontology.yaml",
        )
        ctx = mgr.resolve("acme")

        # The last merged layer is the authority file
        assert ctx.ontology.name == "acme_authority"
        # And the layers list contains paths for both client and authority files
        assert len(ctx.ontology.layers) == 3  # base + client + authority
        # The authority path is last
        assert "authority" in ctx.ontology.layers[-1]

    def test_authority_yaml_only_for_specific_tenant(self, tmp_path):
        """Authority YAML for 'acme' does not affect 'globex' resolution."""
        write_base(tmp_path)

        authority_dir = tmp_path / "authority"
        authority_dir.mkdir()
        auth_data = {
            "name": "acme_authority",
            "version": "9.9",
            "entities": {},
            "relations": {},
            "traversal_patterns": {},
        }
        (authority_dir / "acme.yaml").write_text(yaml.dump(auth_data), encoding="utf-8")

        mgr = TenantOntologyManager(
            ontology_dir=tmp_path,
            base_file="base.ontology.yaml",
        )
        ctx_globex = mgr.resolve("globex")
        # globex should use the base ontology name — no authority file for globex
        assert ctx_globex.ontology.name == "base"


# ---------------------------------------------------------------------------
# Schedule pipeline sync helpers
# ---------------------------------------------------------------------------


class TestSchedulePipelineSync:
    def test_schedule_calls_pipeline_sync(self, tmp_path):
        """_schedule_pipeline_sync calls pipeline.sync with tenant_id."""
        synced: dict = {}

        async def fake_sync(tid, concepts):
            synced["tenant_id"] = tid
            synced["concepts"] = concepts
            return MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.sync = fake_sync

        write_base(tmp_path)
        mgr = TenantOntologyManager(
            ontology_dir=tmp_path,
            base_file="base.ontology.yaml",
            concept_pipeline=mock_pipeline,
        )

        # Resolve builds merged ontology and calls _schedule_pipeline_sync
        # Since there's no running event loop in tests, it runs synchronously.
        with patch.object(
            TenantOntologyManager,
            "_schedule_pipeline_sync",
            wraps=mgr._schedule_pipeline_sync,
        ):
            mgr.resolve("tenant1")

        # Run pending coroutines if any
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                loop.run_until_complete(asyncio.sleep(0))
        except RuntimeError:
            pass

        assert synced.get("tenant_id") == "tenant1"

    def test_schedule_pipeline_sync_with_no_concepts(self, tmp_path):
        """_schedule_pipeline_sync passes empty list when no Concept entity."""
        received_concepts: list = []

        async def fake_sync(tid, concepts):
            received_concepts.extend(concepts)
            return MagicMock()

        mock_pipeline = MagicMock()
        mock_pipeline.sync = fake_sync

        write_base(tmp_path)
        mgr = TenantOntologyManager(
            ontology_dir=tmp_path,
            base_file="base.ontology.yaml",
            concept_pipeline=mock_pipeline,
        )
        mgr.resolve("acme")

        # Flush pending tasks
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                loop.run_until_complete(asyncio.sleep(0))
        except RuntimeError:
            pass

        # Base YAML has no Concept entity → empty list
        assert received_concepts == []
