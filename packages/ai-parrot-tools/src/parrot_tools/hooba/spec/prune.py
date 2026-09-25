"""Prune Hooba's OpenAPI document to the tags FEAT-602 uses.

Usage::

    python -m parrot_tools.hooba.spec.prune --source https://api.hooba.com/api/doc.json --out <file>
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Sequence, Set, Tuple

import aiohttp

logger = logging.getLogger(__name__)

KEEP_TAGS: tuple[str, ...] = (
    "Invoice", "InvoiceLine", "InvoiceSerie", "PurchaseInvoice", "PurchaseInvoiceLine", "Contact", "Tax",
    "IncomeTax", "AccountingAccount", "PaymentMethod", "PaymentTerm", "Currency", "Document", "DocumentType",
    "InboxFile", "UnitOfMeasure", "Account", "Member", "Authentication",
)
SERVERS = [{"url": "https://api.hooba.com"}]

# Standard OpenAPI path-item HTTP method keys (everything else on a path item,
# e.g. "parameters"/"summary"/"description", is shared context, not an operation).
HTTP_METHODS: frozenset[str] = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def _collect_refs(node: Any, refs: Set[Tuple[str, str]]) -> None:
    """Recursively collect ``#/components/<kind>/<name>`` targets referenced by ``node``.

    Args:
        node: An arbitrary JSON-decoded fragment (dict/list/scalar) to walk.
        refs: A set accumulating ``(kind, name)`` tuples found via ``$ref``.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/"):
            parts = ref.split("/")
            if len(parts) >= 4:
                refs.add((parts[2], parts[3]))
        for key, value in node.items():
            if key.startswith("x-"):
                continue
            _collect_refs(value, refs)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, refs)


def _strip_x_keys(node: Any) -> Any:
    """Return a copy of ``node`` with every ``x-``-prefixed key removed, recursively."""
    if isinstance(node, dict):
        return {key: _strip_x_keys(value) for key, value in node.items() if not key.startswith("x-")}
    if isinstance(node, list):
        return [_strip_x_keys(item) for item in node]
    return node


def prune_spec(doc: Dict[str, Any], keep_tags: Sequence[str] = KEEP_TAGS) -> Dict[str, Any]:
    """Return a new document with only ``keep_tags`` operations and the components they reference.

    A path item is kept when at least one of its HTTP-method operations has ``tags[0]`` in
    ``keep_tags``; only those operations (plus the path item's shared, non-method keys) are kept.
    Component references (``$ref``) are then collected transitively from the kept paths so every
    schema/parameter/etc. reachable from a kept operation is preserved, and nothing else is. Keys
    starting with ``x-`` are dropped everywhere. ``servers`` is always set to the single Hooba
    production URL. The result is otherwise a plain, JSON-serializable dict (no in-place mutation
    of ``doc``), so serializing it with ``sort_keys=True`` yields a stable, reproducible document.

    Args:
        doc: The full, decoded OpenAPI document to prune.
        keep_tags: Operation tags to retain; an operation is kept when its first tag is a member.

    Returns:
        A new, pruned OpenAPI document dict.
    """
    keep = set(keep_tags)
    paths = doc.get("paths") or {}
    pruned_paths: Dict[str, Any] = {}
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        kept_ops: Dict[str, Any] = {}
        for method, operation in item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            tags = operation.get("tags") or []
            if tags and tags[0] in keep:
                kept_ops[method] = operation
        if not kept_ops:
            continue
        shared = {key: value for key, value in item.items() if key not in HTTP_METHODS}
        pruned_paths[path] = {**shared, **kept_ops}

    refs: Set[Tuple[str, str]] = set()
    _collect_refs(pruned_paths, refs)

    components = doc.get("components") or {}
    visited: Set[Tuple[str, str]] = set()
    queue = list(refs)
    while queue:
        kind, name = queue.pop()
        if (kind, name) in visited:
            continue
        visited.add((kind, name))
        component = (components.get(kind) or {}).get(name)
        if component is None:
            continue
        nested_refs: Set[Tuple[str, str]] = set()
        _collect_refs(component, nested_refs)
        for nested_ref in nested_refs:
            if nested_ref not in visited:
                queue.append(nested_ref)

    pruned_components: Dict[str, Dict[str, Any]] = {}
    for kind, name in visited:
        value = (components.get(kind) or {}).get(name)
        if value is None:
            continue
        pruned_components.setdefault(kind, {})[name] = value

    result: Dict[str, Any] = {
        "openapi": doc.get("openapi"),
        "info": _strip_x_keys(doc.get("info") or {}),
        "servers": SERVERS,
        "paths": _strip_x_keys(pruned_paths),
        "components": _strip_x_keys(pruned_components),
    }

    doc_tags = doc.get("tags")
    if isinstance(doc_tags, list):
        kept_doc_tags = [tag for tag in doc_tags if isinstance(tag, dict) and tag.get("name") in keep]
        if kept_doc_tags:
            result["tags"] = _strip_x_keys(kept_doc_tags)

    return result


async def fetch_spec(url: str) -> Dict[str, Any]:
    """GET ``url`` with aiohttp and return the decoded JSON."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)


def _write(doc: Dict[str, Any], out: Path) -> str:
    data = json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False).encode("utf-8") + b"\n"
    out.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; prints the sha256 of the written file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        required=True,
        help="http(s) URL to fetch (e.g. https://api.hooba.com/api/doc.json) or a local file path",
    )
    parser.add_argument("--out", required=True, type=Path, help="path to write the pruned document")
    args = parser.parse_args(argv)

    if args.source.startswith("http://") or args.source.startswith("https://"):
        doc = asyncio.run(fetch_spec(args.source))
    else:
        doc = json.loads(Path(args.source).read_text(encoding="utf-8"))

    pruned = prune_spec(doc)
    sha256 = _write(pruned, args.out)
    print(sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
