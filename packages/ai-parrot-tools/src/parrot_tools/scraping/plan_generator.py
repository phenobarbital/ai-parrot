"""
PlanGenerator — LLM-based scraping plan generation.

Builds a prompt from a page snapshot, calls the LLM client, and parses
the JSON response into a ScrapingPlan.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, Optional

from .page_snapshot import PageSnapshot, fetch_snapshot
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

DOM STRUCTURE (pruned outline; identical repeating siblings are collapsed
with ``(×N more identical siblings)``. Every class/id/data-*/aria-*/role
shown here is verified to exist on the page — base your selectors on
these, not on guesses):
{structure}

Element landmarks:
{element_hints}

Available links:
{links}

Respond ONLY with a valid JSON object matching this schema:
{schema_json}

Rules:
- Use CSS selectors unless an XPath is clearly more reliable.
- Every selector MUST be grounded in the DOM STRUCTURE block above.
  Only use class names, ids, data-* attributes, aria-* attributes, and
  roles that appear verbatim in the outline. Do NOT invent
  ``[data-testid='...']``, ``.plan-card``, or similar if they are not
  shown. Repeating card/row patterns are the lines with
  ``(×N more identical siblings)`` — those are your row selectors.
- COPY ATTRIBUTE VALUES VERBATIM. If the outline shows
  ``[data-comp='accordion-duc']``, your selector MUST write
  ``[data-comp='accordion-duc']`` — NOT ``[data-comp='accordion']``,
  NOT ``[data-comp*='accordion']`` (unless you see multiple variants),
  NOT ``[data-comp='accordionDuc']``. LLMs tend to truncate or
  "normalize" attribute values they find ugly (``-duc``, ``-v3``,
  random hashes); resist that instinct. The exact value in the
  snapshot is the one that actually matches on the page. Same rule
  for class tokens (``jsx-1609713937`` is not a typo — copy it if it
  exists in the snapshot).
- To pick a ROW selector for a ``multiple: true`` extract: find the
  collapsed sibling run in DOM STRUCTURE, and use that exemplar's
  tag + (class OR data-*) as the selector. Example: outline shows
  ``li.plan-tile [data-plan-id='go']`` with
  ``(×4 more identical siblings)`` → row selector is ``li.plan-tile``.
- To pick FIELD sub-selectors: look at the children of the exemplar
  row in the outline. Choose the child whose name/class matches
  the field (e.g. ``h3`` for title, ``span.price`` for price).
- Prefer data-* attributes and IDs over class names WHEN they exist in the
  snapshot. Class-name contains (``[class*='...']``) is a last resort.
- ONE selector per field. Do NOT comma-union hedge selectors
  (``h3, h4, [class*='title'], [class*='name']``) in the hope that one
  will match — the broadest variant almost always matches a too-large
  ancestor and swallows the whole row's text into every field. Pick the
  single most specific selector supported by the snapshot. If you
  genuinely cannot tell, leave the field out rather than union guesses.
- The parent/row selector in a ``fields`` extraction MUST match exactly
  one kind of element (e.g. a single card variant). Do not combine
  ``article, li, [class*='item'], [class*='card']`` — that pulls in
  unrelated list items and poisons the fields. Pick the one that the
  snapshot or page actually uses.
- ``wait`` and ``click`` selectors run in the browser via Selenium's
  native CSS — NONE of these pseudo-classes work there:
  ``:contains(...)``, ``:-soup-contains(...)``, ``:has(...)``. Using
  them will crash the step with an InvalidSelectorException. Stick to
  standard CSS: tag + attribute combos, ``nth-of-type``, classes, ids.
  For text-based click targeting use one of these instead:
    * Prefer an aria-label match: ``button[aria-label*='More plans']``
    * Or emit ``selector_type: "xpath"`` with
      ``//button[contains(normalize-space(.), 'More plans')]``
    * Or emit ``selector_type: "text"`` with the literal text as
      ``selector``.
  ``:-soup-contains(...)`` IS allowed inside ``extract`` selectors
  because extraction runs through BeautifulSoup.
- ``wait`` steps are ONLY for content that requires JavaScript rendering
  or async loading (SPA hydration, XHR-loaded lists, lazy-rendered
  carousels). Do NOT add ``wait`` after every navigation by default — on
  server-rendered pages the DOM is already present after ``navigate``.
  Use ``wait`` only when (a) the target element is known to be JS-rendered,
  or (b) a prior ``click`` / ``scroll`` triggers deferred content.
- When the OBJECTIVE mentions an interactive toggle / switch / tab /
  "show more" / "view all" / accordion "expand" control, generate a
  ``click`` step BEFORE the relevant ``extract`` so the content those
  controls reveal is actually in the DOM. Anchor the click on visible
  text or aria-label from the snapshot (e.g. a button whose label
  contains "More great plans" or "View all").
- Expandable accordion items (FAQ, product details) are usually
  present in the DOM even when collapsed — check the snapshot before
  adding click-to-expand steps. If ``aria-expanded='false'`` appears
  on the buttons in the outline, emit one ``click`` with
  ``multiple: true`` to open them all; otherwise extract directly.
- ``wait.timeout`` is expressed in SECONDS (typical 5-30), never
  milliseconds.
- If pagination is needed, include a loop action.
- EXTRACTION — two valid forms:
  (a) Step-level ``extract`` action, executed at its position in the
      plan (use this when data only exists AFTER a click/scroll):
        {{
          "action": "extract",
          "extract_name": "prepaid_plans",
          "selector": "<CSS for row element>",
          "multiple": true,
          "fields": {{
            "plan_name":  {{"selector": "h3", "extract_type": "text"}},
            "price":      {{"selector": ".price", "extract_type": "text"}},
            "cta_link":   {{"selector": "a.btn", "extract_type": "attribute", "attribute": "href"}}
          }}
        }}
      Field selectors run RELATIVE to each row element. ``extract_name``
      becomes the key in extracted_data; the step's top-level ``name``
      field is a free-form label and is IGNORED for dispatch.
  (b) Top-level ``plan.selectors`` list, applied once at the end
      against the final DOM. Flat entries only (no ``fields``). Prefer
      this for simple one-shot extraction against the final page state.
- Each row's sub-field uses ``extract_type`` ("text"|"html"|"attribute")
  plus ``attribute`` for link hrefs / src / etc. Do NOT put ``"text"``
  or ``"html"`` in the ``attribute`` field — those are extract_type
  values, not attribute names.
- Set browser_config only if non-default settings are required.
"""


