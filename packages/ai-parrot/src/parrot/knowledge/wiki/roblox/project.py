"""Bounded Roblox mapping reader and unique require resolver (FEAT-532 TASK-2898).

Two independent resolution paths, per spec §"Local scanning and resolution":

1. **DataModel-mapping resolution** — reads ``sourcemap.json`` (preferred)
   or ``default.project.json`` (fallback when the sourcemap is
   missing/invalid) to build a :class:`RobloxInstanceIndex`
   (:func:`build_instance_index`), then resolves ``script.Parent.Foo`` /
   ``game.Service.Path`` / ``game:GetService("X").Path`` chains against it
   (:func:`resolve_roblox_require`).
2. **Relative-string resolution** — ``"./Foo"``/``"../Foo"``-style string
   requires, resolved directly against the discovered file set
   (:func:`_resolve_relative_string`), independent of any DataModel
   mapping and always available regardless of mapping mode (spec: "Relative
   strings remain available regardless of mapping mode").

Byte/depth limits are the TASK-2896 reviewed policy
(``docs/design/luau-parser-resource-policy.md`` §3): a 16 MiB mapping
JSON byte cap and a 200-level nesting depth cap, enforced **before**
``json.loads`` (bounded pre-scan, not exception-driven) so a hostile or
corrupted mapping file degrades to a diagnostic instead of an expensive
parse or a native recursion crash.

No network access, no external executables (Rojo/luau-lsp/git), and no
production Luau parsing — this module is independent of TASK-2899's
scanner and only consumes the file set the wiki's own repository
discovery already produced.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path, PurePosixPath
from typing import Any

from parrot.knowledge.wiki.roblox.models import RobloxInstanceIndex

logger = logging.getLogger(__name__)

#: Reviewed policy (docs/design/luau-parser-resource-policy.md §3).
MAPPING_JSON_BYTE_LIMIT = 16 * 1024 * 1024
MAPPING_JSON_DEPTH_LIMIT = 200

_SOURCEMAP_FILENAME = "sourcemap.json"
_PROJECT_FILENAME = "default.project.json"

#: Valid bare Lua/Roblox identifier segment (instance/child names).
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: ``game:GetService("X")`` — the only recognized method-call form; any
#: other call shape is a computed expression and is rejected.
_SERVICE_CALL_RE = re.compile(r'^game:GetService\(\s*"([A-Za-z0-9_]+)"\s*\)(.*)$')

#: Script-suffix -> Roblox className convention (spec: "ordinary script
#: suffixes and init-module conventions").
_SUFFIX_CLASS_NAMES: tuple[tuple[str, str], ...] = (
    (".server.luau", "Script"),
    (".server.lua", "Script"),
    (".client.luau", "LocalScript"),
    (".client.lua", "LocalScript"),
    (".luau", "ModuleScript"),
    (".lua", "ModuleScript"),
)

_INIT_STEMS = {"init.server", "init.client", "init"}


# ---------------------------------------------------------------------------
# Bounded JSON loading
# ---------------------------------------------------------------------------


def _bounded_depth(text: str, limit: int) -> bool:
    """Whether ``text``'s bracket nesting stays within ``limit`` levels.

    A cheap, string-aware, **iterative** character scan — no JSON
    parsing, no recursion. Only ``{``/``[``/``}``/``]`` outside quoted
    strings count toward depth, so this must run before ``json.loads``,
    not after (the goal is to reject a pathological mapping file before
    paying for a full parse, per TASK-2896's measured policy).
    """
    depth = 0
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
            if depth > limit:
                return False
        elif ch in "}]":
            depth -= 1
    return True


def _load_bounded_json(path: Path) -> tuple[Any | None, str | None]:
    """Read and parse ``path`` as JSON, enforcing the reviewed size/depth caps.

    Returns:
        ``(data, diagnostic)`` — exactly one is non-``None``. Never
        raises: any I/O error, oversize file, over-depth structure, or
        malformed JSON becomes a diagnostic string with ``data=None``.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"{path.name}: could not stat ({exc})"
    if size > MAPPING_JSON_BYTE_LIMIT:
        return None, f"{path.name}: {size} bytes exceeds {MAPPING_JSON_BYTE_LIMIT} byte limit"

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path.name}: could not read ({exc})"

    if not _bounded_depth(text, MAPPING_JSON_DEPTH_LIMIT):
        return None, f"{path.name}: nesting exceeds {MAPPING_JSON_DEPTH_LIMIT}-level depth limit"

    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        return None, f"{path.name}: invalid JSON ({exc})"

    return data, None


