#!/usr/bin/env python3
"""Registry Generation Script for AI-Parrot monorepo.

Scans parrot_tools/ and parrot_loaders/ packages for tool and loader classes,
then generates or validates the TOOL_REGISTRY and LOADER_REGISTRY dicts in
each package's __init__.py.

Usage:
    python scripts/generate_tool_registry.py              # Update registries
    python scripts/generate_tool_registry.py --dry-run     # Show changes without writing
    python scripts/generate_tool_registry.py --check       # CI mode: exit 1 if stale
    python scripts/generate_tool_registry.py --verbose     # Verbose output
    python scripts/generate_tool_registry.py --tools-only  # Only scan tools
    python scripts/generate_tool_registry.py --loaders-only # Only scan loaders
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

TOOLS_PKG_DIR = WORKSPACE_ROOT / "packages" / "ai-parrot-tools" / "src" / "parrot_tools"
LOADERS_PKG_DIR = WORKSPACE_ROOT / "packages" / "ai-parrot-loaders" / "src" / "parrot_loaders"

TOOLS_INIT = TOOLS_PKG_DIR / "__init__.py"
LOADERS_INIT = LOADERS_PKG_DIR / "__init__.py"

# Base classes that should NOT appear in registries
TOOL_BASE_CLASSES = frozenset({
    "AbstractTool", "AbstractToolkit", "ToolkitTool", "ToolResult",
    "ToolManager", "ToolkitRegistry",
})
LOADER_BASE_CLASSES = frozenset({
    "AbstractLoader", "BaseLoader", "BasePDF", "BaseVideoLoader",
})

# Naming convention: classes ending with these suffixes are tools/loaders
TOOL_SUFFIXES = ("Tool", "Toolkit")
LOADER_SUFFIXES = ("Loader",)


# ---------------------------------------------------------------------------
# AST-based class scanning
# ---------------------------------------------------------------------------
def scan_classes(
    pkg_dir: Path,
    suffixes: tuple[str, ...],
    base_classes: frozenset[str],
    pkg_name: str,
) -> dict[str, str]:
    """Scan a package directory for classes matching the naming convention.

    Args:
        pkg_dir: Root of the package to scan.
        suffixes: Class name suffixes to match (e.g. ("Tool", "Toolkit")).
        base_classes: Class names to exclude from the registry.
        pkg_name: Python package name (e.g. "parrot_tools").

    Returns:
        dict mapping registry_key → dotted import path.
    """
    registry: dict[str, str] = {}

    for py_file in sorted(pkg_dir.rglob("*.py")):
        if py_file.name.startswith("_"):
            continue

        # Compute dotted module path relative to package
        rel = py_file.relative_to(pkg_dir)
        parts = list(rel.with_suffix("").parts)
        module_path = f"{pkg_name}.{'.'.join(parts)}"

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            class_name = node.name
            # Skip base classes and private classes
            if class_name in base_classes or class_name.startswith("_"):
                continue
            # Match by suffix convention
            if not any(class_name.endswith(s) for s in suffixes):
                continue
            # Build registry key: snake_case-ish from class name
            key = _class_to_key(class_name)
            dotted = f"{module_path}.{class_name}"
            registry[key] = dotted

    return registry


def _class_to_key(name: str) -> str:
    """Convert CamelCase class name to a registry key.

    Examples:
        DuckDuckGoToolkit → ddgo  (if toolkit, use module name convention)
        GoogleSearchTool → google_search
        YoutubeLoader → YoutubeLoader  (loaders use class name as key)
    """
    # For loaders, just use the class name directly
    if name.endswith("Loader"):
        return name
    # For tools/toolkits, convert to snake_case and strip suffix
    result = []
    for i, c in enumerate(name):
        if c.isupper() and i > 0:
            prev = name[i - 1]
            if prev.islower() or prev.isdigit():
                result.append("_")
            elif i + 1 < len(name) and name[i + 1].islower():
                result.append("_")
        result.append(c.lower())
    key = "".join(result)
    # Strip common suffixes
    for suffix in ("_toolkit", "_tool"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
            break
    return key


# ---------------------------------------------------------------------------
# Scan for non-class exports (functions, constants)
# ---------------------------------------------------------------------------
def scan_exports(
    pkg_dir: Path,
    pkg_name: str,
    names: list[str],
) -> dict[str, str]:
    """Scan for specific named exports (functions, constants).

    Args:
        pkg_dir: Root of the package.
        pkg_name: Python package name.
        names: Export names to look for.

    Returns:
        dict mapping name → dotted import path.
    """
    registry: dict[str, str] = {}

    for py_file in sorted(pkg_dir.rglob("*.py")):
        if py_file.name.startswith("_"):
            continue

        rel = py_file.relative_to(pkg_dir)
        parts = list(rel.with_suffix("").parts)
        module_path = f"{pkg_name}.{'.'.join(parts)}"

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and node.name in names:
                registry[node.name] = f"{module_path}.{node.name}"
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in names:
                        registry[target.id] = f"{module_path}.{target.id}"

    return registry


# ---------------------------------------------------------------------------
# Registry formatting
# ---------------------------------------------------------------------------
def format_registry(name: str, entries: dict[str, str], docstring: str) -> str:
    """Format a registry dict as Python source code.

    Args:
        name: Variable name (e.g. "TOOL_REGISTRY").
        entries: key → dotted path mapping.
        docstring: Module docstring.

    Returns:
        Complete __init__.py content.
    """
    lines = [f'"""\n{docstring}\n"""', "", f"{name}: dict[str, str] = {{"]

    for key, path in entries.items():
        lines.append(f'    "{key}": "{path}",')

    lines.append("}")
    lines.append("")  # trailing newline
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Read existing registry from __init__.py
# ---------------------------------------------------------------------------
def read_existing_registry(init_file: Path, var_name: str) -> Optional[dict[str, str]]:
    """Parse the existing registry dict from an __init__.py file.

    Args:
        init_file: Path to __init__.py.
        var_name: Variable name to extract (e.g. "TOOL_REGISTRY").

    Returns:
        dict of existing entries, or None if file doesn't exist.
    """
    if not init_file.exists():
        return None

    try:
        tree = ast.parse(init_file.read_text(encoding="utf-8"))
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == var_name:
                    try:
                        return ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        return None
    return None


# ---------------------------------------------------------------------------
# Update __init__.py preserving structure
# ---------------------------------------------------------------------------
def update_init_file(
    init_file: Path,
    var_name: str,
    new_registry: dict[str, str],
    dry_run: bool = False,
) -> tuple[bool, list[str]]:
    """Update the registry dict in an __init__.py file.

    Args:
        init_file: Path to __init__.py.
        var_name: Variable name (e.g. "TOOL_REGISTRY").
        new_registry: New registry entries.
        dry_run: If True, don't write changes.

    Returns:
        (changed, diff_lines) tuple.
    """
    existing = read_existing_registry(init_file, var_name)
    if existing is None:
        existing = {}

    # Merge: new entries override, but preserve manual entries not found by scan
    merged = dict(new_registry)  # scanned entries take priority
    for key, val in existing.items():
        if key not in merged:
            merged[key] = val  # preserve manual entries

    # Check if anything changed
    if merged == existing:
        return False, []

    # Compute diff
    diff: list[str] = []
    added = set(merged.keys()) - set(existing.keys())
    removed = set(existing.keys()) - set(merged.keys())
    changed_vals = {
        k for k in set(merged.keys()) & set(existing.keys()) if merged[k] != existing[k]
    }

    for k in sorted(added):
        diff.append(f"  + {k}: {merged[k]}")
    for k in sorted(removed):
        diff.append(f"  - {k}: {existing[k]}")
    for k in sorted(changed_vals):
        diff.append(f"  ~ {k}: {existing[k]} → {merged[k]}")

    if not dry_run:
        # Read file, replace the registry dict assignment
        content = init_file.read_text(encoding="utf-8")
        tree = ast.parse(content)

        # Find the assignment line range
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        # Replace from assignment start to end
                        lines = content.splitlines(keepends=True)
                        start_line = node.lineno - 1  # 0-indexed
                        end_line = node.end_lineno  # exclusive

                        # Build new assignment
                        new_lines = [f"{var_name}: dict[str, str] = {{\n"]
                        for key, path in merged.items():
                            new_lines.append(f'    "{key}": "{path}",\n')
                        new_lines.append("}\n")

                        # Replace
                        lines[start_line:end_line] = new_lines
                        init_file.write_text("".join(lines), encoding="utf-8")
                        return True, diff

    return bool(diff), diff


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate/validate TOOL_REGISTRY and LOADER_REGISTRY"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing files",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI mode: exit 1 if registries are stale",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--tools-only",
        action="store_true",
        help="Only scan/update tools registry",
    )
    parser.add_argument(
        "--loaders-only",
        action="store_true",
        help="Only scan/update loaders registry",
    )
    args = parser.parse_args()

    if args.check:
        args.dry_run = True  # --check implies dry-run

    do_tools = not args.loaders_only
    do_loaders = not args.tools_only

    any_stale = False

    # --- Tools ---
    if do_tools and TOOLS_PKG_DIR.exists():
        if args.verbose:
            print(f"Scanning {TOOLS_PKG_DIR} ...")

        scanned = scan_classes(
            TOOLS_PKG_DIR, TOOL_SUFFIXES, TOOL_BASE_CLASSES, "parrot_tools"
        )

        if args.verbose:
            print(f"  Found {len(scanned)} tool classes")

        changed, diff = update_init_file(
            TOOLS_INIT, "TOOL_REGISTRY", scanned, dry_run=args.dry_run
        )

        if changed:
            any_stale = True
            action = "Would update" if args.dry_run else "Updated"
            print(f"{action} TOOL_REGISTRY ({len(diff)} changes):")
            for line in diff:
                print(line)
        elif args.verbose:
            print("  TOOL_REGISTRY is up to date")

    # --- Loaders ---
    if do_loaders and LOADERS_PKG_DIR.exists():
        if args.verbose:
            print(f"Scanning {LOADERS_PKG_DIR} ...")

        scanned = scan_classes(
            LOADERS_PKG_DIR, LOADER_SUFFIXES, LOADER_BASE_CLASSES, "parrot_loaders"
        )
        # Also scan for factory exports
        factory_exports = scan_exports(
            LOADERS_PKG_DIR, "parrot_loaders", ["get_loader_class", "LOADER_MAPPING"]
        )
        scanned.update(factory_exports)

        if args.verbose:
            print(f"  Found {len(scanned)} loader classes/exports")

        changed, diff = update_init_file(
            LOADERS_INIT, "LOADER_REGISTRY", scanned, dry_run=args.dry_run
        )

        if changed:
            any_stale = True
            action = "Would update" if args.dry_run else "Updated"
            print(f"{action} LOADER_REGISTRY ({len(diff)} changes):")
            for line in diff:
                print(line)
        elif args.verbose:
            print("  LOADER_REGISTRY is up to date")

    # --- Result ---
    if args.check and any_stale:
        print("\nRegistries are STALE. Run: python scripts/generate_tool_registry.py")
        return 1

    if not any_stale:
        print("All registries are up to date.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
