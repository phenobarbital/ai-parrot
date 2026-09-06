"""Bounded static code-to-API candidate resolution (FEAT-532 TASK-2906).

Extracts candidate Roblox API references from Luau source, resolved
against the offline :class:`~parrot.knowledge.wiki.roblox.models.RobloxApiCatalog`
(TASK-2901's render output) — never against a network dump. Per the
spec's final §8 owner decision (overriding an earlier proposal that
excluded them), the scope is deliberately wide:

1. Literal ``game:GetService("X")`` calls.
2. Explicit API type annotations (``local p: Player``, ``function
   f(p: Player)``) — a plain identifier type, never a ``builtin_type``
   primitive.
3. Chained instance access on a **known, unshadowed root**
   (``game``/``workspace``), at every level of the chain — e.g.
   ``workspace.Terrain``, and both ``Workspace``/``Terrain`` out of
   ``game.Workspace.Terrain``.

Excluded, deliberately: local type aliases' own right-hand side (``type
MyAlias = Player`` never produces a reference — the owner's decision),
any root shadowed by a local declaration/parameter anywhere in the file
(a coarse, file-wide, false-negative-leaning check — see
:func:`_collect_shadowed_roots`), and anything inside a comment or
string literal (tree-sitter already tokenizes those separately, so a
node-type walk never descends into them).

Only candidates that resolve against ``catalog`` are returned — an
unresolved chain (recognized root, valid syntax, but no matching class/
enum) is never guessed into a fabricated page; it is reported as a
diagnostic only.
"""

from __future__ import annotations

import logging
from typing import Any

from parrot.knowledge.wiki.languages import luau_guard, treesitter
from parrot.knowledge.wiki.roblox.models import (
    RobloxApiCatalog,
    RobloxApiReferenceCandidate,
    RobloxReferenceExtractionKind,
)

logger = logging.getLogger(__name__)

#: Roots this task is authorized to treat as known DataModel entry
#: points (spec §8: "game/workspace/class names" are the shadow-checked
#: set). ``script`` is deliberately excluded — it never resolves to an
#: API class by itself (it addresses the *current* instance, handled by
#: TASK-2898's require resolution, not an API reference).
_KNOWN_ROOTS = frozenset({"game", "workspace"})

#: Identifiers whose local shadowing suppresses candidate generation
#: entirely for this file (superset of `_KNOWN_ROOTS`, since a shadowed
#: `game`/`workspace` also invalidates `game:GetService(...)` calls).
_SHADOW_WATCHED_NAMES = _KNOWN_ROOTS

#: Placeholder `recognized_root` for a type-annotation candidate — there
#: is no DataModel root for a type position, but the model requires a
#: non-empty value (diagnostic clarity: "how was this recognized").
_TYPE_ANNOTATION_ROOT = "type-annotation"


