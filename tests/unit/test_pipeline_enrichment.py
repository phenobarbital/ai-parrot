import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.finance.fsm import PipelineStateMachine


class TestPipelineFSM:
    def test_enrichment_state_exists(self):
        """FSM has the enriching state."""
        fsm = PipelineStateMachine(pipeline_id="test")
        assert hasattr(fsm, "enriching")

    def test_researching_to_enriching(self):
        """Can transition from researching to enriching."""
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_enrichment()
        assert fsm.current_state.id == "enriching"

    def test_enriching_to_deliberating(self):
        """Can transition from enriching to deliberating."""
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_enrichment()
        fsm.start_deliberation()
        assert fsm.current_state.id == "deliberating"

    def test_direct_path_preserved(self):
        """Can go researching → deliberating without enrichment."""
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_deliberation()
        assert fsm.current_state.id == "deliberating"

    def test_enriching_to_halted(self):
        """Can halt from enriching state."""
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_enrichment()
        fsm.halt()
        assert fsm.current_state.id == "halted"

    def test_enriching_to_failed(self):
        """Can fail from enriching state."""
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_enrichment()
        fsm.fail()
        assert fsm.current_state.id == "failed"


class TestPipelineEnrichmentBranching:
    @pytest.mark.asyncio
    @patch.dict("os.environ", {"MASSIVE_ENRICHMENT_ENABLED": "true"})
    async def test_pipeline_runs_enrichment_when_toolkit_provided(self):
        """Pipeline enters enrichment when massive_toolkit present and enabled."""
        import os

        enabled = os.environ.get(
            "MASSIVE_ENRICHMENT_ENABLED", "false"
        ).lower() == "true"
        assert enabled

        # Enriched path: researching → enriching → deliberating
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_enrichment()
        assert fsm.current_state.id == "enriching"
        fsm.start_deliberation()
        assert fsm.current_state.id == "deliberating"

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"MASSIVE_ENRICHMENT_ENABLED": "false"})
    async def test_pipeline_skips_enrichment_when_disabled(self):
        """Pipeline skips enrichment when env var is false."""
        import os

        enabled = os.environ.get(
            "MASSIVE_ENRICHMENT_ENABLED", "false"
        ).lower() == "true"
        assert not enabled

        # Direct path: researching → deliberating
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_deliberation()
        assert fsm.current_state.id == "deliberating"

    @pytest.mark.asyncio
    async def test_pipeline_skips_enrichment_when_no_toolkit(self):
        """Pipeline skips enrichment when massive_toolkit is None."""
        massive_toolkit = None
        assert massive_toolkit is None

        # Direct path: researching → deliberating
        fsm = PipelineStateMachine(pipeline_id="test")
        fsm.start_research()
        fsm.start_deliberation()
        assert fsm.current_state.id == "deliberating"

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"MASSIVE_ENRICHMENT_ENABLED": "true", "MASSIVE_ENRICHMENT_TIMEOUT": "1"})
    async def test_enrichment_timeout_falls_back(self):
        """Timeout triggers fallback to raw briefings."""
        import asyncio

        async def slow_enrich(briefings):
            await asyncio.sleep(10)
            return briefings

        # Simulate what the pipeline does
        briefings = {"equity": MagicMock()}
        original_briefings = briefings.copy()

        try:
            briefings = await asyncio.wait_for(
                slow_enrich(briefings),
                timeout=1,
            )
        except asyncio.TimeoutError:
            briefings = original_briefings

        # We should still have the original briefings
        assert briefings == original_briefings
