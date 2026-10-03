"""LLM contradiction pack — opt-in, pair-capped (FEAT-625)."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from parrot.clients.detection import detect_coding_agent_llm
from parrot.clients.factory import LLMFactory
from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions
from parrot.knowledge.lint.rule import make_fingerprint

DEFAULT_MAX_PAIRS = 50


def resolve_lint_llm_spec(explicit: str | None) -> str | None:
    """--llm-model > WIKI_LINT_LLM > WIKI_EXTRACT_LLM > coding-agent auto-detect (unless PARROT_NO_AUTO_LLM).

    Args:
        explicit: Explicit --llm-model value from LintOptions.

    Returns:
        LLM spec string or None if no model is configured.
    """
    spec = explicit or os.environ.get("WIKI_LINT_LLM") or os.environ.get("WIKI_EXTRACT_LLM")
    if spec or os.environ.get("PARROT_NO_AUTO_LLM"):
        return spec or None
    try:
        return detect_coding_agent_llm()
    except Exception:  # noqa: BLE001 — detection is best-effort
        return None


class ContradictionLLMRule:
    """Ask an LLM whether two memories/ADRs about the same page contradict."""

    rule_id, pack, default_severity = "contradiction-llm", "llm", "warning"

    def __init__(self, client: Any, max_pairs: int = DEFAULT_MAX_PAIRS, timeout_s: float = 30.0) -> None:
        self.client = client
        self.max_pairs = max_pairs
        self.timeout_s = timeout_s

    async def _pairs(self, ctx: LintContext) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Find candidate pairs of memories/ADRs that link the same page.

        Pairs are ranked by shared links and capped at max_pairs.

        Args:
            ctx: Lint context with access to pages, edges, and memories.

        Returns:
            List of (memory_a, memory_b) tuples, each a dict from ctx.memories().
        """
        memories = await ctx.memories()
        edges = await ctx.edges()

        # Build a map from target concept_id to list of sources
        target_to_sources: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            src = edge.get("src")
            dst = edge.get("dst")
            if src and dst:
                target_to_sources.setdefault(dst, []).append(src)

        # Group memories by their linked targets
        memory_groups: dict[str, list[dict[str, Any]]] = {}
        for memory in memories:
            # Find all edges where this memory is the source
            for edge in edges:
                if edge.get("src") == memory.get("concept_id"):
                    target = edge.get("dst")
                    if target:
                        memory_groups.setdefault(target, []).append(memory)

        # Build candidate pairs from groups with at least 2 memories
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for group in memory_groups.values():
            if len(group) >= 2:
                # All pairs in this group
                for i in range(len(group)):
                    for j in range(i + 1, len(group)):
                        candidates.append((group[i], group[j]))

        # Rank by shared links (number of edges between the two memories)
        def shared_links(a: dict[str, Any], b: dict[str, Any]) -> int:
            a_id = a.get("concept_id", "")
            b_id = b.get("concept_id", "")
            count = 0
            for edge in edges:
                if edge.get("src") == a_id and edge.get("dst") == b_id:
                    count += 1
                if edge.get("src") == b_id and edge.get("dst") == a_id:
                    count += 1
            return count

        # Sort by shared links descending, then by concept_id ascending
        candidates.sort(
            key=lambda pair: (
                -shared_links(pair[0], pair[1]),
                pair[0].get("concept_id", ""),
                pair[1].get("concept_id", ""),
            )
        )

        # Cap at max_pairs
        return candidates[: self.max_pairs]

    async def _judge(self, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        """Ask the LLM whether two memories contradict.

        Args:
            a: First memory dict.
            b: Second memory dict.

        Returns:
            JSON dict with 'contradicts' (bool) and 'explanation' (str).
        """
        a_id = a.get("concept_id", "")
        b_id = b.get("concept_id", "")
        a_title = a.get("title", "")
        b_title = b.get("title", "")

        prompt = f"""Determine whether the following two memories about the same page contradict.

Memory A:
- Concept ID: {a_id}
- Title: {a_title}

Memory B:
- Concept ID: {b_id}
- Title: {b_title}

Return a JSON object with:
- "contradicts": true if they contradict, false otherwise
- "explanation": a brief explanation (max 200 characters)

Example:
{{"contradicts": true, "explanation": "A says X, B says not X"}}
"""

        response = await asyncio.wait_for(
            self.client.ask(
                prompt=prompt,
                model=self.client.model,
                max_tokens=256,
                temperature=0.0,
            ),
            timeout=self.timeout_s,
        )

        # Parse response defensively
        try:
            # Extract JSON from response text (in case of markdown code blocks)
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            result = json.loads(text)
        except (json.JSONDecodeError, AttributeError) as exc:
            # Malformed response is a skip, not a crash
            return {"contradicts": False, "explanation": f"Failed to parse LLM response: {exc}"}

        # Validate required fields
        if not isinstance(result, dict):
            return {"contradicts": False, "explanation": "LLM response is not a JSON object"}
        if "contradicts" not in result or "explanation" not in result:
            return {"contradicts": False, "explanation": "LLM response missing required fields"}

        return result

    async def check(self, ctx: LintContext) -> list[Finding]:
        """Run the contradiction check and return findings.

        On ANY exception, return a single llm-skipped info finding.

        Args:
            ctx: Lint context.

        Returns:
            List of findings (contradiction-llm warnings or llm-skipped info).
        """
        try:
            pairs = await self._pairs(ctx)
            findings: list[Finding] = []

            for a, b in pairs:
                # A client failure propagates to the outer handler -> single llm-skipped finding.
                verdict = await self._judge(a, b)
                if verdict.get("contradicts", False):
                    explanation = verdict.get("explanation", "No explanation provided")
                    a_id = a.get("concept_id", "")
                    b_id = b.get("concept_id", "")
                    findings.append(
                        Finding(
                            rule_id=self.rule_id,
                            severity=self.default_severity,
                            subjects=[a_id, b_id],
                            message=f"Contradiction between memory '{a_id}' and memory '{b_id}': {explanation}",
                            fingerprint=make_fingerprint(self.rule_id, [a_id, b_id]),
                            data={"memory_a": a_id, "memory_b": b_id, "explanation": explanation},
                        )
                    )

            return findings
        except Exception as exc:  # noqa: BLE001 — any failure is a skip
            # Return a single llm-skipped info finding
            return [
                Finding(
                    rule_id="llm-skipped",
                    severity="info",
                    subjects=[],
                    message=f"LLM contradiction check skipped: {exc}",
                    fingerprint=make_fingerprint("llm-skipped", []),
                    data={"error": str(exc)},
                )
            ]

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        """No automatic fix for contradiction-llm findings.

        Args:
            ctx: Lint context.
            finding: The finding to fix.

        Returns:
            None — this rule does not provide fixes.
        """
        return None


def build_llm_rule(options: LintOptions) -> ContradictionLLMRule | None:
    """Create the rule with a temperature-0 client, or None when no model is configured.

    Args:
        options: Lint options containing llm_model and llm_max_pairs.

    Returns:
        ContradictionLLMRule instance or None if no model is configured.
    """
    spec = resolve_lint_llm_spec(options.llm_model)
    if not spec:
        return None

    client = LLMFactory.create(spec, model_args={"temperature": 0.0})
    return ContradictionLLMRule(client, max_pairs=options.llm_max_pairs)