# ---------------------------------------------------------------------------
# sourcemap.json parsing
# ---------------------------------------------------------------------------


def _parse_sourcemap(data: Any, discovered: frozenset[str]) -> tuple[RobloxInstanceIndex, list[str]]:
    """Build a :class:`RobloxInstanceIndex` from a parsed Rojo sourcemap tree.

    Iterative (explicit stack), not recursive — see TASK-2896's finding
    that Luau/JSON-shaped trees can exceed Python's recursion limit.
    Every node's ``filePaths`` entries are associated one-to-many with its
    instance path; no duplicate is arbitrarily dropped. Only file paths
    present in ``discovered`` (the wiki's own repository file discovery)
    are recorded, so a stale sourcemap entry pointing at a
    no-longer-existing file is silently excluded from resolution rather
    than fabricating a target.
    """
    diagnostics: list[str] = []
    file_to_instances: dict[str, list[str]] = {}
    instance_to_files: dict[str, list[str]] = {}
    class_names: dict[str, str] = {}

    if not isinstance(data, dict):
        return RobloxInstanceIndex(source_kind="none"), ["sourcemap.json: root is not an object"]

    # Root className is conventionally "DataModel"; Roblox code addresses
    # it as "game", not by its sourcemap "name" (usually the place name).
    root_segment = "game" if data.get("className") == "DataModel" else data.get("name", "game")
    stack: list[tuple[Any, list[str]]] = [(data, [str(root_segment)])]
    visited = 0
    max_nodes = 200_000  # generous bound; a real project sourcemap is far smaller

    while stack:
        node, path_segments = stack.pop()
        visited += 1
        if visited > max_nodes:
            diagnostics.append("sourcemap.json: node count exceeded safety bound, truncated")
            break
        if not isinstance(node, dict):
            continue

        instance_path = ".".join(path_segments)
        class_name = node.get("className")
        if isinstance(class_name, str):
            class_names[instance_path] = class_name

        for file_path in node.get("filePaths") or []:
            if not isinstance(file_path, str):
                continue
            rel_path = PurePosixPath(file_path).as_posix()
            if rel_path not in discovered:
                diagnostics.append(f"sourcemap.json: stale entry {rel_path!r} not found, skipped")
                continue
            instance_to_files.setdefault(instance_path, [])
            if rel_path not in instance_to_files[instance_path]:
                instance_to_files[instance_path].append(rel_path)
            file_to_instances.setdefault(rel_path, [])
            if instance_path not in file_to_instances[rel_path]:
                file_to_instances[rel_path].append(instance_path)

        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                if not isinstance(child, dict):
                    continue
                child_name = child.get("name")
                if not isinstance(child_name, str) or not child_name:
                    continue
                stack.append((child, [*path_segments, child_name]))

    for mapping in (file_to_instances, instance_to_files):
        for key in mapping:
            mapping[key] = sorted(mapping[key])

    index = RobloxInstanceIndex(
        file_to_instances=file_to_instances,
        instance_to_files=instance_to_files,
        class_names=class_names,
        source_kind="sourcemap",
        diagnostics=diagnostics,
    )
    return index, diagnostics


# ---------------------------------------------------------------------------
# default.project.json parsing (static $path fallback)
# ---------------------------------------------------------------------------


