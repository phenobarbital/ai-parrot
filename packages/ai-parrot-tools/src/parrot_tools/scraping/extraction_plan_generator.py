"""
ExtractionPlanGenerator — LLM-based ExtractionPlan generation.

Analyzes raw HTML content and a natural language objective to produce an
``ExtractionPlan`` via a single LLM recon call.  The resulting plan
specifies entity types, fields, and CSS selectors derived from the page
structure.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from bs4 import BeautifulSoup

from .extraction_models import ExtractionPlan
from .plan_generator import _strip_code_fences, _extract_json_object


RECON_PROMPT = """\
You are a web content analysis expert specializing in structured data extraction.
Analyze the HTML content below and generate an ExtractionPlan to extract the requested entities.

URL: {url}
OBJECTIVE: {objective}
HINTS: {hints}

HTML CONTENT:
{content}

Respond ONLY with a valid JSON object matching this schema:
{schema_json}

Rules:
- Identify all relevant entity types visible on the page
- Use CSS selectors that include class names for accuracy
- For repeating elements (e.g., product cards, plan listings), set repeating=true and provide container_selector
- Field names should be snake_case (e.g., plan_name, monthly_price)
- Prefer specific class selectors over generic tag selectors
- If multiple selector options exist, prefer the most specific one
- Set page_category to a descriptive string like "telecom_prepaid_plans" or "ecommerce_products"
"""


class ExtractionPlanGenerator:
    """Generates ExtractionPlan from HTML content + objective using LLM reconnaissance.

    Makes a single LLM call with a cleaned version of the page HTML and the
    extraction objective.  The LLM is prompted to identify entity types and
    emit CSS selectors that can be used for mechanical extraction.

    The LLM client must support ``async def complete(prompt: str) -> str``.

    Args:
        llm_client: Any object with an async ``complete(prompt)`` method.
    """

    def __init__(self, llm_client: Any) -> None:
        self._client = llm_client
        self.logger = logging.getLogger(__name__)

    async def generate(
        self,
        url: str,
        objective: str,
        content: str,
        hints: Optional[Dict[str, Any]] = None,
    ) -> ExtractionPlan:
        """Generate an ExtractionPlan via LLM reconnaissance.

        Cleans the HTML, builds the recon prompt, calls the LLM, and parses
        the JSON response into a validated ``ExtractionPlan``.

        Args:
            url: Target URL being analyzed.
            objective: Natural language goal for extraction.
            content: Raw HTML content of the page.
            hints: Optional dict of hints to bias plan generation.

        Returns:
            Validated ExtractionPlan parsed from LLM response.

        Raises:
            ValueError: If the LLM response cannot be parsed into a valid plan.
        """
        cleaned = self._clean_html_content(content)
        prompt = self._build_prompt(url, objective, cleaned, hints)
        self.logger.debug("Sending recon prompt for %s", url)
        raw_response = await self._client.complete(prompt)
        self.logger.debug("Received LLM response (%d chars)", len(raw_response))
        return self._parse_response(raw_response, url, objective)

    def _clean_html_content(self, html: str, max_chars: int = 32000) -> str:
        """Clean HTML for LLM input. Preserves structure and CSS classes.

        Removes noise tags (script, style, noscript, link, meta) and extracts
        the ``<main>`` / ``<article>`` / ``<body>`` section.  Truncates to
        ``max_chars`` (~8K tokens) to stay within LLM context limits.

        Args:
            html: Raw HTML string.
            max_chars: Maximum character count (approximates ~8K tokens).

        Returns:
            Cleaned HTML string with noise tags removed.
        """
        soup = BeautifulSoup(html, "html.parser")
        # Remove noise tags
        for tag in soup.find_all(["script", "style", "noscript", "link", "meta"]):
            tag.decompose()
        # Try to extract main content
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main is None:
            main = soup
        result = str(main)
        # Truncate
        if len(result) > max_chars:
            result = result[:max_chars]
        return result

    def _build_prompt(
        self,
        url: str,
        objective: str,
        content: str,
        hints: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the LLM reconnaissance prompt.

        Args:
            url: Target URL.
            objective: Extraction goal.
            content: Cleaned HTML content.
            hints: Optional generation hints.

        Returns:
            Formatted prompt string.
        """
        schema_json = json.dumps(ExtractionPlan.model_json_schema(), indent=2)
        return RECON_PROMPT.format(
            url=url,
            objective=objective,
            hints=json.dumps(hints) if hints else "None",
            content=content,
            schema_json=schema_json,
        )

    def _parse_response(self, raw: str, url: str, objective: str) -> ExtractionPlan:
        """Parse LLM JSON response into an ExtractionPlan.

        Handles markdown code fences and extracts the first JSON object from
        the response.  Falls back to the provided ``url`` and ``objective`` if
        the LLM omitted them.

        Args:
            raw: Raw LLM response string.
            url: Original URL (used as fallback).
            objective: Original objective (used as fallback).

        Returns:
            Validated ExtractionPlan.

        Raises:
            ValueError: If JSON parsing or plan validation fails.
        """
        cleaned = _strip_code_fences(raw)
        try:
            json_str = _extract_json_object(cleaned)
            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(
                f"Failed to parse LLM response as JSON: {exc}\n"
                f"Raw response (first 500 chars): {raw[:500]}"
            ) from exc

        if "url" not in data or not data["url"]:
            data["url"] = url
        if "objective" not in data or not data["objective"]:
            data["objective"] = objective
        if "entities" not in data:
            data["entities"] = []

        try:
            plan = ExtractionPlan.model_validate(data)
        except Exception as exc:
            raise ValueError(
                f"LLM response failed ExtractionPlan validation: {exc}\n"
                f"Parsed data: {json.dumps(data, indent=2, default=str)[:500]}"
            ) from exc

        plan.source = "llm"
        return plan
