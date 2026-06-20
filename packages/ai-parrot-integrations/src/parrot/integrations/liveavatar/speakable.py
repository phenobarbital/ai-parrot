"""Speakable-text flattener and sentence segmenter (FEAT-242 Phase A — Module 4).

Converts markdown chunks streamed from the agent into speakable plaintext and
segments them into complete sentences for per-sentence streaming TTS.

**Shared with Phase C (FEAT-243).**

No avatar or TTS imports — this is a pure text utility (stdlib only).

Flattening strips:
- Code fences (``` ... ```)
- Inline code (` ... `)
- Tables (| col | ... |)
- Markdown headings (#, ##, …)
- Emphasis markers (*, **, _, __)
- List bullets (-, *, +, 1.)
- Links — keeps link text, drops URL (``[text](url)`` → ``text``)
- HTML tags (basic strip)
- Horizontal rules (---, ***, ___)

Sentence segmentation:
- Accumulates chunks across ``feed()`` calls.
- Emits a sentence only when terminal punctuation (.!?) is seen followed by
  whitespace or the end of the buffer.
- ``flush()`` emits any remaining buffered content as a final sentence.
"""
from __future__ import annotations

import re
from typing import List


# ---------------------------------------------------------------------------
# Private regex patterns
# ---------------------------------------------------------------------------

# Code fences: ```...``` (possibly with language tag)
_RE_CODE_FENCE = re.compile(r"```[\w]*\n?.*?```", re.DOTALL)

# Unterminated (still-streaming) code fence: an opening ``` with no closing
# fence yet.  Applied AFTER complete fences are removed, so any remaining ```
# is by definition an unmatched opener — everything from it to the end of the
# buffer is code-in-progress and must NOT be spoken (e.g. a streamed ```json
# structured-output block).  The closing fence, when it arrives, makes the
# whole block match _RE_CODE_FENCE instead.
_RE_OPEN_CODE_FENCE = re.compile(r"```.*$", re.DOTALL)

# Inline code: `...`
_RE_INLINE_CODE = re.compile(r"`[^`\n]*`")

# Table rows: lines that start/end with |
_RE_TABLE_ROW = re.compile(r"^\|.*\|[ \t]*$", re.MULTILINE)

# Table separator rows: |---|---|
_RE_TABLE_SEP = re.compile(r"^\|[-: |]+\|[ \t]*$", re.MULTILINE)

# Horizontal rules
_RE_HORIZ_RULE = re.compile(r"^(?:[-*_]){3,}[ \t]*$", re.MULTILINE)

# Markdown heading markers (#, ##, …)
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)

# Bold/italic: **text**, __text__, *text*, _text_
_RE_BOLD_ITALIC = re.compile(r"\*{1,3}([^*\n]+)\*{1,3}|_{1,3}([^_\n]+)_{1,3}")

# Links: [text](url)  →  keep text
_RE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")

# Images: ![alt](url)  →  empty
_RE_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

# HTML tags (basic)
_RE_HTML_TAG = re.compile(r"<[^>]+>")

# List bullets (-, *, +, 1.) at the start of a line
_RE_LIST_BULLET = re.compile(r"^[ \t]*(?:[-*+]|\d+\.)\s+", re.MULTILINE)