PLAN_REFINEMENT_PROMPT = """\
You are a web scraping expert. Your previous plan for this URL produced
weak or incomplete results. Study what went wrong and emit a REVISED
plan that addresses the specific failures.

URL: {url}
OBJECTIVE: {objective}

PRIOR PLAN (the one that underperformed):
{prior_plan_json}

EXECUTION RESULTS FROM THE PRIOR PLAN:
Extraction summary:
{extraction_summary}
Step errors / warnings:
{step_errors}

Quality diagnosis (what the scoring function flagged):
{diagnosis}

CURRENT DOM STATE (snapshot taken AFTER the prior plan ran, so it
reflects any clicks / scrolls / expansions already applied):
Title: {title}
Text excerpt: {text_excerpt}

DOM STRUCTURE:
{structure}

Element landmarks:
{element_hints}

Common failure modes — check if any apply:
- Empty row list → the row selector didn't match. Pick a different
  attribute from the DOM STRUCTURE (data-*, aria-label, a verified id).
- All rows captured but fields are null → field selectors are wrong.
  Anchor each field on a specific child class/tag visible inside the
  first exemplar row in DOM STRUCTURE.
- Too few rows (e.g. 3 instead of 5) → there may be a tab/toggle or a
  "View more" / "Show all" button in the DOM STRUCTURE. Extract BEFORE
  AND AFTER the click using the same ``extract_name`` (the executor
  appends+dedupes across same-name extracts).
- Step errors like ``ElementClickInterceptedException`` → the executor
  now auto-dismisses common cookie/privacy banners, so don't worry
  about those specifically; but your click selector might still target
  the wrong element.
- Wait step timed out → your selector uses a BS4-only pseudo-class
  (``:contains``, ``:-soup-contains``, ``:has``) in a Selenium-side
  step, or the element simply isn't there. Use verified selectors
  from DOM STRUCTURE.
- FAQ-style accordion returns 0 rows → the section is likely inside
  a ``lazyload-wrapper``. Add a ``scroll`` step with
  ``direction: "bottom"`` before the FAQ extract (chunked scroll is
  automatic for bottom).

Respond ONLY with a valid JSON object matching this schema:
{schema_json}

All the rules from the ORIGINAL plan prompt still apply (verbatim
attribute values, no comma-unioned selectors, standard CSS for
wait/click, etc.).
"""


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
        auto_snapshot: bool = True,
        snapshot_fetcher: Optional[
            Callable[[str], Any]
        ] = None,
    ) -> ScrapingPlan:
        """Generate a scraping plan via LLM inference.

        When ``snapshot`` is not provided and ``auto_snapshot`` is True,
        the generator fetches the page via a lightweight ``aiohttp`` GET
        and builds a snapshot from the HTML. Fetch failures degrade to
        an empty snapshot rather than raising.

        Args:
            url: Target URL to scrape.
            objective: Natural language goal for the scraping operation.
            snapshot: Pre-built snapshot (skips auto-fetch when provided).
            hints: Optional dict of hints to bias plan generation.
            auto_snapshot: If True and no snapshot is supplied, fetch one
                from ``url`` before prompting the LLM.
            snapshot_fetcher: Optional async callable ``(url) -> PageSnapshot``
                used instead of the default aiohttp-based fetcher. Use
                this to inject a browser-driven fetcher for JS pages.

        Returns:
            A validated ``ScrapingPlan`` parsed from the LLM response.

        Raises:
            ValueError: If the LLM response cannot be parsed into a valid plan.
        """
        if snapshot is None and auto_snapshot:
            fetcher = snapshot_fetcher or fetch_snapshot
            try:
                snapshot = await fetcher(url)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Snapshot fetch for %s failed (%s); proceeding without snapshot",
                    url, exc,
                )
                snapshot = None
            if snapshot is not None:
                self.logger.info(
                    "Snapshot for %s: title=%r, text=%dc, hints=%d lines, "
                    "structure=%dc (%d lines), links=%d lines",
                    url,
                    snapshot.title,
                    len(snapshot.text_excerpt),
                    snapshot.element_hints.count("\n") + bool(snapshot.element_hints),
                    len(snapshot.structure),
                    snapshot.structure.count("\n") + bool(snapshot.structure),
                    snapshot.links.count("\n") + bool(snapshot.links),
                )

        prompt = self._build_prompt(url, objective, snapshot, hints)
        self.logger.debug("Sending plan generation prompt for %s", url)
        raw_response = await self._client.complete(prompt)
        self.logger.debug("Received LLM response (%d chars)", len(raw_response))
        return self._parse_response(raw_response, url, objective)

    async def refine(
        self,
        url: str,
        objective: str,
        prior_plan: ScrapingPlan,
        extraction_summary: str,
        step_errors: str,
        diagnosis: str,
        snapshot: Optional[PageSnapshot] = None,
    ) -> ScrapingPlan:
        """Regenerate a plan given the failure signals from a prior run.

        The prompt shows the LLM its previous plan, what came out of the
        extractor, what step errors fired, and a FRESH DOM snapshot
        captured after the prior plan ran — so it reflects any clicks /
        scrolls / expansions already applied. Expected to return a full
        replacement plan that corrects the mistakes.

        Args:
            url: Target URL.
            objective: Original scraping objective.
            prior_plan: The plan that produced weak results.
            extraction_summary: Human-readable summary of what came out
                (row counts, null-field ratios, example values).
            step_errors: Summary of failed steps (one line each) — may
                be empty string when everything ran but extracted little.
            diagnosis: Scoring function's reasons (e.g.
                ``"faq: 0 rows; prepaid_plans: 3 rows, 40% empty fields"``).
            snapshot: Post-execution DOM snapshot for the LLM to anchor
                new selectors on.

        Returns:
            A refined ``ScrapingPlan`` (full replacement, not a diff).
        """
        snap = snapshot or PageSnapshot()
        schema_json = json.dumps(ScrapingPlan.model_json_schema(), indent=2)
        prior_json = json.dumps(
            prior_plan.model_dump(mode="json"), indent=2, default=str
        )
        # Truncate prior plan if absurdly long — the structure is what
        # matters, not every selector detail
        if len(prior_json) > 6000:
            prior_json = prior_json[:6000] + "\n... (truncated)"

        prompt = PLAN_REFINEMENT_PROMPT.format(
            url=url,
            objective=objective,
            prior_plan_json=prior_json,
            extraction_summary=extraction_summary or "(none)",
            step_errors=step_errors or "(none)",
            diagnosis=diagnosis or "(none)",
            title=snap.title,
            text_excerpt=snap.text_excerpt,
            structure=snap.structure or "(no structure captured)",
            element_hints=snap.element_hints or "(none)",
            schema_json=schema_json,
        )
        self.logger.info("Sending refinement prompt for %s", url)
        raw_response = await self._client.complete(prompt)
        self.logger.debug(
            "Received refinement LLM response (%d chars)", len(raw_response)
        )
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
            structure=snap.structure or "(no structure captured)",
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
