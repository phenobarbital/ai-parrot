"""ThalesRunner — public Python API for the "Thales" research flow (FEAT-425 Module 5).

Two-phase execution (spec §2): phase 1 runs the planner standalone (its
output — the angle count — determines phase 2's graph shape); phase 2
assembles the run's ``AgentsFlow`` (see ``definition.py`` for why this is
programmatic rather than ``FlowDefinition``-driven) and executes it with
``checkpoint=True`` (FEAT-399). Owns persistence: every artifact through
``ArtifactStore``, mirrored to ``output_dir``, indexed in ``manifest.json``,
and aggregated into ``ThalesResult``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from navconfig.logging import logging

from parrot.bots.flows.core.context import FlowContext
from parrot.clients.factory import LLMFactory
from parrot.flows.thales.definition import ThalesNodeDeps, assemble_thales_flow
from parrot.flows.thales.factories import DEFAULT_DEEP_RESEARCH_LLM
from parrot.flows.thales.models import (
    ArtifactRef,
    Bibliography,
    ResearchAngle,
    ResearchDeck,
    ThalesConfig,
    ThalesResult,
)
from parrot.flows.thales.nodes import PlannerNode
from parrot.flows.thales.nodes.deck_builder import DROPPED_DECK_SENTINEL
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.models import Artifact, ArtifactType
from parrot.tools.infographic_toolkit import InfographicToolkit


class ThalesRunner:
    """Public Python API for one "Thales" research run.

    Args:
        thesis: The thesis statement to research.
        num_decks: Minimum number of research angles/decks (``ThalesConfig``
            enforces ``ge=10``, no upper cap).
        sources: Research sources to enable. Defaults to
            ``["web", "deep_research", "arxiv"]``.
        output_dir: Optional filesystem directory to mirror every artifact
            (deck JSON, slide HTML, final document, manifest.json) into.
        artifact_store: Optional ``ArtifactStore`` for persistence + public
            URLs. When ``None``, persistence is skipped (refs carry no
            ``artifact_id``/``url``) — only ``output_dir`` mirroring and the
            in-memory ``ThalesResult`` remain available.
        llm: ``"provider:model"`` string for the planner/slide-spec/deep-
            research client. Defaults to Google (spec §2).
        infographic_toolkit: Optional pre-configured ``InfographicToolkit``
            (with its templates already registered). When ``None``, the
            infographic step degrades to ``None`` (spec: infographic is
            ``Optional`` on ``ThalesResult``).
        infographic_template: Template name to pass to
            ``InfographicToolkit.render_template``.
        user_id: Owning user identifier for persistence.
        agent_id: Agent identifier for persistence.
        session_id: Session identifier for persistence (defaults to a
            fresh UUID).
        per_node_timeout: Optional per-research-node timeout, in seconds.
        max_paragraphs_per_finding: Cap on extracted paragraphs per finding.
    """

    def __init__(
        self,
        thesis: str,
        *,
        num_decks: int = 10,
        sources: Optional[List[str]] = None,
        output_dir: Optional[Path] = None,
        artifact_store: Optional[ArtifactStore] = None,
        llm: Optional[str] = None,
        infographic_toolkit: Optional[InfographicToolkit] = None,
        infographic_template: str = "crew_report",
        user_id: str = "thales",
        agent_id: str = "thales",
        session_id: Optional[str] = None,
        per_node_timeout: Optional[float] = None,
        max_paragraphs_per_finding: int = 6,
        **kwargs: Any,
    ) -> None:
        self.config = ThalesConfig(
            thesis=thesis,
            num_decks=num_decks,
            sources=sources or ["web", "deep_research", "arxiv"],
            output_dir=output_dir,
            per_node_timeout=per_node_timeout,
            max_paragraphs_per_finding=max_paragraphs_per_finding,
        )
        self.llm = llm or DEFAULT_DEEP_RESEARCH_LLM
        self.artifact_store = artifact_store
        self.infographic_toolkit = infographic_toolkit
        self.infographic_template = infographic_template
        self.user_id = user_id
        self.agent_id = agent_id
        self.session_id = session_id or str(uuid.uuid4())
        self.run_id = str(uuid.uuid4())
        self.logger = logging.getLogger(f"parrot.thales.{self.run_id}")
        self._progress_listeners: List[Callable[[str, str, Dict[str, Any]], Any]] = []

    def add_progress_listener(
        self, callback: Callable[[str, str, Dict[str, Any]], Any],
    ) -> None:
        """Register a callback forwarded every ``AgentsFlow`` node event.

        Args:
            callback: Sync or async callable ``(event, node_id, info)``,
                same contract as ``AgentsFlow.add_node_event_listener``.
        """
        self._progress_listeners.append(callback)

    def _on_node_event(self, event: str, node_id: str, info: Dict[str, Any]) -> None:
        for callback in self._progress_listeners:
            callback(event, node_id, info)

    async def run(self) -> ThalesResult:
        """Run the full two-phase Thales pipeline.

        Returns:
            The aggregated ``ThalesResult``.

        Raises:
            RuntimeError: When every research angle's deck was dropped
                (all sources failed for every angle).
        """
        client = LLMFactory.create(llm=self.llm)

        # Phase 1: planner (standalone — its output shapes phase 2's graph).
        planner_node = PlannerNode(node_id="planner", config=self.config, client=client)
        angles_json = await planner_node.execute(ctx=None, deps={})
        angles = [ResearchAngle.model_validate(item) for item in json.loads(angles_json)]

        projected_calls = len(angles) * len(self.config.sources)
        self.logger.info(
            "Thales run %s: %d angles x %d sources = %d projected research calls",
            self.run_id, len(angles), len(self.config.sources), projected_calls,
        )

        accessed_date = datetime.now(timezone.utc).date().isoformat()
        node_deps = ThalesNodeDeps(
            client=client,
            store=self.artifact_store,
            toolkit=self.infographic_toolkit,
            user_id=self.user_id,
            agent_id=self.agent_id,
            session_id=self.session_id,
            accessed_date=accessed_date,
            title=f"Thales Research Report — {self.config.thesis}",
            output_dir=self.config.output_dir,
        )

        # Phase 2: assemble + run.
        flow = assemble_thales_flow(
            angles, self.config, node_deps,
            flow_id=self.run_id,
            on_node_event=self._on_node_event,
        )
        ctx = FlowContext(initial_task=self.config.thesis, synthesis_client=client)
        flow_result = await flow.run_flow(ctx)

        return await self._build_result(angles, flow_result)

    # ------------------------------------------------------------------
    # Result aggregation + persistence
    # ------------------------------------------------------------------

    async def _build_result(self, angles: List[ResearchAngle], flow_result: Any) -> ThalesResult:
        """Aggregate node outputs + persist artifacts into one ``ThalesResult``."""
        warnings: List[str] = []
        decks: List[ResearchDeck] = []
        slide_refs: List[ArtifactRef] = []

        for angle in angles:
            deck_raw = flow_result.responses.get(f"deck-{angle.angle_id}")
            if deck_raw is None:
                warnings.append(f"Angle {angle.angle_id!r}: deck_builder did not complete.")
                continue
            try:
                payload = json.loads(deck_raw)
            except (TypeError, ValueError):
                warnings.append(f"Angle {angle.angle_id!r}: unparseable deck output.")
                continue
            if isinstance(payload, dict) and payload.get(DROPPED_DECK_SENTINEL):
                warnings.append(
                    f"Angle {angle.angle_id!r}: deck dropped — all sources failed "
                    f"({payload.get('failed_sources')})."
                )
                continue

            deck = ResearchDeck.model_validate(payload)
            decks.append(deck)

            await self._persist(
                kind="deck_json", title=f"Deck — {angle.title}",
                definition={"deck": payload}, artifact_type=ArtifactType.EXPORT,
            )
            self._mirror_to_output_dir(f"deck-{angle.angle_id}.json", deck_raw)

            slide_raw = flow_result.responses.get(f"slide-render-{angle.angle_id}")
            if slide_raw:
                slide_ref = await self._persist(
                    kind="slide_html", title=f"Slide — {angle.title}",
                    definition={"html": slide_raw}, artifact_type=ArtifactType.INTERACTIVE,
                )
                slide_refs.append(slide_ref)
                self._mirror_to_output_dir(f"slide-{angle.angle_id}.html", slide_raw)

        if not decks:
            raise RuntimeError(
                "Thales run aborted: every research angle's deck was dropped "
                "(all sources failed for every angle)."
            )

        executive_summary = flow_result.responses.get("exec_summary", "") or ""

        final_document_ref = ArtifactRef(kind="final_html")
        final_pdf_ref: Optional[ArtifactRef] = None
        final_raw = flow_result.responses.get("final_document")
        if final_raw:
            try:
                final_payload = json.loads(final_raw)
            except (TypeError, ValueError):
                final_payload = {}
            if final_payload.get("final_document"):
                final_document_ref = ArtifactRef.model_validate(final_payload["final_document"])
            if final_payload.get("final_pdf"):
                final_pdf_ref = ArtifactRef.model_validate(final_payload["final_pdf"])
            warnings.extend(final_payload.get("warnings", []))
        else:
            warnings.append("final_document node did not complete.")

        infographic = flow_result.responses.get("infographic")

        bibliography_raw = flow_result.responses.get("bibliography")
        bibliography = (
            Bibliography.model_validate_json(bibliography_raw)
            if bibliography_raw
            else Bibliography()
        )

        result = ThalesResult(
            thesis=self.config.thesis,
            decks=decks,
            slides=slide_refs,
            bibliography=bibliography,
            executive_summary=executive_summary,
            final_document=final_document_ref,
            final_pdf=final_pdf_ref,
            infographic=infographic,
            warnings=warnings,
        )

        manifest_path = self._write_manifest(result)
        if manifest_path is not None:
            result.manifest_path = manifest_path

        return result

    async def _persist(
        self, *, kind: str, title: str, definition: Dict[str, Any], artifact_type: ArtifactType,
    ) -> ArtifactRef:
        """Persist one artifact via the injected ``ArtifactStore``, if any.

        Returns a bare ``ArtifactRef`` (no ``artifact_id``/``url``) when no
        store is configured, or persistence fails — never raises.
        """
        if self.artifact_store is None:
            return ArtifactRef(kind=kind)
        now = datetime.now(timezone.utc)
        artifact_id = f"{self.run_id}-{kind}-{uuid.uuid4().hex[:8]}"
        try:
            artifact = Artifact(
                artifact_id=artifact_id, artifact_type=artifact_type, title=title,
                created_at=now, updated_at=now, definition=definition,
            )
            await self.artifact_store.save_artifact(
                self.user_id, self.agent_id, self.session_id, artifact,
            )
            url = await self.artifact_store.get_public_url(
                self.user_id, self.agent_id, self.session_id, artifact_id,
            )
            return ArtifactRef(kind=kind, artifact_id=artifact_id, url=url)
        except Exception as exc:  # noqa: BLE001 - persistence failures degrade, never abort
            self.logger.warning("Failed to persist %s artifact: %s", kind, exc)
            return ArtifactRef(kind=kind)

    def _mirror_to_output_dir(self, relative_name: str, content: str) -> None:
        """Best-effort mirror of one artifact's content under ``output_dir``."""
        if not self.config.output_dir:
            return
        try:
            directory = Path(self.config.output_dir)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / relative_name).write_text(content, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - mirroring failures degrade, never abort
            self.logger.warning("Failed to mirror %s to output_dir: %s", relative_name, exc)

    def _write_manifest(self, result: ThalesResult) -> Optional[Path]:
        """Best-effort ``manifest.json`` write under ``output_dir``."""
        if not self.config.output_dir:
            return None
        try:
            directory = Path(self.config.output_dir)
            directory.mkdir(parents=True, exist_ok=True)
            manifest_path = directory / "manifest.json"
            manifest_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
            return manifest_path
        except Exception as exc:  # noqa: BLE001 - manifest failures degrade, never abort
            self.logger.warning("Failed to write manifest.json: %s", exc)
            return None
