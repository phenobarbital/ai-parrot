"""BOEDataSource — ExtractDataSource adapter for BOE consolidated legislation.

Lets BOE data enter the existing ``OntologyRefreshPipeline`` without any
modification to the pipeline: it calls
``datasource_factory.get(entity_def.source, config).extract(fields=...)``
and expects an ``ExtractionResult`` back, nothing more.

BOE arrives as structured records (parsed by
``parrot_tools.legal.boe.parser.parse_consolidated``), so it enters through
``ExtractDataSource`` and never touches ``GraphIndexBuilder`` or
``UniversalNode``.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import aiohttp
from parrot_loaders.extractors.base import ExtractDataSource, ExtractionResult

from .models import ParsedNorm
from .parser import parse_consolidated

# Both entities declared in legal.ontology.yaml source from "boe"; their
# property sets are disjoint by design, so the requested `fields` tell us
# which entity is being refreshed for a given extract() call.
_NORMA_FIELDS = frozenset(
    {"boe_id", "titulo", "rango", "fecha_disposicion", "fecha_publicacion", "materia_id"}
)
_ARTICULO_FIELDS = frozenset({"articulo_key", "norma_ref", "numero", "versions"})


class BOEDataSource(ExtractDataSource):
    """Extracts norma/articulo records from BOE consolidated legislation.

    Config:
        base_url: str — BOE datos abiertos "legislacion-consolidada" API
            base URL. Defaults to the real BOE endpoint.
        boe_ids: list[str] — BOE identifiers of the norms to sync.
            Defaults to an empty list (no norms configured).
        user_agent: str — identifying User-Agent sent with each request.
        request_delay_seconds: float — optional pause between successive
            norm fetches, to avoid hammering BOE. Defaults to 0 (no
            forced delay); deployments should set this via config.

    Args:
        name: Human-readable name for logging and reporting.
        config: Source-specific configuration (see Config above).
    """

    DEFAULT_BASE_URL = "https://www.boe.es/datosabiertos/api/legislacion-consolidada/id"
    DEFAULT_USER_AGENT = "ai-parrot-legal-boe/1.0 (+https://github.com/phenobarbital/ai-parrot)"

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(name, config)
        # Caches the parsed norm per BOE id for the lifetime of this
        # instance. NOTE: OntologyRefreshPipeline's real call path
        # (DataSourceFactory.get() -> a fresh instance per call) does NOT
        # benefit from this across the pipeline's two extract() calls (one
        # per entity) since each call gets a new instance — see TASK-2376's
        # Completion Note. This cache still helps any caller that holds a
        # single BOEDataSource instance across multiple extract() calls
        # (e.g. direct/manual use, or a future factory-level cache).
        self._cache: dict[str, ParsedNorm] = {}

    async def extract(
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Fetch and parse the configured BOE norms into records.

        Args:
            fields: Optional field projection. Also used to infer which
                entity (norma or articulo) is being refreshed, since their
                property sets are disjoint.
            filters: Optional filters. Supports ``{"since": <date|str>}``
                to restrict extraction to norms published on/after that
                date (an incremental-sync approximation based on
                ``fecha_publicacion``, the only date TASK-2372's parser
                surfaces on the norma record). Falls back to
                ``self.config["since"]`` when ``filters`` does not
                specify one — ``OntologyRefreshPipeline._refresh_entity``
                calls ``extract(fields=...)`` without ever forwarding
                ``filters``, so ``sync_boe(since=...)`` (TASK-2374) can
                only reach this restriction via the constructor config
                (``source_configs={"boe": {"since": since}}``), not via
                the ``filters`` kwarg.

        Returns:
            ExtractionResult with the norma and/or articulo records for
            the requested entity, plus any parser errors. Never raises —
            fetch/parse failures are collected in ``errors``.
        """
        boe_ids = list(self.config.get("boe_ids", []))
        since = self._parse_since(filters)
        target = self._target_entity(fields)
        delay = float(self.config.get("request_delay_seconds", 0) or 0)

        records: list[dict[str, Any]] = []
        errors: list[str] = []

        for index, boe_id in enumerate(boe_ids):
            if delay and index > 0:
                await self._sleep(delay)

            parsed = await self._get_parsed_norm(boe_id)
            errors.extend(parsed.errors)

            if since is not None and parsed.norma:
                fecha_publicacion = parsed.norma.get("fecha_publicacion")
                if fecha_publicacion and fecha_publicacion < since.isoformat():
                    continue

            if target in ("norma", "both") and parsed.norma:
                records.append(parsed.norma)
            if target in ("articulo", "both"):
                records.extend(parsed.articulos)

        return self._build_result(records, fields=fields, errors=errors)

    async def list_fields(self) -> list[str]:
        """Return the field names available across both BOE-sourced entities.

        Returns:
            Sorted list of norma and articulo field names.
        """
        return sorted(_NORMA_FIELDS | _ARTICULO_FIELDS)

    async def extract_relations(self) -> list[dict[str, Any]]:
        """Return the ``modifica``/``deroga`` provenance relations.

        ``ExtractDataSource.extract()`` only ever returns node records
        (norma/articulo), because it exists to feed
        ``OntologyRefreshPipeline``'s generic node upsert path. The
        provenance relations parsed alongside those nodes
        (``ParsedNorm.relations`` — see ``parrot_tools.legal.boe.parser``)
        have no field-match discovery rule to ride into the graph through
        (``modifica``/``deroga`` declare zero rules in
        ``legal.ontology.yaml`` by design, since they are facts extracted
        directly from BOE's XML, not field-matchable). This method exposes
        them explicitly so a caller (``sync_boe``) can bridge them into
        ``OntologyGraphStore.create_edges`` itself.

        Reuses the same per-instance parse cache as ``extract()`` — call
        both on the SAME ``BOEDataSource`` instance to avoid re-fetching
        each configured norm twice.

        Returns:
            Flattened list of relation records across all configured
            ``boe_ids``, each ``{"type": "modifica"|"deroga", "from":
            <boe_id>, "to": <boe_id or articulo_key>}``.
        """
        boe_ids = list(self.config.get("boe_ids", []))
        relations: list[dict[str, Any]] = []
        for boe_id in boe_ids:
            parsed = await self._get_parsed_norm(boe_id)
            relations.extend(parsed.relations)
        return relations

    def _target_entity(self, fields: list[str] | None) -> str:
        """Infer which entity (norma|articulo|both) is being refreshed.

        Args:
            fields: The fields requested by the caller.

        Returns:
            ``"norma"``, ``"articulo"`` or ``"both"`` (when ``fields`` is
            empty/None or straddles both entities' property sets).
        """
        if not fields:
            return "both"
        requested = set(fields)
        wants_norma = bool(requested & _NORMA_FIELDS)
        wants_articulo = bool(requested & _ARTICULO_FIELDS)
        if wants_norma and not wants_articulo:
            return "norma"
        if wants_articulo and not wants_norma:
            return "articulo"
        return "both"

    def _parse_since(self, filters: dict[str, Any] | None) -> date | None:
        """Parse the optional ``since`` restriction into a ``date``.

        Checks ``filters["since"]`` first, then falls back to
        ``self.config["since"]`` — see ``extract()``'s docstring for why
        the config fallback is needed for ``sync_boe(since=...)`` to have
        any effect through the real pipeline call path.

        Args:
            filters: The filters dict passed to ``extract()``.

        Returns:
            The parsed ``since`` date, or None if not provided by either
            source.

        Raises:
            TypeError: If ``since`` is provided but not a ``date`` or an
                ISO-format ``str``.
        """
        if filters and "since" in filters:
            raw = filters["since"]
        elif "since" in self.config:
            raw = self.config["since"]
        else:
            return None

        if raw is None:
            return None
        if isinstance(raw, date):
            return raw
        if isinstance(raw, str):
            return date.fromisoformat(raw)
        raise TypeError(f"Unsupported 'since' filter type: {type(raw)!r}")

    async def _get_parsed_norm(self, boe_id: str) -> ParsedNorm:
        """Fetch (if not cached) and parse one BOE norm.

        Args:
            boe_id: The BOE identifier to fetch.

        Returns:
            The ParsedNorm for this id. On fetch failure, a ParsedNorm
            with an empty norma/articulos and a populated `errors` list —
            never raises.
        """
        if boe_id in self._cache:
            return self._cache[boe_id]

        try:
            xml_text = await self._fetch_raw(self._build_url(boe_id))
        except Exception as exc:  # noqa: BLE001 — tolerant: report, don't raise
            self.logger.warning("Failed to fetch BOE norm %s: %s", boe_id, exc)
            parsed = ParsedNorm(errors=[f"Failed to fetch {boe_id}: {exc}"])
        else:
            parsed = parse_consolidated(xml_text)

        self._cache[boe_id] = parsed
        return parsed

    def _build_url(self, boe_id: str) -> str:
        """Build the BOE API URL for one norm."""
        base_url = self.config.get("base_url", self.DEFAULT_BASE_URL)
        return f"{base_url.rstrip('/')}/{boe_id}"

    async def _fetch_raw(self, url: str) -> str:
        """Fetch a URL as text via aiohttp, sending an identifying User-Agent.

        Args:
            url: The absolute URL to GET.

        Returns:
            The raw response body as text.

        Raises:
            aiohttp.ClientError: On a non-2xx response or connection failure.
        """
        headers = {
            "Accept": "application/xml",
            "User-Agent": self.config.get("user_agent", self.DEFAULT_USER_AGENT),
        }
        session = aiohttp.ClientSession()
        try:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.text()
        finally:
            await session.close()

    async def _sleep(self, seconds: float) -> None:
        """Pause between successive norm fetches (isolated for testability)."""
        await asyncio.sleep(seconds)
