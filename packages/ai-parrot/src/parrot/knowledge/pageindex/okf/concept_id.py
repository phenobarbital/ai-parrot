"""Deterministic slug generation for OKF concept identifiers.

Implements stable ``concept_id`` derivation from node titles and parent paths.
``concept_id`` is the stable identity anchor for the entire OKF layer — it
survives ``reindex_node_ids``, ``splice_subtree``, and ``delete_node`` operations.

Design notes (from spec §2, D3, D8):
- ``concept_id`` is a deterministic slug — same title + parent path → same slug.
- Collisions (duplicate titles at the same level) are resolved with numeric
  suffixes (``-2``, ``-3``, ...) that are stable across runs.
- The first occurrence in depth-first order keeps the bare slug.
- Slash-separated hierarchy levels encode parent/child relationships.
  The projection layer flattens slashes to ``--`` for filesystem storage.
"""

import re
import unicodedata
from typing import Any


_MAX_SLUG_LENGTH = 80  # truncate before adding suffix
_SAFE_CHARS_RE = re.compile(r"[^a-z0-9-]+")
_MULTI_DASH_RE = re.compile(r"-{2,}")


def _slugify(text: str) -> str:
    """Convert text to a deterministic kebab-case slug.

    Steps:
    1. NFKD-normalise and convert to ASCII where possible.
    2. Lowercase.
    3. Replace runs of non-alphanumeric/non-hyphen chars with a single hyphen.
    4. Strip leading/trailing hyphens.
    5. Collapse multiple consecutive hyphens.
    6. Truncate to ``_MAX_SLUG_LENGTH`` characters.
    7. Fall back to ``"untitled"`` if the result is empty.

    Args:
        text: Raw input string (title, etc.).

    Returns:
        URL-safe kebab-case slug string.
    """
    if not text or not text.strip():
        return "untitled"

    # 1. Unicode normalise → ASCII-safe representation
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")

    # 2. Lowercase
    lower = ascii_text.lower()

    # 3. Replace non-alnum runs with a single hyphen
    slugged = _SAFE_CHARS_RE.sub("-", lower)

    # 4. Strip and 5. collapse
    slugged = _MULTI_DASH_RE.sub("-", slugged).strip("-")

    # 6. Truncate
    slugged = slugged[:_MAX_SLUG_LENGTH].rstrip("-")

    # 7. Fallback
    return slugged or "untitled"


def derive_concept_id(title: str, parent_path: str = "") -> str:
    """Derive a deterministic concept_id slug from a title.

    The slug is scoped under ``parent_path`` using a ``/`` separator, encoding
    the hierarchy level (e.g. ``controls/nist-800-53/ir-4``).

    Note: forward slashes in ``parent_path`` are preserved and encode hierarchy;
    they are NOT filesystem path separators here.  The projection layer handles
    flattening for storage.

    Args:
        title: Node title string (human-readable).
        parent_path: Optional parent scope prefix
            (e.g. ``"controls/nist-800-53"``).

    Returns:
        Deterministic slug, e.g.  ``"aws-incident-response"``
        or ``"controls/nist-800-53/ir-4"``.

    Examples:
        >>> derive_concept_id("AWS Incident Response")
        'aws-incident-response'
        >>> derive_concept_id("IR-4", "controls/nist-800-53")
        'controls/nist-800-53/ir-4'
    """
    slug = _slugify(title)
    if parent_path:
        return f"{parent_path.rstrip('/')}/{slug}"
    return slug


def dedup_concept_ids(nodes: list[dict]) -> None:
    """Resolve slug collisions with stable numeric suffixes.

    The first occurrence (in list order, which must be depth-first) keeps the
    bare slug.  Subsequent duplicates receive ``-2``, ``-3``, etc.  The
    assignment is stable across runs because the input list ordering is
    deterministic (depth-first tree walk).

    Modifies ``nodes`` in place.

    Args:
        nodes: Flat list of node dicts, each with a ``concept_id`` key.
            Must be in depth-first order (same as produced by
            ``assign_concept_ids``).
    """
    seen: dict[str, int] = {}
    for node in nodes:
        raw = node["concept_id"]
        if raw in seen:
            seen[raw] += 1
            node["concept_id"] = f"{raw}-{seen[raw]}"
        else:
            seen[raw] = 1


def _assign_recursive(
    nodes: list[dict],
    parent_path: str,
    flat: list[dict],
) -> None:
    """Recursively assign concept_ids depth-first, collecting nodes for dedup.

    Args:
        nodes: List of sibling node dicts (``nodes`` field of a parent).
        parent_path: Accumulated path from parent context.
        flat: Accumulator list for depth-first ordering (used by dedup).
    """
    for node in nodes:
        title = node.get("title", "")
        node["concept_id"] = derive_concept_id(title, parent_path)
        flat.append(node)
        children = node.get("nodes", [])
        if children:
            _assign_recursive(children, node["concept_id"], flat)


def assign_concept_ids(tree: dict[str, Any]) -> None:
    """Walk the tree depth-first and write deterministic ``concept_id`` values.

    This is the public entry point for enriching a bare PageIndex tree with
    ``concept_id`` fields.  Running twice on the same tree produces identical
    values (idempotent and deterministic).

    The function:
    1. Walks the tree depth-first via ``structure``.
    2. Derives a slug for each node via ``derive_concept_id``.
    3. Collects all nodes in DFS order.
    4. Resolves collisions via ``dedup_concept_ids``.

    Args:
        tree: PageIndex tree dict with a ``structure`` list of node dicts.
            Modified in place.
    """
    structure = tree.get("structure", [])
    flat: list[dict] = []
    _assign_recursive(structure, "", flat)
    dedup_concept_ids(flat)
