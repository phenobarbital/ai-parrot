"""
Research Briefing Store
========================

Persistence and retrieval layer for research briefings produced by
the five finance research crews (macro, equity, crypto, sentiment, risk).

Architecture:
    Research Crew LLM output (str)
        → ResearchOutputParser.parse()
        → ResearchBriefing (dataclass)
        → ResearchBriefingStore.store_briefing()
            → Redis  (latest per crew, TTL-based, fast read)
            → Publish event on ``briefings:updated`` channel

Read path:
    DeliberationTrigger / CommitteeDeliberation
        → store.get_latest_briefings()
        → Redis cache (sub-ms latency)

Design decisions:
    - Redis-first: analysts need sub-second access to latest briefings.
    - Pub/Sub: decouples research from deliberation. The trigger
      subscribes to ``briefings:updated`` and decides when to fire.
    - Serialization uses dataclasses.asdict → JSON. No Pydantic overhead
      on the hot path; the ResearchBriefing/ResearchItem dataclasses
      already exist in parrot.finance.schemas.
    - TTL on Redis keys prevents stale data from being used if a crew
      stops producing. Default: 24h per crew, configurable.
"""
from __future__ import annotations
from typing import Any
import json
import uuid
from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone
import redis.asyncio as aioredis
from navconfig.logging import logging
from parrot.finance.schemas import ResearchBriefing, ResearchItem

logger = logging.getLogger("parrot.finance.research.briefing_store")


# =============================================================================
# OUTPUT PARSER — LLM text → ResearchBriefing
# =============================================================================

