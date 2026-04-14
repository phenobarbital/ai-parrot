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
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from .extraction_models import ExtractionPlan
from .plan_generator import _strip_code_fences, _extract_json_object


# ---------------------------------------------------------------------------
# Curated schema example shown to the LLM.
# Using a hand-written example (rather than the full Pydantic JSON Schema)
# keeps the prompt concise and easier for the LLM to follow.
# ---------------------------------------------------------------------------
_EXAMPLE_SCHEMA = json.dumps(
    {
        "url": "https://example.com/plans",
        "objective": "Extract mobile plans from this page",
        "page_category": "telecom_prepaid_plans",
        "extraction_strategy": "hybrid",
        "entities": [
            {
                "entity_type": "plan",
                "description": "A mobile plan offering",
                "repeating": True,
                "container_selector": ".plan-card",
                "fields": [
                    {
                        "name": "plan_name",
                        "description": "Name of the plan",
                        "field_type": "text",
                        "required": True,
                        "selector": "h2, .plan-title",
                        "extract_from": "text",
                    },
                    {
                        "name": "monthly_price",
                        "description": "Monthly recurring cost",
                        "field_type": "currency",
                        "required": True,
                        "selector": ".price, [class*='price']",
                        "extract_from": "text",
                    },
                    {
                        "name": "plan_url",
                        "description": "Link to the plan detail page",
                        "field_type": "url",
                        "required": False,
                        "selector": "a.cta",
                        "extract_from": "attribute",
                        "attribute": "href",
                    },
                ],
            }
        ],
        "ignore_sections": ["nav", "footer", ".advertisement"],
    },
    indent=2,
)


RECON_PROMPT = """\
You are a web content analysis expert specializing in structured data extraction.
Analyze the HTML content below and generate an ExtractionPlan to extract the requested entities.

URL: {url}
OBJECTIVE: {objective}
HINTS: {hints}

HTML CONTENT:
{content}

Respond ONLY with a valid JSON object using this exact shape (adjust values for the page):
{schema_example}

Rules:
- Identify all relevant entity types visible on the page
- Use CSS selectors that include class names for accuracy
- For repeating elements (e.g. product cards, plan listings), set repeating=true and provide container_selector
- Field names must be snake_case (e.g. plan_name, monthly_price)
- Prefer specific class selectors over generic tag selectors
- For url-type fields set extract_from="attribute" and attribute="href" or "src"
- Set page_category to a descriptive string like "telecom_prepaid_plans" or "ecommerce_products"
- List CSS selectors for noisy sections (nav, footer, ads) in ignore_sections
- field_type must be one of: text, number, currency, url, boolean, list
- extraction_strategy must be one of: hybrid, selector, llm
"""

# Default noise selectors always removed from HTML before sending to the LLM.
_DEFAULT_NOISE_SELECTORS: List[str] = [
    "nav", "footer", "header", ".cookie-banner", ".advertisement",
    ".sidebar", ".breadcrumb", "[role='banner']", "[role='navigation']",
]


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
        ignore_sections: Optional[List[str]] = None,
    ) -> ExtractionPlan:
        """Generate an ExtractionPlan via LLM reconnaissance.

        Cleans the HTML (applying ``ignore_sections`` to strip noise), builds
        the recon prompt, calls the LLM, and parses the JSON response into a
        validated ``ExtractionPlan``.

        Args:
            url: Target URL being analyzed.
            objective: Natural language goal for extraction.
            content: Raw HTML content of the page.
            hints: Optional dict of hints to bias plan generation.
            ignore_sections: Optional list of CSS selectors for page sections
                to strip before sending HTML to the LLM (e.g. from a
                pre-existing ExtractionPlan's ``ignore_sections`` field).

        Returns:
            Validated ExtractionPlan parsed from LLM response.

        Raises:
            ValueError: If the LLM response cannot be parsed into a valid plan.
        """
        cleaned = self._clean_html_content(content, ignore_sections=ignore_sections)
        prompt = self._build_prompt(url, objective, cleaned, hints)
        self.logger.debug("Sending recon prompt for %s", url)
        raw_response = await self._client.complete(prompt)
        self.logger.debug("Received LLM response (%d chars)", len(raw_response))
        return self._parse_response(raw_response, url, objective)

    def _clean_html_content(
        self,
        html: str,
        max_chars: int = 32000,
        ignore_sections: Optional[List[str]] = None,
    ) -> str:
        """Clean HTML for LLM input. Preserves structure and CSS classes.

        Removes noise tags (script, style, noscript, link, meta), applies
        ``ignore_sections`` selectors, extracts the ``<main>`` /
        ``<article>`` / ``<body>`` section, and truncates to ``max_chars``
        (~8K tokens) to stay within LLM context limits.

        Truncation happens at the last ``<`` tag boundary to avoid sending
        malformed mid-tag HTML to the LLM.

        Args:
            html: Raw HTML string.
            max_chars: Maximum character count (approximates ~8K tokens).
            ignore_sections: Extra CSS selectors for sections to strip (in
                addition to the built-in noise list).

        Returns:
            Cleaned HTML string with noise tags removed.
        """
        soup = BeautifulSoup(html, "html.parser")

        # Remove built-in noise tags
        for tag in soup.find_all(["script", "style", "noscript", "link", "meta"]):
            tag.decompose()

        # Apply ignore_sections selectors (default noise + caller-supplied)
        all_noise = list(_DEFAULT_NOISE_SELECTORS)
        if ignore_sections:
            all_noise.extend(ignore_sections)
        for selector in all_noise:
            try:
                for node in soup.select(selector):
                    node.decompose()
            except Exception:
                pass  # ignore invalid selectors

        # Try to extract the main content section
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main is None:
            main = soup
        result = str(main)

        # Truncate at a tag boundary to avoid mid-tag cuts
        if len(result) > max_chars:
            truncated = result[:max_chars]
            # Walk back to the last '<' to avoid splitting a tag
            last_tag = truncated.rfind("<")
            if last_tag > max_chars // 2:
                truncated = truncated[:last_tag]
            result = truncated + "<!-- content truncated -->"

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
        return RECON_PROMPT.format(
            url=url,
            objective=objective,
            hints=json.dumps(hints) if hints else "None",
            content=content,
            schema_example=_EXAMPLE_SCHEMA,
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