# Sentence boundary: terminal punctuation [.!?] followed by whitespace or EOS.
# We split on these positions and re-assemble sentence tokens.
_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class SpeakableFlattener:
    """Incremental markdown→speakable-text flattener with sentence segmentation.

    Maintains an internal buffer that accumulates across ``feed()`` calls.
    A sentence is only emitted once terminal punctuation is detected.

    Example::

        f = SpeakableFlattener()
        sentences = f.feed("Hello wor") + f.feed("ld. How are you?")
        # sentences == ["Hello world.", "How are you?"]
        rest = f.flush()   # any trailing content

    Note:
        This class is NOT thread-safe.  Create one instance per conversation
        turn and discard it afterwards.
    """

    def __init__(self) -> None:
        self._buffer: str = ""

    def feed(self, chunk: str) -> List[str]:
        """Accumulate ``chunk`` and return any newly completed sentences.

        A sentence is considered complete when terminal punctuation (``.``,
        ``!``, ``?``) is followed by whitespace (or a quote/bracket + ws).
        The terminal punctuation is included in the emitted sentence.

        Args:
            chunk: Next partial text chunk from ``ask_stream()``.

        Returns:
            A (possibly empty) list of complete speakable sentences.
        """
        self._buffer += chunk
        return self._extract_sentences()

    def flush(self) -> List[str]:
        """Return all remaining buffered text as a final sentence.

        Cleans and returns whatever is left in the buffer, regardless of
        whether it ends with terminal punctuation.

        Returns:
            A list containing the cleaned trailing text if non-empty,
            otherwise an empty list.
        """
        remaining = self._strip_markdown(self._buffer).strip()
        self._buffer = ""
        return [remaining] if remaining else []

    # ── Private helpers ────────────────────────────────────────────────

    def _strip_markdown(self, text: str) -> str:
        """Remove markdown formatting that should not be read aloud.

        Applies regex patterns in order to avoid partial matches.  The
        transformation is conservative: code content is discarded entirely,
        link text is preserved, inline formatting markers are removed.

        Args:
            text: Raw markdown text.

        Returns:
            Speakable plaintext with markdown stripped.
        """
        # 1. Remove complete code fences and their content entirely
        text = _RE_CODE_FENCE.sub(" ", text)

        # 1b. Remove an unterminated (still-streaming) code fence — see
        #     _RE_OPEN_CODE_FENCE.  Guards flush() and is a safety net even
        #     though _extract_sentences splits the open fence off first.
        text = _RE_OPEN_CODE_FENCE.sub(" ", text)

        # 2. Remove inline code content
        text = _RE_INLINE_CODE.sub(" ", text)

        # 3. Remove image alt-text and URL
        text = _RE_IMAGE.sub("", text)

        # 4. Links — keep the display text
        text = _RE_LINK.sub(r"\1", text)

        # 5. Table rows / separators
        text = _RE_TABLE_SEP.sub("", text)
        text = _RE_TABLE_ROW.sub("", text)

        # 6. Horizontal rules
        text = _RE_HORIZ_RULE.sub("", text)

        # 7. Heading markers
        text = _RE_HEADING.sub("", text)

        # 8. Bold / italic markers (keep text)
        def _bold_italic_repl(m: re.Match) -> str:
            return m.group(1) or m.group(2) or ""

        text = _RE_BOLD_ITALIC.sub(_bold_italic_repl, text)

        # 9. HTML tags
        text = _RE_HTML_TAG.sub("", text)

        # 10. List bullets at line start
        text = _RE_LIST_BULLET.sub("", text)

        # 11. Collapse excess whitespace and newlines
        text = re.sub(r"\n{2,}", " ", text)
        text = re.sub(r"\s{2,}", " ", text)

        return text

    @staticmethod
    def _split_open_fence(text: str) -> tuple[str, str]:
        """Split a raw buffer into its speakable prefix and a trailing open fence.

        While a ```` ``` ```` code block is still streaming (opener seen, closer
        not yet), everything from the opener onward is code-in-progress and must
        be held RAW in the buffer until the closing fence arrives — stripping it
        too early would lose the opener and let the (now fenceless) code leak to
        the TTS on the next feed.

        Returns:
            ``(speakable_prefix, open_fence)``.  ``open_fence`` is ``""`` when
            the buffer contains no unterminated fence.
        """
        # An odd number of ``` markers means the last one opens a fence that
        # has not been closed yet.
        if text.count("```") % 2 == 1:
            idx = text.rfind("```")
            return text[:idx], text[idx:]
        return text, ""

    def _extract_sentences(self) -> List[str]:
        """Split the current buffer on sentence boundaries and drain them.

        Strategy:
        1. Hold any trailing unterminated code fence RAW (do not speak code).
        2. Strip markdown from the speakable prefix (BEFORE stripping ws).
        3. Split on ``_RE_SENTENCE_SPLIT`` (terminal punct + whitespace).
           Critically: we do NOT strip the cleaned text before splitting so
           that a trailing space in the chunk acts as a valid sentence boundary.
        4. Emit all segments except the last one as complete sentences.
        5. If the last segment also ends with terminal punctuation emit it too.

        Returns:
            List of complete speakable sentences extracted from the buffer.
        """
        # Hold back a still-streaming code fence; re-append it (raw) to whatever
        # remains in the buffer so the next feed() can complete/strip it.
        speakable, open_fence = self._split_open_fence(self._buffer)

        # Clean but do NOT call .strip() here — trailing whitespace from the
        # incoming chunk is the sentence boundary signal we rely on.
        cleaned = self._strip_markdown(speakable)
        if not cleaned.strip():
            # Nothing speakable yet; retain the raw buffer (an open fence, or a
            # partial sentence/markdown that completes on a later feed).
            self._buffer = speakable + open_fence
            return []

        # Split gives: ["First sentence.", " Second sentence.", " partial"]
        # Everything but the last part ends with [.!?]
        parts = _RE_SENTENCE_SPLIT.split(cleaned)
        # parts[-1] is the tail (may or may not end with terminal punct)

        if len(parts) <= 1:
            # No whitespace-after-punct boundary found yet; keep accumulating.
            # Store the cleaned prefix (markup already removed) plus the raw
            # open fence so future feeds don't re-process stripped markup.
            self._buffer = cleaned + open_fence
            return []

        complete = parts[:-1]
        tail = parts[-1]

        sentences = [s.strip() for s in complete if s.strip()]

        # If the last segment itself ends with terminal punctuation,
        # it is also a complete sentence (occurs at EOS or when the stream ends).
        if tail.strip() and re.search(r"[.!?]$", tail.strip()):
            sentences.append(tail.strip())
            self._buffer = open_fence
        else:
            self._buffer = tail.lstrip() + open_fence  # retain tail for next feed()

        return sentences
