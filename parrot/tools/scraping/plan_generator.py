"""
PlanGenerator — LLM-based scraping plan generation.

Builds a prompt from a page snapshot, calls the LLM client, and parses
the JSON response into a ScrapingPlan.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from .plan import ScrapingPlan

logger = logging.getLogger(__name__)

PLAN_GENERATION_PROMPT = """\
You are a web scraping expert. Given the following page snapshot, generate
a scraping plan to achieve the stated objective.

URL: {url}
OBJECTIVE: {objective}
HINTS: {hints}

PAGE SNAPSHOT:
Title: {title}
Text excerpt: {text_excerpt}
Element hints: {element_hints}
Available links: {links}

Respond ONLY with a valid JSON object matching this schema:
{schema_json}

Rules:
- Use CSS selectors unless an XPath is clearly more reliable.
- Prefer data-* attributes and IDs over class names.
- Include a wait step after every navigation.
- If pagination is needed, include a loop action.
- Set browser_config only if non-default settings are required.
"""


class PageSnapshot:
    """Lightweight page data for LLM prompt building.

    Args:
        title: Page title.
        text_excerpt: First ~2000 chars of visible text.
        element_hints: Tag/id/class hints for page elements.
        links: Up to 50 link hrefs found on the page.
    """

    def __init__(
        self,
        title: str = "",
        text_excerpt: str = "",
        element_hints: str = "",
        links: str = "",
    ) -> None:
        self.title = title
        self.text_excerpt = text_excerpt
        self.element_hints = element_hints
        self.links = links


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM response.

    Handles patterns like:
        ```json\n{...}\n```
        ```\n{...}\n```

    Args:
        text: Raw LLM response text.

    Returns:
        Text with code fences removed.
    """
    # Match ```json\n...\n``` or ```\n...\n```
    pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _extract_json_object(text: str) -> str:
    """Extract the first JSON object from text.

    Finds the first ``{`` and matches it to its closing ``}``.

    Args:
        text: Text that may contain a JSON object.

    Returns:
        The extracted JSON string.

    Raises:
        ValueError: If no JSON object is found.
    """
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")

    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise ValueError("Unterminated JSON object in response")


class PlanGenerator:
    """Generates ScrapingPlan from URL + objective using an LLM client.

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
        snapshot: Optional[PageSnapshot] = None,
        hints: Optional[Dict[str, Any]] = None,
    ) -> ScrapingPlan:
        """Generate a scraping plan via LLM inference.

        Args:
            url: Target URL to scrape.
            objective: Natural language goal for the scraping operation.
            snapshot: Optional page snapshot data for context.
            hints: Optional dict of hints to bias plan generation.

        Returns:
            A validated ``ScrapingPlan`` parsed from the LLM response.

        Raises:
            ValueError: If the LLM response cannot be parsed into a valid plan.
        """
        prompt = self._build_prompt(url, objective, snapshot, hints)
        self.logger.debug("Sending plan generation prompt for %s", url)
        raw_response = await self._client.complete(prompt)
        self.logger.debug("Received LLM response (%d chars)", len(raw_response))
        return self._parse_response(raw_response, url, objective)

    def _build_prompt(
        self,
        url: str,
        objective: str,
        snapshot: Optional[PageSnapshot] = None,
        hints: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the LLM prompt from inputs.

        Args:
            url: Target URL.
            objective: Scraping goal.
            snapshot: Page snapshot data (uses empty values if None).
            hints: Optional generation hints.

        Returns:
            Formatted prompt string.
        """
        snap = snapshot or PageSnapshot()
        schema_json = json.dumps(
            ScrapingPlan.model_json_schema(), indent=2
        )
        return PLAN_GENERATION_PROMPT.format(
            url=url,
            objective=objective,
            hints=json.dumps(hints) if hints else "None",
            title=snap.title,
            text_excerpt=snap.text_excerpt,
            element_hints=snap.element_hints,
            links=snap.links,
            schema_json=schema_json,
        )

    def _parse_response(
        self, raw: str, url: str, objective: str
    ) -> ScrapingPlan:
        """Parse LLM JSON response into a ScrapingPlan.

        Handles common LLM quirks: markdown code fences, extra text
        around the JSON object.

        Args:
            raw: Raw LLM response string.
            url: Original URL (used as fallback if not in response).
            objective: Original objective (used as fallback).

        Returns:
            Validated ``ScrapingPlan``.

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

        # Ensure required fields are present
        if "url" not in data:
            data["url"] = url
        if "objective" not in data:
            data["objective"] = objective
        if "steps" not in data:
            raise ValueError(
                "LLM response missing required 'steps' field.\n"
                f"Parsed data keys: {list(data.keys())}"
            )

        try:
            plan = ScrapingPlan.model_validate(data)
        except Exception as exc:
            raise ValueError(
                f"LLM response failed ScrapingPlan validation: {exc}\n"
                f"Parsed data: {json.dumps(data, indent=2, default=str)[:500]}"
            ) from exc

        plan.source = "llm"
        return plan
