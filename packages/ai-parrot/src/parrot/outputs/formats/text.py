"""Plain-text output renderer (``OutputMode.TEXT``).

Markdown-free conversational text for surfaces that render message text
literally — most notably Microsoft Copilot consuming a Parrot agent over
the A2A protocol, where markdown in an A2A ``TextPart`` shows up as raw
``**bold**`` and ``| pipe |`` tables.

Two levers fire from this single mode:

- ``PLAIN_TEXT_SYSTEM_PROMPT`` is injected into the system prompt
  (``formatter.get_system_prompt()``) so the LLM is asked to answer in
  plain text in the first place.
- :class:`PlainTextRenderer` post-processes the response through
  :func:`markdown_to_plain`, deterministically flattening any markdown
  the model (or a tool) still emitted.
"""
import re
from typing import Any, List, Optional, Tuple

from . import register_renderer
from .base import BaseRenderer
from ...models.outputs import OutputMode


PLAIN_TEXT_SYSTEM_PROMPT = (
    "PLAIN TEXT OUTPUT MODE: Reply in plain conversational text only. "
    "Do NOT use markdown formatting of any kind: no headers (#), no bold "
    "(**text**) or italics (*text*), no pipe tables (| a | b |), no code "
    "fences (```), no inline code (`x`), and no [text](url) links. "
    "Write short sentences and paragraphs. Present lists as lines starting "
    "with a hyphen. Present tabular facts as 'Label: value' lines, one per "
    "line. Write URLs literally."
)

# A table-separator cell: optional colons around 1+ dashes (":---", "---:", "-").
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")
# A horizontal rule: a line made only of 3+ dashes/asterisks/underscores.
_HORIZONTAL_RULE = re.compile(r"^\s{0,3}([-*_])\s*(?:\1\s*){2,}$")


def _split_row(line: str) -> List[str]:
    """Split a ``| a | b |`` markdown table row into stripped cells."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator_row(cells: List[str]) -> bool:
    """True when every cell looks like a table alignment separator."""
    return bool(cells) and all(_SEPARATOR_CELL.match(cell) for cell in cells if cell)


def _flatten_table(rows: List[List[str]], has_header: bool) -> List[str]:
    """Convert parsed table rows into plain 'Label: value' style lines.

    Two-column tables read naturally as ``<col1>: <col2>`` lines; wider
    tables emit one hyphen line per row pairing each header with its cell.
    """
    lines: List[str] = []
    headers: Optional[List[str]] = rows[0] if has_header else None
    data_rows = rows[1:] if has_header else rows

    if not data_rows:
        # Header-only table — keep the headers as a single readable line.
        return [", ".join(rows[0])] if rows else []

    width = max(len(r) for r in data_rows)
    if width <= 2:
        for row in data_rows:
            if len(row) >= 2:
                lines.append(f"{row[0]}: {row[1]}")
            elif row:
                lines.append(row[0])
    else:
        for row in data_rows:
            if headers:
                pairs = [
                    f"{headers[i]}: {cell}" if i < len(headers) and headers[i] else cell
                    for i, cell in enumerate(row)
                ]
            else:
                pairs = list(row)
            lines.append("- " + ", ".join(p for p in pairs if p))
    return lines


def _flatten_tables(text: str) -> str:
    """Replace markdown pipe tables in ``text`` with plain-text lines."""
    out: List[str] = []
    block: List[List[str]] = []
    block_has_header = False

    def flush() -> None:
        nonlocal block, block_has_header
        if block:
            out.extend(_flatten_table(block, block_has_header))
        block = []
        block_has_header = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            cells = _split_row(stripped)
            if _is_separator_row(cells):
                # Separator marks the previous row as the header row.
                if len(block) == 1:
                    block_has_header = True
                continue
            block.append(cells)
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out)


def markdown_to_plain(text: str) -> str:
    """Deterministically convert markdown to readable plain text.

    Handles fenced/inline code (content kept), bold/italic/strikethrough,
    ATX headings, blockquotes, horizontal rules, links/images
    (``text (url)``), bullet markers, and pipe tables (flattened to
    ``Label: value`` lines). Never raises — on any error the original
    text is returned unchanged.

    Args:
        text: Markdown (or mixed) text.

    Returns:
        A plain-text rendering of ``text``.
    """
    if not text:
        return ""
    try:
        # Fenced code blocks — keep the inner content verbatim.
        result = re.sub(r"```[\w+-]*\n?(.*?)```", r"\1", text, flags=re.DOTALL)
        # Pipe tables → 'Label: value' lines (before emphasis stripping so
        # cell content like **bold** is cleaned afterwards).
        result = _flatten_tables(result)
        # Images / links → "text (url)"
        result = re.sub(r"!?\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", r"\1 (\2)", result)
        # Headings → bare line
        result = re.sub(r"^\s{0,3}#{1,6}\s+", "", result, flags=re.MULTILINE)
        # Blockquotes
        result = re.sub(r"^\s{0,3}>\s?", "", result, flags=re.MULTILINE)
        # Horizontal rules → dropped
        result = "\n".join(
            line for line in result.splitlines() if not _HORIZONTAL_RULE.match(line)
        )
        # Bold / italic / strikethrough
        result = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", result)
        result = re.sub(r"(?<!\w)_{1,2}([^_\n]+)_{1,2}(?!\w)", r"\1", result)
        result = re.sub(r"~~([^~\n]+)~~", r"\1", result)
        # Inline code
        result = re.sub(r"`([^`\n]*)`", r"\1", result)
        # Bullet markers * / + → hyphen
        result = re.sub(r"^(\s*)[*+]\s+", r"\1- ", result, flags=re.MULTILINE)
        # Collapse runs of 3+ newlines
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()
    except Exception:  # noqa: BLE001 - converter must never break a reply
        return text


@register_renderer(OutputMode.TEXT, system_prompt=PLAIN_TEXT_SYSTEM_PROMPT)
class PlainTextRenderer(BaseRenderer):
    """Renderer for plain-text output — strips markdown from the reply."""

    def _extract_content(self, response: Any) -> str:
        """Extract text content from the agent response."""
        output = getattr(response, 'output', None)
        if output is not None:
            if hasattr(output, 'explanation') and output.explanation:
                return str(output.explanation)
            if hasattr(output, 'response') and output.response:
                return str(output.response)

        if hasattr(response, 'response') and response.response:
            return str(response.response)

        if output is not None:
            return output if isinstance(output, str) else str(output)

        return str(response)

    async def render(
        self,
        response: Any,
        environment: str = 'default',
        **kwargs,
    ) -> Tuple[str, Any]:
        """Render response as markdown-free plain text."""
        content = markdown_to_plain(self._extract_content(response))
        return content, content
