"""FinalDocumentNode — slides + bibliography -> persisted final document (FEAT-425 Module 3).

Calls TASK-2228's deterministic renderer (``render_document`` /
``rasterize_pdf``) and persists BOTH the HTML and (when weasyprint is
available) the PDF via an injected ``ArtifactStore``. The store, and every
run-scoped identifier this node needs, are injected via the node factory
closure (TASK-2231) — this node never constructs its own store.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Set

from pydantic import Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.thales.models import ArtifactRef, Bibliography
from parrot.flows.thales.nodes.registry import register_thales_node
from parrot.flows.thales.rendering.document import rasterize_pdf, render_document
from parrot.storage.models import Artifact, ArtifactType


@register_thales_node("thales.final_document")
class FinalDocumentNode(Node):
    """Fan-in: rendered slide HTML + bibliography -> persisted final document.

    Args:
        node_id: Unique identifier within the graph.
        store: An ``ArtifactStore`` instance (injected — never constructed here).
        user_id: Owning user identifier for persistence.
        agent_id: Agent identifier for persistence.
        session_id: Session identifier for persistence.
        slide_node_ids: node_ids (in display order) whose ``deps`` value is
            one already-rendered slide HTML fragment (TASK-2228's
            ``render_slide``).
        bibliography_node_id: node_id whose ``deps`` value is the
            JSON-encoded ``Bibliography`` (``BibliographyNode``'s output).
        title: Document title.
        dependencies: Set of node_ids that must complete first.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if ``None``.
    """

    node_id: str
    store: Any
    user_id: str
    agent_id: str
    session_id: str
    slide_node_ids: list[str] = Field(default_factory=list)
    bibliography_node_id: str = "bibliography"
    title: str = "Thales Research Report"
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook (initialises ``self.logger``)."""
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> str:
        """Compose, then persist, the final document (+ optional PDF).

        Args:
            ctx: The current flow execution context (unused directly).
            deps: Mapping keyed by ``slide_node_ids`` (slide HTML) and
                ``bibliography_node_id`` (JSON ``Bibliography``).

        Returns:
            JSON: ``{"final_document": ArtifactRef, "final_pdf":
            ArtifactRef | None, "warnings": [...]}``.
        """
        slides_html = [deps[node_id] for node_id in self.slide_node_ids if node_id in deps]
        bibliography_raw = deps.get(self.bibliography_node_id)
        bibliography = (
            Bibliography.model_validate_json(bibliography_raw)
            if bibliography_raw
            else Bibliography()
        )

        html = await render_document(slides_html, bibliography, title=self.title)

        warnings: list[str] = []
        now = datetime.now(timezone.utc)

        document_ref = await self._persist_html(html, now)

        pdf_bytes = rasterize_pdf(html)
        pdf_ref: Optional[ArtifactRef] = None
        if pdf_bytes is None:
            warnings.append(
                "weasyprint is not installed — .pdf artifact was skipped."
            )
        else:
            pdf_ref = await self._persist_pdf(pdf_bytes, now)

        return json.dumps(
            {
                "final_document": document_ref.model_dump(mode="json"),
                "final_pdf": pdf_ref.model_dump(mode="json") if pdf_ref else None,
                "warnings": warnings,
            }
        )

    async def _persist_html(self, html: str, now: datetime) -> ArtifactRef:
        """Persist the final document HTML via the injected ``ArtifactStore``.

        Degrades to a bare ``ArtifactRef`` (no ``artifact_id``/``url``) when
        no store is configured — mirrors ``ThalesRunner._persist()``'s own
        "no store configured" degrade path (spec: each persistence surface
        fails independently, never aborts the run).
        """
        if self.store is None:
            return ArtifactRef(kind="final_html")
        artifact_id = f"{self.node_id}-html-{uuid.uuid4().hex[:8]}"
        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.INTERACTIVE,
            title=self.title,
            created_at=now,
            updated_at=now,
            definition={"html": html},
        )
        await self.store.save_artifact(self.user_id, self.agent_id, self.session_id, artifact)
        url = await self.store.get_public_url(
            self.user_id, self.agent_id, self.session_id, artifact_id,
        )
        return ArtifactRef(kind="final_html", artifact_id=artifact_id, url=url)

    async def _persist_pdf(self, pdf_bytes: bytes, now: datetime) -> ArtifactRef:
        """Persist the final document PDF via the injected ``ArtifactStore``.

        Degrades to a bare ``ArtifactRef`` (no ``artifact_id``/``url``) when
        no store is configured — see :meth:`_persist_html`.
        """
        if self.store is None:
            return ArtifactRef(kind="final_pdf")
        artifact_id = f"{self.node_id}-pdf-{uuid.uuid4().hex[:8]}"
        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=ArtifactType.EXPORT,
            title=f"{self.title} (PDF)",
            created_at=now,
            updated_at=now,
            definition={"pdf_base64": base64.b64encode(pdf_bytes).decode("ascii")},
        )
        await self.store.save_artifact(self.user_id, self.agent_id, self.session_id, artifact)
        url = await self.store.get_public_url(
            self.user_id, self.agent_id, self.session_id, artifact_id,
        )
        return ArtifactRef(kind="final_pdf", artifact_id=artifact_id, url=url)
