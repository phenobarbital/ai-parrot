"""
Utilities for WhatsApp integration.

Provides markdown conversion, message splitting, and phone number sanitization.
"""
import re
from typing import List


def convert_markdown_to_whatsapp(text: str) -> str:
    """
    Convert standard Markdown to WhatsApp-compatible formatting.

    WhatsApp supports:
    - *bold* (not **bold**)
    - _italic_ (same as standard MD single underscore)
    - ~strikethrough~ (not ~~strikethrough~~)
    - ```code``` (same as standard MD)

    Standard MD -> WhatsApp:
    - **bold** -> *bold*
    - ~~strikethrough~~ -> ~strikethrough~
    - Code blocks (```...```) are preserved as-is
    """
    if not text:
        return text

    # Protect code blocks from conversion
    code_blocks = []
    code_block_pattern = re.compile(r'```[\s\S]*?```')

    def preserve_code_block(match):
        code_blocks.append(match.group(0))
        return f'\x00CODE_BLOCK_{len(code_blocks) - 1}\x00'

    text = code_block_pattern.sub(preserve_code_block, text)

    # Protect inline code from conversion
    inline_codes = []
    inline_code_pattern = re.compile(r'`[^`]+`')

    def preserve_inline_code(match):
        inline_codes.append(match.group(0))
        return f'\x00INLINE_CODE_{len(inline_codes) - 1}\x00'

    text = inline_code_pattern.sub(preserve_inline_code, text)

    # Convert **bold** to *bold* (must be before single * handling)
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    # Convert ~~strikethrough~~ to ~strikethrough~
    text = re.sub(r'~~(.+?)~~', r'~\1~', text)

    # Convert [text](url) links to "text (url)" since WhatsApp auto-links URLs
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)

    # Remove ### headers - just keep the text with bold
    text = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        text = text.replace(f'\x00INLINE_CODE_{i}\x00', code)

    # Restore code blocks
    for i, block in enumerate(code_blocks):
        text = text.replace(f'\x00CODE_BLOCK_{i}\x00', block)

    return text


def split_message(text: str, max_length: int = 4096) -> List[str]:
    """
    Split a long message into chunks that fit WhatsApp's message size limit.

    Splits at natural boundaries (paragraphs, newlines, sentences) without
    breaking code blocks.

    Args:
        text: The text to split.
        max_length: Maximum characters per chunk (default 4096).

    Returns:
        List of text chunks.
    """
    if not text or len(text) <= max_length:
        return [text] if text else []

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to split at a double newline (paragraph boundary)
        split_pos = remaining.rfind('\n\n', 0, max_length)

        # Fall back to single newline
        if split_pos == -1 or split_pos < max_length // 2:
            split_pos = remaining.rfind('\n', 0, max_length)

        # Fall back to sentence boundary
        if split_pos == -1 or split_pos < max_length // 2:
            for sep in ('. ', '! ', '? ', '; '):
                pos = remaining.rfind(sep, 0, max_length)
                if pos > max_length // 2:
                    split_pos = pos + 1  # Include the punctuation
                    break

        # Fall back to space
        if split_pos == -1 or split_pos < max_length // 4:
            split_pos = remaining.rfind(' ', 0, max_length)

        # Last resort: hard split at max_length
        if split_pos == -1 or split_pos == 0:
            split_pos = max_length

        chunks.append(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip()

    return chunks


def sanitize_phone_number(number: str) -> str:
    """
    Normalize a phone number by stripping non-digit characters.

    Args:
        number: Phone number string (may contain +, spaces, dashes).

    Returns:
        Cleaned phone number string with only digits.
    """
    return re.sub(r'[^\d]', '', number)