def _class_name_for_suffix(rel_path: str) -> tuple[str, str] | None:
    """Return ``(instance_name, className)`` for a script file by suffix
    convention, or ``None`` when the suffix is not a recognized script type.

    ``init.lua``/``init.luau``/``init.server.*``/``init.client.*`` map the
    file's **containing folder** to the instance (folder name, not
    "init"); every other recognized suffix maps the file's own stem.
    """
    name = PurePosixPath(rel_path).name
    stem_no_suffix = None
    class_name = None
    for suffix, cname in _SUFFIX_CLASS_NAMES:
        if name.endswith(suffix):
            stem_no_suffix = name[: -len(suffix)]
            class_name = cname
            break
    if stem_no_suffix is None or class_name is None:
        return None

    if stem_no_suffix in ("init.server", "init.client", "init"):
        folder_name = PurePosixPath(rel_path).parent.name
        if not folder_name:
            return None
        return folder_name, class_name
    return stem_no_suffix, class_name


def _parse_project_file(data: Any, discovered: frozenset[str]) -> tuple[RobloxInstanceIndex, list[str]]:
    """Build a :class:`RobloxInstanceIndex` from a ``default.project.json``
    static ``tree``/``$path`` structure.

    Only paths already present in ``discovered`` are ever associated —
    this never walks the filesystem itself, it intersects the project
    file's ``$path`` directories against the wiki's own file discovery.
    Unsupported directives (anything besides ``$className``/``$path``)
    produce a diagnostic and are otherwise ignored; never executed.
    """
    diagnostics: list[str] = []
    file_to_instances: dict[str, list[str]] = {}
    instance_to_files: dict[str, list[str]] = {}
    class_names: dict[str, str] = {}

    if not isinstance(data, dict):
        return RobloxInstanceIndex(source_kind="none"), ["default.project.json: root is not an object"]

    tree = data.get("tree")
    if not isinstance(tree, dict):
        return RobloxInstanceIndex(source_kind="none"), ["default.project.json: missing 'tree'"]

    def _associate(instance_path: str, rel_path: str, class_name: str) -> None:
        if rel_path not in discovered:
            diagnostics.append(f"default.project.json: {rel_path!r} not found, skipped")
            return
        instance_to_files.setdefault(instance_path, [])
        if rel_path not in instance_to_files[instance_path]:
            instance_to_files[instance_path].append(rel_path)
        file_to_instances.setdefault(rel_path, [])
        if instance_path not in file_to_instances[rel_path]:
            file_to_instances[rel_path].append(instance_path)
        class_names[instance_path] = class_name

    stack: list[tuple[dict, list[str]]] = [(tree, ["game"])]
    visited = 0
    max_nodes = 200_000

    while stack:
        node, path_segments = stack.pop()
        visited += 1
        if visited > max_nodes:
            diagnostics.append("default.project.json: node count exceeded safety bound, truncated")
            break

        instance_path = ".".join(path_segments)
        class_name = node.get("$className")
        if isinstance(class_name, str):
            class_names[instance_path] = class_name

        path_directive = node.get("$path")
        if isinstance(path_directive, str):
            rel = PurePosixPath(path_directive).as_posix()
            if rel in discovered:
                # $path points directly at a single known file.
                mapped = _class_name_for_suffix(rel)
                cname = class_name or (mapped[1] if mapped else "ModuleScript")
                _associate(instance_path, rel, cname)
            else:
                prefix = rel.rstrip("/") + "/"
                for candidate in sorted(discovered):
                    if not candidate.startswith(prefix):
                        continue
                    remainder = candidate[len(prefix) :]
                    if "/" in remainder:
                        continue  # nested folder: not directly under $path
                    mapped = _class_name_for_suffix(candidate)
                    if mapped is None:
                        continue
                    child_name, cname = mapped
                    child_path = [*path_segments, child_name]
                    _associate(".".join(child_path), candidate, cname)

        for key, value in node.items():
            if key.startswith("$"):
                if key not in ("$className", "$path", "$ignoreUnknownInstances"):
                    diagnostics.append(f"default.project.json: unsupported directive {key!r} ignored")
                continue
            if isinstance(value, dict):
                stack.append((value, [*path_segments, key]))
            else:
                diagnostics.append(f"default.project.json: unsupported child value for {key!r} ignored")

    for mapping in (file_to_instances, instance_to_files):
        for key in mapping:
            mapping[key] = sorted(mapping[key])

    index = RobloxInstanceIndex(
        file_to_instances=file_to_instances,
        instance_to_files=instance_to_files,
        class_names=class_names,
        source_kind="project-file",
        diagnostics=diagnostics,
    )
    return index, diagnostics


