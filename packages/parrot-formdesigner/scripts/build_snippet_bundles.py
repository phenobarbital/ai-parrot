#!/usr/bin/env python
"""Build-time TS -> JS compiler for snippet bundles (FEAT-459 / M14).

NEVER invoked at request time — a CI/authoring-time script only. Compiles
each bundle's optional client.ts (TASK-3164's directory layout) to
client.js via `esbuild`, then rewrites manifest.json's client_sha256.

Usage:
    python scripts/build_snippet_bundles.py --root path/to/snippet_bundles
    python scripts/build_snippet_bundles.py --root ... --check   # CI dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

MANIFEST_FILENAME = "manifest.json"
TS_SOURCE_FILENAME = "client.ts"
JS_OUTPUT_FILENAME = "client.js"


class EsbuildNotFoundError(Exception):
    """Raised when `esbuild` is required (a bundle declares client.ts) but absent."""


def _find_bundle_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir())


def _compile_one(bundle_dir: Path, *, check_only: bool) -> bool:
    """Compile one bundle's client.ts, if present.

    Args:
        check_only: When True, do NOT write client.js — only report
            whether it would change (CI dry-run mode).

    Returns:
        True if this bundle has (or would need) a client.js update.

    Raises:
        EsbuildNotFoundError: client.ts is present but `esbuild` is not on PATH.
        subprocess.CalledProcessError: esbuild exited non-zero.
    """
    ts_path = bundle_dir / TS_SOURCE_FILENAME
    if not ts_path.exists():
        return False
    if shutil.which("esbuild") is None:
        raise EsbuildNotFoundError(
            f"{bundle_dir.name} declares {TS_SOURCE_FILENAME} but `esbuild` "
            "is not on PATH. Install esbuild (or swc) to build snippet client halves."
        )
    js_path = bundle_dir / JS_OUTPUT_FILENAME
    result = subprocess.run(
        ["esbuild", str(ts_path), "--bundle", "--minify", "--format=iife"],
        capture_output=True,
        text=True,
        check=True,
    )
    new_js = result.stdout
    changed = not js_path.exists() or js_path.read_text() != new_js
    if changed and not check_only:
        js_path.write_text(new_js)
        _update_manifest_hash(bundle_dir, new_js)
    return changed


def _update_manifest_hash(bundle_dir: Path, js_source: str) -> None:
    manifest_path = bundle_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text())
    manifest["client_sha256"] = hashlib.sha256(js_source.encode("utf-8")).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Snippet bundle root directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI dry-run: exit non-zero if any client.js is stale, without writing",
    )
    args = parser.parse_args(argv)

    any_changed = False
    try:
        for bundle_dir in _find_bundle_dirs(args.root):
            if _compile_one(bundle_dir, check_only=args.check):
                any_changed = True
                print(f"{'STALE' if args.check else 'built'}: {bundle_dir.name}")
    except EsbuildNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"esbuild failed for a bundle: {exc.stderr}", file=sys.stderr)
        return 1

    if args.check and any_changed:
        print(
            "error: one or more client.js files are stale — run without --check",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