class ResearchOutputParser:
    """Parse raw LLM output from a research crew into a ResearchBriefing.

    Research crew prompts instruct the LLM to respond with a JSON array
    of research items. This parser:
        1. Extracts the JSON array from the (possibly noisy) LLM response
        2. Validates each item into a ResearchItem dataclass
        3. Wraps them in a ResearchBriefing with metadata

    Usage::

        parser = ResearchOutputParser()
        briefing = parser.parse(
            crew_id="research_crew_macro",
            domain="macro",
            raw_output=llm_response_text,
        )
    """

    def __init__(self, strict: bool = False):
        self.strict = strict
        self.logger = logging.getLogger("parrot.finance.research.parser")

    def parse(
        self,
        crew_id: str,
        domain: str,
        raw_output: str,
        analyst_id: str = "",
        portfolio_snapshot: dict[str, Any] | None = None,
    ) -> ResearchBriefing:
        """Parse raw LLM output into a validated ResearchBriefing.

        Args:
            crew_id: Identifier of the crew (e.g. ``research_crew_macro``).
            domain: Research domain (``macro``, ``equity``, ``crypto``,
                ``sentiment``, ``risk``).
            raw_output: Raw string output from the LLM agent.
            analyst_id: ID of the downstream analyst that will consume this.
            portfolio_snapshot: Current portfolio state (optional context).

        Returns:
            A populated ``ResearchBriefing`` dataclass.

        Raises:
            ValueError: If ``strict=True`` and no valid items are parsed.
        """
        items_raw = self._extract_json(raw_output)
        validated: list[ResearchItem] = []

        for idx, item_data in enumerate(items_raw):
            try:
                ri = self._to_research_item(item_data)
                validated.append(ri)
            except Exception as exc:
                self.logger.warning(
                    "Skipping invalid item %d from %s: %s", idx, crew_id, exc
                )
                if self.strict:
                    raise

        if self.strict and not validated:
            raise ValueError(
                f"No valid research items parsed from {crew_id} output"
            )

        self.logger.info(
            "Parsed %d/%d items from %s (domain=%s)",
            len(validated), len(items_raw), crew_id, domain,
        )

        return ResearchBriefing(
            id=uuid.uuid4().hex,
            analyst_id=analyst_id or self._analyst_for_domain(domain),
            domain=domain,
            generated_at=datetime.now(timezone.utc),
            research_items=validated,
            portfolio_snapshot=portfolio_snapshot or {},
        )

    # ── JSON extraction ─────────────────────────────────────────────

    def _extract_json(self, text: str) -> list[dict[str, Any]]:
        """Extract a JSON array from LLM output text.

        Handles common LLM quirks:
        - JSON inside markdown code fences
        - Leading/trailing prose around the JSON
        - Single JSON object (wraps in array)
        """
        cleaned = text.strip()

        # Strip markdown code fences
        if "```" in cleaned:
            parts = cleaned.split("```")
            for part in parts:
                stripped = part.strip()
                if stripped.startswith("json"):
                    stripped = stripped[4:].strip()
                if stripped.startswith("[") or stripped.startswith("{"):
                    cleaned = stripped
                    break

        # Find the JSON array or object boundaries
        start_bracket = cleaned.find("[")
        start_brace = cleaned.find("{")

        if start_bracket == -1 and start_brace == -1:
            self.logger.warning("No JSON found in output")
            return []

        try:
            if start_bracket != -1 and (
                start_brace == -1 or start_bracket < start_brace
            ):
                # Array found first
                end = cleaned.rfind("]")
                if end == -1:
                    return []
                return json.loads(cleaned[start_bracket : end + 1])
            else:
                # Object found first — wrap in array
                end = cleaned.rfind("}")
                if end == -1:
                    return []
                obj = json.loads(cleaned[start_brace : end + 1])
                return [obj] if isinstance(obj, dict) else obj
        except json.JSONDecodeError as exc:
            self.logger.warning("JSON decode error: %s", exc)
            return []

    # ── Item conversion ──────────────────────────────────────────────

    def _to_research_item(self, data: dict[str, Any]) -> ResearchItem:
        """Convert a raw dict into a ResearchItem dataclass.

        Performs lenient mapping: unknown keys are ignored, missing
        optional fields get defaults from the dataclass definition.
        """
        valid_fields = {f.name for f in fields(ResearchItem)}
        filtered = {}

        for key, value in data.items():
            if key in valid_fields:
                filtered[key] = value

        # Parse timestamp if string
        ts = filtered.get("timestamp")
        if isinstance(ts, str):
            try:
                filtered["timestamp"] = datetime.fromisoformat(
                    ts.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                filtered["timestamp"] = datetime.now(timezone.utc)

        # Ensure relevance_score is float
        score = filtered.get("relevance_score")
        if score is not None:
            try:
                filtered["relevance_score"] = float(score)
            except (ValueError, TypeError):
                filtered["relevance_score"] = 0.0

        # Ensure assets_mentioned is a list
        assets = filtered.get("assets_mentioned")
        if assets is not None and not isinstance(assets, list):
            filtered["assets_mentioned"] = [str(assets)]

        return ResearchItem(**filtered)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _analyst_for_domain(domain: str) -> str:
        """Map domain → default analyst_id."""
        mapping = {
            "macro": "macro_analyst",
            "equity": "equity_analyst",
            "crypto": "crypto_analyst",
            "sentiment": "sentiment_analyst",
            "risk": "risk_analyst",
        }
        return mapping.get(domain, f"{domain}_analyst")


# =============================================================================
# BRIEFING STORE — Redis persistence + event publishing
# =============================================================================

class ResearchBriefingStore:
    """Store and retrieve research briefings via Redis.

    Write path:
        ``store_briefing()`` → serialise → Redis SET (latest) + PUBLISH event.

    Read path:
        ``get_latest_briefings()`` → Redis GET per crew → deserialise.

    Keys:
        ``briefing:latest:{crew_id}``   — latest briefing JSON (TTL)
        ``briefing:meta:{crew_id}``     — metadata (timestamp, item count)

    Events:
        Channel ``briefings:updated``   — published after every store.

    Usage::

        store = ResearchBriefingStore(redis)
        await store.store_briefing("research_crew_macro", briefing)
        latest = await store.get_latest_briefings()
    """

    # Default TTL per crew domain. Crypto data gets stale faster.
    DEFAULT_TTL: dict[str, int] = {
        "macro": 86400,       # 24 hours
        "equity": 43200,      # 12 hours
        "crypto": 21600,      # 6 hours
        "sentiment": 43200,   # 12 hours
        "risk": 86400,        # 24 hours
    }
    EVENT_CHANNEL = "briefings:updated"
    KEY_PREFIX = "briefing:latest"
    META_PREFIX = "briefing:meta"

    # Crew ID → domain mapping
    CREW_DOMAINS: dict[str, str] = {
        "research_crew_macro": "macro",
        "research_crew_equity": "equity",
        "research_crew_crypto": "crypto",
        "research_crew_sentiment": "sentiment",
        "research_crew_risk": "risk",
    }
    ALL_CREW_IDS = list(CREW_DOMAINS.keys())

    def __init__(
        self,
        redis: aioredis.Redis,
        ttl_overrides: dict[str, int] | None = None,
    ):
        self.redis = redis
        self._ttl = {**self.DEFAULT_TTL, **(ttl_overrides or {})}

    # ═════════════════════════════════════════════════════════════════
    # WRITE
    # ═════════════════════════════════════════════════════════════════

    async def store_briefing(
        self,
        crew_id: str,
        briefing: ResearchBriefing,
    ) -> str:
        """Persist a new briefing and notify subscribers.

        Args:
            crew_id: Research crew identifier (e.g. ``research_crew_macro``).
            briefing: Validated ``ResearchBriefing`` dataclass.

        Returns:
            The briefing ID.
        """
        domain = self.CREW_DOMAINS.get(crew_id, "unknown")
        ttl = self._ttl.get(domain, 86400)

        # Serialise
        payload = json.dumps(
            asdict(briefing), default=self._json_serializer, ensure_ascii=False,
        )

        # Store latest briefing
        key = f"{self.KEY_PREFIX}:{crew_id}"
        await self.redis.set(key, payload, ex=ttl)

        # Store metadata (lighter, for quick freshness checks)
        meta_key = f"{self.META_PREFIX}:{crew_id}"
        meta = json.dumps({
            "briefing_id": briefing.id,
            "domain": domain,
            "generated_at": briefing.generated_at.isoformat(),
            "item_count": len(briefing.research_items),
            "stored_at": datetime.now(timezone.utc).isoformat(),
        })
        await self.redis.set(meta_key, meta, ex=ttl)

        # Publish event
        event_payload = json.dumps({
            "crew_id": crew_id,
            "domain": domain,
            "briefing_id": briefing.id,
            "item_count": len(briefing.research_items),
            "generated_at": briefing.generated_at.isoformat(),
        })
        await self.redis.publish(self.EVENT_CHANNEL, event_payload)

        logger.info(
            "Stored briefing %s for %s (%d items, TTL=%ds)",
            briefing.id, crew_id, len(briefing.research_items), ttl,
        )
        return briefing.id

    # ═════════════════════════════════════════════════════════════════
    # READ
    # ═════════════════════════════════════════════════════════════════

    async def get_latest_briefing(
        self, crew_id: str
    ) -> ResearchBriefing | None:
        """Get the latest briefing for a single crew.

        Returns None if no briefing is cached (expired or never stored).
        """
        key = f"{self.KEY_PREFIX}:{crew_id}"
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return self._deserialize_briefing(raw)

    async def get_latest_briefings(self) -> dict[str, ResearchBriefing]:
        """Get latest briefings from all crews.

        Returns:
            Dict mapping domain name → ResearchBriefing.
            Only includes crews that have fresh (non-expired) data.
        """
        result: dict[str, ResearchBriefing] = {}
        pipe = self.redis.pipeline()
        for crew_id in self.ALL_CREW_IDS:
            pipe.get(f"{self.KEY_PREFIX}:{crew_id}")
        values = await pipe.execute()

        for crew_id, raw in zip(self.ALL_CREW_IDS, values):
            if raw is not None:
                domain = self.CREW_DOMAINS[crew_id]
                briefing = self._deserialize_briefing(raw)
                if briefing is not None:
                    result[domain] = briefing

        return result

    async def get_briefing_metadata(self) -> dict[str, dict[str, Any]]:
        """Get lightweight metadata for all crews (no full items).

        Useful for the DeliberationTrigger to check freshness without
        deserialising full briefings.
        """
        result: dict[str, dict[str, Any]] = {}
        pipe = self.redis.pipeline()
        for crew_id in self.ALL_CREW_IDS:
            pipe.get(f"{self.META_PREFIX}:{crew_id}")
        values = await pipe.execute()

        for crew_id, raw in zip(self.ALL_CREW_IDS, values):
            if raw is not None:
                domain = self.CREW_DOMAINS[crew_id]
                try:
                    result[domain] = json.loads(raw)
                except json.JSONDecodeError:
                    pass

        return result

    # ═════════════════════════════════════════════════════════════════
    # FRESHNESS
    # ═════════════════════════════════════════════════════════════════

    async def check_freshness(
        self,
        staleness_windows: dict[str, timedelta] | None = None,
    ) -> dict[str, bool]:
        """Check which crews have fresh briefings.

        Args:
            staleness_windows: Max age per domain. Defaults to:
                macro=8h, equity=6h, crypto=4h, sentiment=6h, risk=8h.

        Returns:
            Dict mapping domain → is_fresh (bool).
        """
        default_windows = {
            "macro": timedelta(hours=8),
            "equity": timedelta(hours=6),
            "crypto": timedelta(hours=4),
            "sentiment": timedelta(hours=6),
            "risk": timedelta(hours=8),
        }
        windows = {**default_windows, **(staleness_windows or {})}
        now = datetime.now(timezone.utc)

        metadata = await self.get_briefing_metadata()
        freshness: dict[str, bool] = {}

        for domain in ["macro", "equity", "crypto", "sentiment", "risk"]:
            meta = metadata.get(domain)
            if meta is None:
                freshness[domain] = False
                continue

            generated_str = meta.get("generated_at", "")
            try:
                generated_at = datetime.fromisoformat(generated_str)
                if generated_at.tzinfo is None:
                    generated_at = generated_at.replace(tzinfo=timezone.utc)
                age = now - generated_at
                freshness[domain] = age <= windows[domain]
            except (ValueError, TypeError):
                freshness[domain] = False

        return freshness

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL
    # ═════════════════════════════════════════════════════════════════

    def _deserialize_briefing(self, raw: str) -> ResearchBriefing | None:
        """Deserialize a JSON string into a ResearchBriefing."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to decode briefing JSON: %s", exc)
            return None

        # Reconstruct ResearchItem list
        items_raw = data.pop("research_items", [])
        items = []
        for item_data in items_raw:
            ts = item_data.get("timestamp")
            if isinstance(ts, str):
                try:
                    item_data["timestamp"] = datetime.fromisoformat(
                        ts.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    item_data["timestamp"] = datetime.now(timezone.utc)
            # Filter to valid fields only
            valid = {f.name for f in fields(ResearchItem)}
            filtered = {k: v for k, v in item_data.items() if k in valid}
            items.append(ResearchItem(**filtered))

        # Reconstruct generated_at
        gen_at = data.get("generated_at")
        if isinstance(gen_at, str):
            try:
                data["generated_at"] = datetime.fromisoformat(
                    gen_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                data["generated_at"] = datetime.now(timezone.utc)

        # Build briefing
        valid_briefing_fields = {f.name for f in fields(ResearchBriefing)}
        filtered_data = {k: v for k, v in data.items() if k in valid_briefing_fields}
        filtered_data["research_items"] = items

        try:
            return ResearchBriefing(**filtered_data)
        except Exception as exc:
            logger.warning("Failed to reconstruct ResearchBriefing: %s", exc)
            return None

    @staticmethod
    def _json_serializer(obj: Any) -> Any:
        """JSON serializer for dataclass fields (datetime, etc.)."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "value"):  # Enum
            return obj.value
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")