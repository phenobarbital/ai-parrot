"""Relation discovery engine for automatic edge creation.

Discovers relationships between entities using configurable strategies:
exact field matching, fuzzy string matching, AI-assisted resolution,
and composite multi-field scoring.
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .schema import DiscoveryRule, RelationDef, TenantContext

logger = logging.getLogger("Parrot.Ontology.Discovery")


class DiscoveryStats(BaseModel):
    """Statistics for a discovery run.

    Args:
        total_source: Number of source records processed.
        total_target: Number of target records available.
        edges_created: Number of confirmed edges.
        needs_review: Number of ambiguous pairs sent to review queue.
    """

    total_source: int = 0
    total_target: int = 0
    edges_created: int = 0
    needs_review: int = 0


class DiscoveryResult(BaseModel):
    """Result of a relation discovery operation.

    Args:
        confirmed: Edges to create (list of {_from, _to, confidence, rule} dicts).
        review_queue: Ambiguous pairs below threshold.
        stats: Discovery statistics.
    """

    confirmed: list[dict[str, Any]] = Field(default_factory=list)
    review_queue: list[dict[str, Any]] = Field(default_factory=list)
    stats: DiscoveryStats = Field(default_factory=DiscoveryStats)


class RelationDiscovery:
    """Discover and create relationships between entities in the graph.

    Strategies:
        - exact: Direct equality join between source and target fields.
        - fuzzy: Normalized string matching with configurable threshold (rapidfuzz).
        - ai_assisted: Batch LLM resolution for ambiguous pairs.
        - composite: Multi-field weighted scoring.

    Args:
        llm_client: Optional LLM client for AI-assisted strategy.
        review_dir: Directory for review queue JSON files. If None, review
            entries are returned but not written to disk.
    """

    # Minimum confidence for fuzzy matches to enter the review queue
    # (below this they are silently dropped).
    _FUZZY_MIN_CONFIDENCE = 0.50

    def __init__(
        self,
        llm_client: Any = None,
        review_dir: Path | str | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.review_dir = Path(review_dir) if review_dir else None

    async def discover(
        self,
        ctx: TenantContext,
        relation_def: RelationDef,
        source_data: list[dict[str, Any]],
        target_data: list[dict[str, Any]],
    ) -> DiscoveryResult:
        """Discover edges between source and target entities.

        Iterates over all discovery rules in the relation definition,
        applies each matching strategy, merges and deduplicates results.

        Args:
            ctx: Tenant context.
            relation_def: Relation definition with discovery rules.
            source_data: Source entity records.
            target_data: Target entity records.

        Returns:
            DiscoveryResult with confirmed edges and review queue.
        """
        all_confirmed: list[dict[str, Any]] = []
        all_review: list[dict[str, Any]] = []

        from_collection = None
        to_collection = None
        from_entity = ctx.ontology.entities.get(relation_def.from_entity)
        to_entity = ctx.ontology.entities.get(relation_def.to_entity)
        if from_entity:
            from_collection = from_entity.collection
        if to_entity:
            to_collection = to_entity.collection

        from_key = from_entity.key_field if from_entity else "_key"
        to_key = to_entity.key_field if to_entity else "_key"

        for rule in relation_def.discovery.rules:
            if rule.match_type == "exact":
                matches = self._exact_match(
                    source_data, target_data, rule,
                    from_collection, to_collection, from_key, to_key,
                )
                all_confirmed.extend(matches)

            elif rule.match_type == "fuzzy":
                confirmed, ambiguous = self._fuzzy_match(
                    source_data, target_data, rule,
                    from_collection, to_collection, from_key, to_key,
                    threshold=rule.threshold,
                )
                all_confirmed.extend(confirmed)
                all_review.extend(ambiguous)

            elif rule.match_type == "ai_assisted":
                candidates = self._get_candidates(
                    source_data, target_data, rule,
                )
                resolved = await self._llm_resolve_batch(
                    candidates, relation_def, rule.threshold,
                )
                for item in resolved:
                    if item.get("confidence", 0) >= rule.threshold:
                        all_confirmed.append(item.get("edge", {}))
                    else:
                        all_review.append(item)

            elif rule.match_type == "composite":
                confirmed, ambiguous = self._composite_match(
                    source_data, target_data, rule,
                    from_collection, to_collection, from_key, to_key,
                )
                all_confirmed.extend(confirmed)
                all_review.extend(ambiguous)

        # Deduplicate confirmed edges
        all_confirmed = self._deduplicate(all_confirmed)

        # Write review queue to disk
        if all_review and self.review_dir:
            self._write_review_queue(ctx.tenant_id, all_review)

        result = DiscoveryResult(
            confirmed=all_confirmed,
            review_queue=all_review,
            stats=DiscoveryStats(
                total_source=len(source_data),
                total_target=len(target_data),
                edges_created=len(all_confirmed),
                needs_review=len(all_review),
            ),
        )

        logger.info(
            "Discovery for '%s': %d confirmed, %d review (from %d source × %d target)",
            relation_def.edge_collection,
            len(all_confirmed), len(all_review),
            len(source_data), len(target_data),
        )
        return result

    # ── Exact Match ──

    def _exact_match(
        self,
        source_data: list[dict],
        target_data: list[dict],
        rule: DiscoveryRule,
        from_collection: str | None,
        to_collection: str | None,
        from_key: str,
        to_key: str,
    ) -> list[dict[str, Any]]:
        """Exact field match — deterministic, O(n+m) via lookup dict.

        Args:
            source_data: Source records.
            target_data: Target records.
            rule: Discovery rule with source_field and target_field.
            from_collection: Source vertex collection name.
            to_collection: Target vertex collection name.
            from_key: Source key field name.
            to_key: Target key field name.

        Returns:
            List of edge dicts.
        """
        # Build lookup on target_field
        target_lookup: dict[str, dict] = {}
        for t in target_data:
            val = t.get(rule.target_field)
            if val is not None:
                target_lookup[str(val).strip()] = t

        edges: list[dict[str, Any]] = []
        for s in source_data:
            val = s.get(rule.source_field)
            if val is None:
                continue
            match = target_lookup.get(str(val).strip())
            if match:
                edges.append(self._build_edge(
                    s, match, from_collection, to_collection,
                    from_key, to_key,
                    confidence=1.0, rule_name=f"exact:{rule.source_field}",
                ))
        return edges

    # ── Fuzzy Match ──

    def _fuzzy_match(
        self,
        source_data: list[dict],
        target_data: list[dict],
        rule: DiscoveryRule,
        from_collection: str | None,
        to_collection: str | None,
        from_key: str,
        to_key: str,
        threshold: float = 0.85,
    ) -> tuple[list[dict], list[dict]]:
        """Fuzzy string matching using rapidfuzz.

        Args:
            threshold: Confidence threshold. Above = confirmed, between
                threshold and _FUZZY_MIN_CONFIDENCE = review queue.

        Returns:
            Tuple of (confirmed_edges, ambiguous_pairs).
        """
        from rapidfuzz import fuzz

        confirmed: list[dict] = []
        ambiguous: list[dict] = []

        target_values = []
        target_records = []
        for t in target_data:
            val = t.get(rule.target_field)
            if val is not None:
                target_values.append(str(val).strip().lower())
                target_records.append(t)

        for s in source_data:
            val = s.get(rule.source_field)
            if val is None:
                continue
            source_val = str(val).strip().lower()

            best_score = 0.0
            best_idx = -1
            for idx, tv in enumerate(target_values):
                score = fuzz.ratio(source_val, tv) / 100.0
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_idx < 0:
                continue

            if best_score >= threshold:
                confirmed.append(self._build_edge(
                    s, target_records[best_idx],
                    from_collection, to_collection, from_key, to_key,
                    confidence=best_score,
                    rule_name=f"fuzzy:{rule.source_field}",
                ))
            elif best_score >= self._FUZZY_MIN_CONFIDENCE:
                ambiguous.append({
                    "source_value": str(val),
                    "target_value": str(target_records[best_idx].get(rule.target_field)),
                    "confidence": round(best_score, 3),
                    "rule_name": f"fuzzy:{rule.source_field}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        return confirmed, ambiguous

    # ── AI-Assisted Match ──

    def _get_candidates(
        self,
        source_data: list[dict],
        target_data: list[dict],
        rule: DiscoveryRule,
    ) -> list[tuple[str, str]]:
        """Get candidate pairs for AI-assisted resolution.

        Returns pairs of (source_value, target_value) that could not be
        resolved by exact or fuzzy matching.
        """
        candidates: list[tuple[str, str]] = []
        for s in source_data:
            sval = s.get(rule.source_field)
            if sval is None:
                continue
            for t in target_data:
                tval = t.get(rule.target_field)
                if tval is None:
                    continue
                candidates.append((str(sval), str(tval)))
        return candidates

    async def _llm_resolve_batch(
        self,
        candidates: list[tuple[str, str]],
        relation_def: RelationDef,
        threshold: float,
        batch_size: int = 50,
    ) -> list[dict[str, Any]]:
        """Send ambiguous pairs to the LLM for resolution.

        Args:
            candidates: List of (source_value, target_value) pairs.
            relation_def: Relation context for the LLM prompt.
            threshold: Confidence threshold for confirmed matches.
            batch_size: Max pairs per LLM call.

        Returns:
            List of resolution dicts with confidence scores.
        """
        if not self.llm_client or not candidates:
            return []

        results: list[dict[str, Any]] = []

        for i in range(0, len(candidates), batch_size):
            batch = candidates[i : i + batch_size]
            pairs_text = "\n".join(
                f"{idx+1}. ('{src}', '{tgt}')"
                for idx, (src, tgt) in enumerate(batch)
            )
            prompt = (
                f"Given these pairs for the relation '{relation_def.edge_collection}' "
                f"({relation_def.from_entity} → {relation_def.to_entity}), "
                f"determine if each pair refers to the same concept.\n\n"
                f"Pairs:\n{pairs_text}\n\n"
                f"Return a JSON array with one object per pair: "
                f'[{{"index": 1, "confidence": 0.95}}, ...]'
            )

            try:
                response = await self.llm_client.completion(prompt)
                output = getattr(response, "output", str(response))
                parsed = _json.loads(output) if isinstance(output, str) else output
                if isinstance(parsed, list):
                    for item in parsed:
                        idx = item.get("index", 0) - 1
                        conf = float(item.get("confidence", 0))
                        if 0 <= idx < len(batch):
                            results.append({
                                "source_value": batch[idx][0],
                                "target_value": batch[idx][1],
                                "confidence": conf,
                                "rule_name": "ai_assisted",
                                "edge": {},  # Caller builds the actual edge
                            })
            except Exception as e:
                logger.warning("LLM resolution batch failed: %s", e)

        return results

    # ── Composite Match ──

    def _composite_match(
        self,
        source_data: list[dict],
        target_data: list[dict],
        rule: DiscoveryRule,
        from_collection: str | None,
        to_collection: str | None,
        from_key: str,
        to_key: str,
    ) -> tuple[list[dict], list[dict]]:
        """Multi-field weighted scoring (extension of fuzzy).

        Uses the source_field as a comma-separated list of fields and
        averages fuzzy scores across all of them.

        Returns:
            Tuple of (confirmed_edges, ambiguous_pairs).
        """
        from rapidfuzz import fuzz

        fields = [f.strip() for f in rule.source_field.split(",")]
        target_fields = [f.strip() for f in rule.target_field.split(",")]

        if len(fields) != len(target_fields):
            logger.warning(
                "Composite match: source and target field count mismatch"
            )
            return [], []

        confirmed: list[dict] = []
        ambiguous: list[dict] = []

        for s in source_data:
            best_score = 0.0
            best_target: dict | None = None

            for t in target_data:
                scores = []
                for sf, tf in zip(fields, target_fields):
                    sv = str(s.get(sf, "")).strip().lower()
                    tv = str(t.get(tf, "")).strip().lower()
                    if sv and tv:
                        scores.append(fuzz.ratio(sv, tv) / 100.0)
                if scores:
                    avg = sum(scores) / len(scores)
                    if avg > best_score:
                        best_score = avg
                        best_target = t

            if best_target is None:
                continue

            if best_score >= rule.threshold:
                confirmed.append(self._build_edge(
                    s, best_target, from_collection, to_collection,
                    from_key, to_key,
                    confidence=best_score,
                    rule_name=f"composite:{rule.source_field}",
                ))
            elif best_score >= self._FUZZY_MIN_CONFIDENCE:
                ambiguous.append({
                    "source_value": {f: s.get(f) for f in fields},
                    "target_value": {f: best_target.get(f) for f in target_fields},
                    "confidence": round(best_score, 3),
                    "rule_name": f"composite:{rule.source_field}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        return confirmed, ambiguous

    # ── Helpers ──

    def _build_edge(
        self,
        source: dict,
        target: dict,
        from_collection: str | None,
        to_collection: str | None,
        from_key: str,
        to_key: str,
        confidence: float,
        rule_name: str,
    ) -> dict[str, Any]:
        """Build an edge document from source and target records."""
        from_id = f"{from_collection}/{source.get(from_key, source.get('_key', ''))}" if from_collection else source.get("_id", "")
        to_id = f"{to_collection}/{target.get(to_key, target.get('_key', ''))}" if to_collection else target.get("_id", "")
        return {
            "_from": from_id,
            "_to": to_id,
            "confidence": confidence,
            "rule": rule_name,
        }

    def _deduplicate(
        self, edges: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Deduplicate edges by (_from, _to), keeping highest confidence."""
        seen: dict[tuple[str, str], dict] = {}
        for edge in edges:
            key = (edge.get("_from", ""), edge.get("_to", ""))
            existing = seen.get(key)
            if existing is None or edge.get("confidence", 0) > existing.get("confidence", 0):
                seen[key] = edge
        return list(seen.values())

    def _write_review_queue(
        self, tenant_id: str, review_items: list[dict[str, Any]]
    ) -> None:
        """Write ambiguous pairs to a JSON review queue file.

        Args:
            tenant_id: Tenant identifier for filename.
            review_items: List of ambiguous match dicts.
        """
        if not self.review_dir:
            return
        self.review_dir.mkdir(parents=True, exist_ok=True)
        path = self.review_dir / f"{tenant_id}_review_queue.json"

        # Append to existing review queue if present
        existing: list[dict] = []
        if path.exists():
            try:
                existing = _json.loads(path.read_text())
            except Exception:
                pass

        existing.extend(review_items)
        path.write_text(_json.dumps(existing, indent=2, default=str))
        logger.info(
            "Wrote %d review items to %s (total: %d)",
            len(review_items), path, len(existing),
        )
