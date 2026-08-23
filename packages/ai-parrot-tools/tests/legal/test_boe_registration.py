"""Registration + resolution tests for the BOE datasource (TASK-2374)."""
import inspect
from datetime import UTC, datetime

from parrot_loaders.extractors.factory import DataSourceFactory


class TestBOERegistration:
    def test_import_registers_source(self):
        import parrot_tools.legal.boe  # noqa: F401

        src = DataSourceFactory().get("boe", {})
        assert type(src).__name__ == "BOEDataSource"

    def test_sync_boe_is_async(self):
        from parrot_tools.legal.boe import sync_boe

        assert inspect.iscoroutinefunction(sync_boe)

    def test_no_scheduler_dependency(self):
        """The legal toolkit must not depend on the ai-parrot-server satellite."""
        import parrot_tools.legal.boe.sync as m

        src = inspect.getsource(m)
        assert "from parrot.scheduler" not in src
        assert "import parrot.scheduler" not in src

    def test_sync_boe_signature(self):
        from parrot_tools.legal.boe import sync_boe

        sig = inspect.signature(sync_boe)
        assert list(sig.parameters) == ["tenant_id", "since"]
        assert sig.parameters["since"].default is None

    async def test_sync_boe_passes_legal_domain(self, monkeypatch):
        """sync_boe must pass domain="legal" to OntologyRefreshPipeline.run."""
        from parrot.knowledge.ontology.refresh import RefreshReport
        from parrot_tools.legal.boe import sync_boe

        captured: dict = {}

        class _FakePipeline:
            def __init__(self, **kwargs):
                captured["init_kwargs"] = kwargs

            async def run(self, tenant_id, domain=None):
                captured["tenant_id"] = tenant_id
                captured["domain"] = domain
                return RefreshReport(
                    tenant=tenant_id,
                    started_at=datetime.now(UTC),
                )

        monkeypatch.setattr(
            "parrot_tools.legal.boe.sync.OntologyRefreshPipeline", _FakePipeline
        )

        report = await sync_boe("legal_civil")

        assert isinstance(report, RefreshReport)
        assert captured["tenant_id"] == "legal_civil"
        assert captured["domain"] == "legal"
        assert captured["init_kwargs"]["vector_store"] is None
        assert captured["init_kwargs"]["source_configs"] == {"boe": {"since": None}}
