"""Stable document pages and their asserted graph neighbourhood."""

import asyncio
import hashlib
import logging
from pathlib import Path

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.documents import AcquiredDocument, TriageProvenance, render_frontmatter
from parrot.knowledge.wiki.inbox.models import ResolvedClassification, VerifiedLink
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.review import ManifestDocEntry
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, estimate_tokens

INBOX_ASSERTED_BY = "agent:wikitoolkit-inbox"
REL_PART_OF = "part_of"
REL_TAGGED = "tagged"
TAG_CATEGORY = "tag"


def tag_page_id(tag: str) -> str:
    """Return a tag node id for an already normalized tag."""
    return f"tag:{tag}"


def render_doc_body(
    classification: ResolvedClassification,
    acquired: AcquiredDocument,
    provenance: TriageProvenance,
    links: list[VerifiedLink],
    child_ids: list[str],
) -> str:
    """Render source metadata, title/summary, related links and child sections."""
    frontmatter = render_frontmatter(acquired.metadata, provenance)
    lines = [f"# {classification.title}", "", classification.summary]
    if links:
        lines.extend(["", "## Related"])
        lines.extend(f"- [[{link.page_id}]] ({link.rel})" for link in links)
    if child_ids:
        lines.extend(["", "## Sections"])
        lines.extend(f"- [[{child_id}]]" for child_id in child_ids)
    return frontmatter + "\n".join(lines) + "\n"


class DocPageWriter:
    """Persist authored document/tag pages without owning PageIndex's source slice."""

    def __init__(
        self,
        store: BaseWikiStore,
        sources: SourceCollectionManager,
        bookkeeper: WikiBookkeeper,
        wiki_dir: Path,
    ) -> None:
        """Bind graph persistence and audit dependencies."""
        self.store = store
        self.sources = sources
        self.bookkeeper = bookkeeper
        self.wiki_dir = wiki_dir
        self.logger = logging.getLogger(__name__)

    async def write_doc_page(
        self,
        doc_id: str,
        source_id: str,
        classification: ResolvedClassification,
        acquired: AcquiredDocument,
        triage: ManifestDocEntry,
        charter_version: str,
        links: list[VerifiedLink],
        archive_decision: bool,
    ) -> str:
        """Write the doc page and asserted child/link edges, returning doc_id."""
        source = await asyncio.to_thread(self.sources.get_source, source_id)
        child_ids = list(source.pages_generated) if source is not None else []
        extra = dict(acquired.metadata.extra)
        extra.update(
            {
                "source_id": source_id,
                "source_uri": triage.source_uri,
                "file_hash": triage.file_hash,
            }
        )
        metadata = acquired.metadata.model_copy(update={"extra": extra})
        copied = acquired.model_copy(update={"metadata": metadata})
        provenance = TriageProvenance(
            composite_score=triage.composite,
            decision=triage.decision or triage.proposed_action,
            decision_source=triage.decision_source,
            charter_version=charter_version,
        )
        body = render_doc_body(classification, copied, provenance, links, child_ids)
        page = WikiPageRecord(
            concept_id=doc_id,
            node_id=doc_id,
            title=classification.title,
            category="archive" if archive_decision else classification.category,
            summary=classification.summary,
            body=body,
            source_id=None,
            token_count=estimate_tokens(body),
            origin="authored",
            asserted_by=INBOX_ASSERTED_BY,
        )
        await self.store.upsert_pages([page])
        await self.ensure_tags(doc_id, classification.tags)
        edges: list[tuple[str, str, str, str]] = [(child_id, doc_id, REL_PART_OF, "asserted") for child_id in child_ids]
        edges.extend((doc_id, link.page_id, link.rel, "asserted") for link in links)
        if edges:
            await self.store.add_edges(edges)
        await asyncio.to_thread(
            self.bookkeeper.log_operation,
            self.wiki_dir,
            "DOC_PAGE",
            f"wrote {doc_id}",
        )
        return doc_id

    async def ensure_tags(self, doc_id: str, tags: list[str]) -> list[str]:
        """Create missing tag nodes and idempotent asserted tagged edges."""
        tag_ids = list(dict.fromkeys(tag_page_id(tag) for tag in tags))
        missing: list[WikiPageRecord] = []
        for tag_id in tag_ids:
            if await self.store.get_page(tag_id, include_body=False) is None:
                tag = tag_id.removeprefix("tag:")
                missing.append(
                    WikiPageRecord(
                        concept_id=tag_id,
                        node_id=tag_id,
                        title=tag,
                        category=TAG_CATEGORY,
                        summary=tag,
                        body=f"# {tag}\n",
                        source_id=None,
                        token_count=1,
                        origin="authored",
                        asserted_by=INBOX_ASSERTED_BY,
                    )
                )
        if missing:
            await self.store.upsert_pages(missing)
        if tag_ids:
            await self.store.add_edges([(doc_id, tag_id, REL_TAGGED, "asserted") for tag_id in tag_ids])
        return tag_ids

    async def emit_adr_candidate(
        self,
        doc_id: str,
        classification: ResolvedClassification,
        acquired: AcquiredDocument,
        doc_rel_path: str,
        config: WikiProjectConfig,
    ) -> tuple[str | None, bool]:
        """Create or reuse an inferred ADR; return None on disabled/nondecision/error."""
        if classification.kind != "decision" or not config.decisions.enabled:
            return None, False
        from parrot.knowledge.wiki.decisions.codec import candidate_decision_id
        from parrot.knowledge.wiki.decisions.generation import PROMPT_VERSION
        from parrot.knowledge.wiki.decisions.models import DecisionRecord, EvidenceRef
        from parrot.knowledge.wiki.decisions.repository import DecisionRepository

        try:
            source_bytes = await asyncio.to_thread(Path(acquired.ref.uri).read_bytes)
            source_sha1 = hashlib.sha1(source_bytes).hexdigest()
            decision = classification.summary.strip()
            if not decision:
                decision = classification.title.strip()
            if not decision:
                return None, False
            fingerprint = hashlib.sha1(acquired.text.encode("utf-8")).hexdigest()
            decision_id = candidate_decision_id(doc_id, fingerprint, PROMPT_VERSION, decision)
            repository = DecisionRepository(self.store, max_records=config.decisions.max_records)
            if await repository.get(decision_id) is not None:
                self.logger.info("Reused inbox ADR candidate %s", decision_id)
                return decision_id, True
            lines = acquired.text.splitlines() or [decision]
            record = DecisionRecord(
                decision_id=decision_id,
                title=classification.title,
                context=classification.summary,
                decision=decision,
                origin="inferred",
                source_status="unknown",
                review_status="unreviewed",
                source_path=doc_rel_path,
                external_id=f"inbox:{doc_id}",
                evidence=[
                    EvidenceRef(
                        page_id=doc_id,
                        rel_path=doc_rel_path,
                        start_line=1,
                        end_line=len(lines),
                        source_sha1=source_sha1,
                        excerpt="\n".join(lines[:20]),
                        kind="document",
                    )
                ],
                content_fingerprint=fingerprint,
            )
            await repository.save(record, None)
            return decision_id, False
        except Exception:
            self.logger.exception("Failed to emit inbox ADR candidate for %s", doc_id)
            return None, False