# ---------------------------------------------------------------------------
# Public entry point: build the index
# ---------------------------------------------------------------------------


def build_instance_index(scan_root: Path | None, discovered_paths: Any) -> RobloxInstanceIndex:
    """Build a :class:`RobloxInstanceIndex` for one repository scan.

    Reads ``sourcemap.json`` first; falls back to
    ``default.project.json`` only when the sourcemap is absent or
    invalid (a valid-but-stale sourcemap is *not* silently supplemented
    by the project-file fallback — spec: "A valid but stale sourcemap
    entry is unresolved, not silently remapped through the project
    fallback"). Returns ``source_kind="none"`` with only
    :attr:`~RobloxInstanceIndex.diagnostics` populated when neither
    mapping source is usable — callers then proceed with relative-string
    resolution and local requires only.

    Args:
        scan_root: Absolute repository root, or ``None`` (no mapping is
            attempted without a root).
        discovered_paths: POSIX-style relative paths of every file the
            wiki's own repository discovery already found.

    Returns:
        The built index. Never raises.
    """
    discovered = frozenset(PurePosixPath(p).as_posix() for p in discovered_paths)
    if scan_root is None:
        return RobloxInstanceIndex(source_kind="none", diagnostics=["no scan root available"])

    sourcemap_path = scan_root / _SOURCEMAP_FILENAME
    if sourcemap_path.is_file():
        data, error = _load_bounded_json(sourcemap_path)
        if error is None:
            index, _ = _parse_sourcemap(data, discovered)
            digest = _content_digest(sourcemap_path)
            return index.model_copy(update={"mapping_digest": digest})
        logger.debug("sourcemap.json invalid, falling back to project file: %s", error)
        fallback_diag = [f"sourcemap invalid ({error}), falling back to default.project.json"]
    else:
        fallback_diag = []

    project_path = scan_root / _PROJECT_FILENAME
    if project_path.is_file():
        data, error = _load_bounded_json(project_path)
        if error is None:
            index, _ = _parse_project_file(data, discovered)
            digest = _content_digest(project_path)
            return index.model_copy(
                update={
                    "mapping_digest": digest,
                    "diagnostics": [*fallback_diag, *index.diagnostics],
                }
            )
        fallback_diag.append(f"default.project.json invalid ({error})")

    return RobloxInstanceIndex(
        source_kind="none",
        diagnostics=(
            [*fallback_diag, "no valid Roblox mapping found"]
            if fallback_diag
            else ["no sourcemap.json or default.project.json found"]
        ),
    )


def _content_digest(path: Path) -> str:
    """Stable content hash of one mapping file, for enrichment invalidation."""
    import hashlib

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Require resolution
# ---------------------------------------------------------------------------


def resolve_roblox_require(
    spec: str,
    from_file: str,
    index: RobloxInstanceIndex,
    discovered_paths: Any,
) -> str | None:
    """Resolve one raw Luau require specifier to a unique repository file.

    Recognizes, in order:

    1. ``script`` / ``script.Parent...`` chains, relative to
       ``from_file``'s own DataModel instance position(s).
    2. ``game.Service.Path...`` and ``game:GetService("Service").Path...``
       absolute chains.
    3. Relative string requires (``"./Foo"``, ``"../Foo/Bar"``), resolved
       directly against ``discovered_paths`` — independent of ``index``,
       always available regardless of mapping mode.

    Rejects (returns ``None``) numeric asset requires, computed
    expressions, ambiguous instance names (a chain that resolves to more
    than one file), absolute/out-of-root paths, and any target not
    present in ``discovered_paths``. Never guesses through a stale or
    unresolved instance path.

    Args:
        spec: Raw require argument text (already extracted from source),
            e.g. ``"script.Parent.Foo"`` or ``'"./Foo"'``.
        from_file: POSIX-relative path of the requiring file.
        index: The :class:`RobloxInstanceIndex` built by
            :func:`build_instance_index` (may be ``source_kind="none"``).
        discovered_paths: Every file the wiki's own discovery found.

    Returns:
        The resolved repository-relative path, or ``None``.
    """
    discovered = frozenset(PurePosixPath(p).as_posix() for p in discovered_paths)
    spec = spec.strip()

    relative = _resolve_relative_string(spec, from_file, discovered)
    if relative is not None:
        return relative

    if spec.startswith("script"):
        remainder = spec[len("script") :]
        segments = _split_chain(remainder)
        if segments is None:
            return None
        start_path = _instance_path_for_file(from_file, index)
        if start_path is None:
            return None
        return _navigate_and_resolve(start_path, segments, index)

    if spec.startswith("game:"):
        match = _SERVICE_CALL_RE.match(spec)
        if not match:
            return None  # any other method call is a computed expression
        service, remainder = match.group(1), match.group(2)
        segments = _split_chain(remainder)
        if segments is None:
            return None
        return _navigate_and_resolve(["game"], [service, *segments], index)

    if spec.startswith("game."):
        segments = _split_chain(spec[len("game") :])
        if segments is None:
            return None
        return _navigate_and_resolve(["game"], segments, index)

    return None