def _text(node: Any, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _collect_shadowed_roots(root: Any, source_bytes: bytes) -> frozenset[str]:
    """Names among :data:`_SHADOW_WATCHED_NAMES` declared ANYWHERE in the
    file as a ``local`` variable or a function parameter.

    Deliberately whole-file and not point-of-use scoped: real Roblox
    code essentially never shadows ``game``/``workspace``, so this
    coarse check trades a theoretical false negative (a shadow that
    stops applying before some later, legitimate use) for a simple,
    fully deterministic, source-span-free implementation — a
    lexical-scope-accurate version would need real per-block scope
    tracking, which is out of scope here (no expression type inference,
    no LSP calls, per spec §8).
    """
    shadowed: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "variable_list":
            for child in node.children:
                if child.type == "identifier":
                    name = _text(child, source_bytes)
                    if name in _SHADOW_WATCHED_NAMES:
                        shadowed.add(name)
        elif node.type == "parameter":
            for child in node.children:
                if child.type == "identifier":
                    name = _text(child, source_bytes)
                    if name in _SHADOW_WATCHED_NAMES:
                        shadowed.add(name)
                    break  # only the first identifier is the param name
        stack.extend(node.children)
    return frozenset(shadowed)


def _root_identifier(node: Any, source_bytes: bytes) -> str | None:
    """Walk a ``dot_index_expression``'s left spine down to its ultimate
    base identifier, or ``None`` if the base is not a plain identifier
    (e.g. a function call or an indexed expression)."""
    current = node
    while current.type == "dot_index_expression":
        current = current.children[0]
    if current.type == "identifier":
        return _text(current, source_bytes)
    return None


def _match_service_call(
    node: Any, source_bytes: bytes, shadowed: frozenset[str]
) -> tuple[int, int, str, RobloxReferenceExtractionKind, str] | None:
    """Match ``game:GetService("X")`` — returns a raw candidate tuple, or
    ``None``."""
    if node.type != "function_call":
        return None
    children = node.children
    if len(children) < 2:
        return None
    callee, arguments = children[0], children[1]
    if callee.type != "method_index_expression" or arguments.type != "arguments":
        return None
    callee_children = [c for c in callee.children if c.type != ":"]
    if len(callee_children) != 2:
        return None
    base, method = callee_children
    if base.type != "identifier" or _text(base, source_bytes) != "game":
        return None
    if "game" in shadowed:
        return None
    if method.type != "identifier" or _text(method, source_bytes) != "GetService":
        return None
    string_args = [c for c in arguments.children if c.type == "string"]
    if len(string_args) != 1:
        return None  # a computed/variable argument — never guessed
    content_nodes = [c for c in string_args[0].children if c.type == "string_content"]
    if not content_nodes:
        return None
    target = _text(content_nodes[0], source_bytes)
    return (node.start_byte, node.end_byte, "game", RobloxReferenceExtractionKind.SERVICE_CALL, target)


def _match_chain_segment(
    node: Any, source_bytes: bytes, shadowed: frozenset[str]
) -> tuple[int, int, str, RobloxReferenceExtractionKind, str] | None:
    """Match one ``dot_index_expression`` level rooted at a known,
    unshadowed root — returns a raw candidate tuple for its own field
    segment, or ``None``."""
    if node.type != "dot_index_expression":
        return None
    root = _root_identifier(node, source_bytes)
    if root is None or root not in _KNOWN_ROOTS or root in shadowed:
        return None
    field = node.children[-1]
    if field.type != "identifier":
        return None
    target = _text(field, source_bytes)
    return (node.start_byte, node.end_byte, root, RobloxReferenceExtractionKind.CHAINED_ACCESS, target)


def _match_type_annotation(
    colon_index: int, node: Any, source_bytes: bytes
) -> tuple[int, int, str, RobloxReferenceExtractionKind, str] | None:
    """Given a ``parameter``/``variable_list`` child sequence with a
    ``:`` at ``colon_index``, match a plain-identifier type annotation
    (never a ``builtin_type`` primitive) following it."""
    children = node.children
    if colon_index + 1 >= len(children):
        return None
    type_node = children[colon_index + 1]
    if type_node.type != "identifier":
        return None  # builtin_type (primitives) or a generic/union — not a bare API type
    target = _text(type_node, source_bytes)
    return (
        type_node.start_byte,
        type_node.end_byte,
        _TYPE_ANNOTATION_ROOT,
        RobloxReferenceExtractionKind.TYPE_ANNOTATION,
        target,
    )


def _extract_type_annotations(
    node: Any, source_bytes: bytes
) -> list[tuple[int, int, str, RobloxReferenceExtractionKind, str]]:
    """Type-annotation candidates from a ``parameter`` or ``variable_list`` node."""
    if node.type not in ("parameter", "variable_list"):
        return []
    out = []
    for i, child in enumerate(node.children):
        if child.type == ":":
            match = _match_type_annotation(i, node, source_bytes)
            if match is not None:
                out.append(match)
    return out


def _extract_candidates_worker(parser: Any, source_bytes: bytes) -> dict[str, Any]:
    """Parse + extract using an already-loaded, cached ``Parser``.

    Runs synchronously, in-process — per
    ``docs/design/luau-parser-resource-policy.md`` §1/§3, per-file
    subprocess isolation is reserved for the offline benchmark/CI
    regression path, never a per-file production hot path (this function
    runs once per enrichment-eligible Luau file, mirroring
    :mod:`parrot.knowledge.wiki.languages.luau`'s ``outline()``).
    """
    tree = parser.parse(source_bytes)
    root = tree.root_node

    shadowed = _collect_shadowed_roots(root, source_bytes)
    raw: list[tuple[int, int, str, RobloxReferenceExtractionKind, str]] = []

    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "type_definition":
            continue  # local type aliases never generate a reference
        service_match = _match_service_call(node, source_bytes, shadowed)
        if service_match is not None:
            raw.append(service_match)
        chain_match = _match_chain_segment(node, source_bytes, shadowed)
        if chain_match is not None:
            raw.append(chain_match)
        raw.extend(_extract_type_annotations(node, source_bytes))
        stack.extend(node.children)

    return {
        "candidates": [
            {
                "source_span": (start, end),
                "recognized_root": root_name,
                "extraction_kind": kind.value,
                "target_name": target,
            }
            for start, end, root_name, kind, target in raw
        ]
    }


def extract_api_reference_candidates(
    source: str,
    catalog: RobloxApiCatalog | None,
) -> tuple[list[RobloxApiReferenceCandidate], list[str]]:
    """Extract, deduplicate and resolve API reference candidates.

    Args:
        source: Raw Luau/Lua source text.
        catalog: The active generation's :class:`RobloxApiCatalog`, or
            ``None``/empty when no API plane has been ingested.

    Returns:
        ``(candidates, diagnostics)``. ``candidates`` contains only
        entries whose ``target_name`` resolves to a known class or enum
        in ``catalog`` — deduplicated by ``(recognized_root,
        extraction_kind, target_name)``; an unresolved name is never
        returned as a candidate at all, only as a diagnostic.
        ``diagnostics`` explains skips: no catalog, grammar unavailable,
        oversized/timed-out source, or an unresolved chain.
    """
    if catalog is None or (not catalog.classes and not catalog.enums):
        return [], ["no API catalog available, skipped API reference extraction"]

    source_bytes = source.encode("utf-8")
    if not luau_guard.admit_for_treesitter(source_bytes):
        return [], [f"source exceeds {luau_guard.BYTE_LIMIT}-byte guard, skipped API reference extraction"]
    parser = treesitter.get_parser("luau")
    if parser is None:
        return [], ["tree-sitter-luau grammar unavailable, skipped API reference extraction"]

    try:
        result = _extract_candidates_worker(parser, source_bytes)
    except Exception as exc:  # noqa: BLE001 - degrade, never raise
        logger.debug("API reference extraction failed: %s", exc)
        return [], [f"extraction failed ({exc}), skipped API reference extraction"]

    known_names = set(catalog.classes) | set(catalog.enums)
    seen: set[tuple[str, str, str]] = set()
    resolved: list[RobloxApiReferenceCandidate] = []
    unresolved_names: set[str] = set()

    for raw in result["candidates"]:
        target = raw["target_name"]
        key = (raw["recognized_root"], raw["extraction_kind"], target)
        if key in seen:
            continue
        if target not in known_names:
            unresolved_names.add(target)
            continue
        seen.add(key)
        resolved.append(
            RobloxApiReferenceCandidate(
                source_span=tuple(raw["source_span"]),
                recognized_root=raw["recognized_root"],
                extraction_kind=RobloxReferenceExtractionKind(raw["extraction_kind"]),
                target_name=target,
            )
        )

    diagnostics = [
        f"unresolved candidate {name!r}: no matching class/enum in the active API catalog"
        for name in sorted(unresolved_names)
    ]
    return resolved, diagnostics
