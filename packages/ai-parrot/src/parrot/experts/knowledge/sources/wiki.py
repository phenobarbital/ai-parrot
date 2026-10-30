"""Mandatory wiki source for an expert: namespace handle, probe and LLM-free seeding (FEAT-778 M5, G9)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Sequence

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import (
    ExpertBundle,
    ExpertKnowledgeError,
    KnowledgeLayer,
    KnowledgeMode,
    KnowledgeSourceKind,
    KnowledgeSourceSpec,
)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord
from parrot.memory.compaction.tokens import TokenCounter, get_default_counter

if TYPE_CHECKING:
    from parrot_tools.wiki.toolkit import LLMWikiToolkit

PROBE_LIMIT: Final[int] = 10_000
_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)


class WikiSource:
    """Bind an expert to ``expert-<slug>`` using namespace-prefixed page identifiers."""

    kind = KnowledgeSourceKind.WIKI

    def __init__(
        self,
        toolkit: "LLMWikiToolkit | Any",
        *,
        namespace: str,
        counter: TokenCounter | None = None,
    ) -> None:
        """Initialize a wiki namespace source.

        Args:
            toolkit: Wiki toolkit that owns the backing store.
            namespace: Expert-specific wiki namespace.
            counter: Optional deterministic token counter.
        """
        self.toolkit = toolkit
        self.namespace = namespace
        self.counter = counter or get_default_counter()

    def store_for(self, wiki_name: str) -> BaseWikiStore:
        """Resolve a federated namespace or the toolkit's local store.

        Args:
            wiki_name: Namespace to resolve.

        Returns:
            The resolved wiki store.

        Raises:
            ExpertKnowledgeError: When the namespace cannot be resolved.
        """
        try:
            store = self.toolkit._store_for(wiki_name)  # noqa: SLF001 -- isolated private API adapter
        except Exception as exc:  # noqa: BLE001 -- normalize toolkit/backend failures
            raise ExpertKnowledgeError(f"wiki namespace {wiki_name!r} cannot be resolved: {exc}") from exc
        if store is None:
            raise ExpertKnowledgeError(f"wiki namespace {wiki_name!r} cannot be resolved")
        return store

    @property
    def store(self) -> BaseWikiStore:
        """Return the store serving this expert's namespace."""
        return self.store_for(self.namespace)

    async def probe(self) -> int:
        """Count namespace-prefixed pages, scanning at most ``PROBE_LIMIT`` rows without an LLM call."""
        prefix = f"{self.namespace}/"
        pages = await self.store.list_pages(limit=PROBE_LIMIT)
        return sum(1 for page in pages if str(page.get("concept_id", "")).startswith(prefix))

    async def seed(self, files: Sequence[Path], *, asserted_by: str) -> int:
        """Seed one page per file without invoking the LLM ingester.

        Args:
            files: Markdown knowledge files to seed.
            asserted_by: Identity recorded as the page author.

        Returns:
            Number of pages upserted.

        Raises:
            ExpertKnowledgeError: When the namespace store is not writable.
        """
        records: list[WikiPageRecord] = []
        for file in sorted(files):
            data = file.read_bytes()
            text = data.decode("utf-8")
            heading = _H1.search(text)
            title = heading.group(1).strip() if heading is not None else file.stem
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
            summary = next((part for part in paragraphs if _H1.fullmatch(part) is None), "")[:280]
            records.append(
                WikiPageRecord(
                    concept_id=f"{self.namespace}/{file.stem}",
                    title=title,
                    category="knowledge",
                    body=text,
                    summary=summary,
                    token_count=self.counter.count(text),
                    origin="bundle",
                    asserted_by=asserted_by,
                    content_hash=sha256_revision(data),
                )
            )

        try:
            store = self.store
            store._assert_writable()  # noqa: SLF001 -- explicit fail-fast store contract
            return await store.upsert_pages(records) if records else 0
        except ExpertKnowledgeError:
            raise
        except Exception as exc:  # noqa: BLE001 -- normalize backend-specific write failures
            raise ExpertKnowledgeError(f"wiki-not-writable: {self.namespace}: {exc}") from exc

    async def layers(
        self,
        spec: KnowledgeSourceSpec,
        bundle: ExpertBundle,
        *,
        workspace: Path | None,
        counter: TokenCounter,
    ) -> list[KnowledgeLayer]:
        """Build one retrieval layer, failing when the namespace is empty.

        Args:
            spec: Wiki source declaration from the expert manifest.
            bundle: Expert bundle being resolved.
            workspace: Optional workspace root; unused for wiki retrieval.
            counter: Resolver token counter; unused for retrieval handles.

        Returns:
            A single revisioned retrieval layer.

        Raises:
            ExpertKnowledgeError: When the namespace contains no pages.
        """
        documents = await self.probe()
        if documents == 0:
            raise ExpertKnowledgeError(f"empty-wiki-namespace: {self.namespace}")
        handle: dict[str, Any] = {
            "toolkit": "wiki",
            "wiki_name": self.namespace,
            "scope": spec.scope,
            "documents": documents,
        }
        return [
            KnowledgeLayer(
                layer="retrieval",
                source=f"wiki:{self.namespace}",
                mode=KnowledgeMode.RETRIEVAL,
                revision=sha256_revision(json.dumps(handle, sort_keys=True).encode()),
                tokens=0,
                handle=handle,
            )
        ]