def _split_chain(remainder: str) -> list[str] | None:
    """Split a ``.Foo.Parent.Bar`` suffix into validated identifier segments.

    Returns ``None`` (reject) on any non-identifier segment — a
    computed/indexed expression, string-keyed lookup, or numeric asset id.
    """
    if remainder == "":
        return []
    if not remainder.startswith("."):
        return None  # e.g. trailing `(...)` call - a computed expression
    parts = remainder[1:].split(".")
    for part in parts:
        if not _VALID_IDENTIFIER.match(part):
            return None
    return parts


def _instance_path_for_file(rel_path: str, index: RobloxInstanceIndex) -> list[str] | None:
    """The unique instance path mapped to ``rel_path``, or ``None`` if
    zero or more than one mapping exists (ambiguous)."""
    posix_path = PurePosixPath(rel_path).as_posix()
    candidates = index.file_to_instances.get(posix_path, [])
    if len(candidates) != 1:
        return None
    return candidates[0].split(".")


def _navigate_and_resolve(start: list[str], segments: list[str], index: RobloxInstanceIndex) -> str | None:
    """Apply ``segments`` (``Parent`` pops, any other identifier pushes) to
    ``start``, then resolve the resulting instance path to a unique file."""
    path = list(start)
    for segment in segments:
        if segment == "Parent":
            if not path:
                return None  # escaped above the root
            path.pop()
        else:
            path.append(segment)
    instance_path = ".".join(path)
    targets = index.instance_to_files.get(instance_path, [])
    if len(targets) != 1:
        return None  # missing, or ambiguous — never guess
    return targets[0]


def _resolve_relative_string(spec: str, from_file: str, discovered: frozenset[str]) -> str | None:
    """Resolve a quoted relative-string require, independent of any mapping.

    Only recognizes an explicitly relative form (``./`` or ``../``
    prefix) so this never collides with ``script``/``game`` chain
    parsing. Tries the ``.luau``/``.lua`` suffixes and the
    ``init.luau``/``init.lua`` folder convention, matched only against
    already-discovered files.
    """
    text = spec.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    if not (text.startswith("./") or text.startswith("../")):
        return None

    base = PurePosixPath(from_file).parent
    target = _normalize_posix(base / text)

    for suffix in (".luau", ".lua"):
        candidate = f"{target}{suffix}"
        if candidate in discovered:
            return candidate
    for init_name in ("init.luau", "init.lua"):
        candidate = f"{target}/{init_name}" if target != "." else init_name
        if candidate in discovered:
            return candidate
    if target in discovered:
        return target
    return None


def _normalize_posix(path: PurePosixPath) -> str:
    """Collapse ``.``/``..`` segments in a joined relative path.

    Rejects escape above the join root by simply not resolving past it
    (an unresolvable ``..`` leaves a leading ``..`` segment behind, which
    then never matches anything in ``discovered`` — the same
    fail-closed behavior the sibling PHP/JS scanners rely on).
    """
    parts: list[str] = []
    for part in path.parts:
        if part == ".":
            continue
        if part == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            else:
                parts.append(part)
        else:
            parts.append(part)
    return "/".join(parts) if parts else "."
