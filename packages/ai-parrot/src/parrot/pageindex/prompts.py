"""Prompt templates for the Two-Step Chain-of-Thought ingest pipeline."""
from __future__ import annotations

INGEST_STEP1_SYSTEM = (
    "You are a documentation analyst. You reason step-by-step about a chunk "
    "of raw content the user wants to ingest into a knowledge tree."
)

INGEST_STEP1_USER = """Hint (optional): {hint}

Content (may be truncated):
<<<{content}>>>

Produce a Chain-of-Thought analysis covering:
1. Document type / genre.
2. Main topics covered.
3. A concise H1 title for this document.
4. A proposed H2 outline (3-10 sections) with one-line descriptions.

Respond as plain prose. Do not output JSON or code fences.
"""


INGEST_STEP2_SYSTEM = (
    "You produce clean, hierarchical markdown for a knowledge index. "
    "You preserve facts, names and numbers from the source and do not "
    "invent information that is not present in it."
)

INGEST_STEP2_USER = """Hint (optional): {hint}

Prior analysis from a previous reasoning step:
{analysis}

Raw content to convert:
<<<{content}>>>

Return a JSON object matching this schema:
{{
  "title": "<H1 title for this document>",
  "summary": "<one or two sentence summary>",
  "markdown": "<the full markdown body>"
}}

The "markdown" field must contain:
- exactly one top-level "# " header (the document title);
- H2 ("## ") sections matching the proposed outline;
- well-formed body text under each section;
- no surrounding code fences.
"""
