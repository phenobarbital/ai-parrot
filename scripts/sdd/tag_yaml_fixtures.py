"""scripts/sdd/tag_yaml_fixtures.py

Idempotently inserts ``tenant: navigator`` into YAML form fixtures that
declare ``form_id:`` but lack a top-level ``tenant:`` field.

Usage::

    python -m scripts.sdd.tag_yaml_fixtures [--dry-run] [--roots PATH ...]

The default roots are the in-repo YAML fixture locations relevant to
``parrot-formdesigner``.  Pass ``--roots`` to override them.

Idempotency guarantee:
    Running the script twice against the same directory produces no diff on
    the second run.  The script checks for an existing ``tenant:`` key in
    the parsed YAML before writing.

Diff-minimal strategy:
    The script inserts a single line ``tenant: navigator`` immediately after
    the line that starts with ``form_id:``, preserving all other formatting.
    It does NOT round-trip the YAML through ``yaml.safe_dump()``.

CI integration (follow-up):
    Add ``python -m scripts.sdd.tag_yaml_fixtures --dry-run`` to the CI
    lint step after merging FEAT-183 to ensure new fixtures always carry
    ``tenant:``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

DEFAULT_ROOTS: list[str] = [
    "packages/parrot-formdesigner/tests",
    "examples/forms",
    "tests/forms",
]
DEFAULT_TENANT = "navigator"
LOG = logging.getLogger("tag_yaml_fixtures")


def is_form_fixture(parsed: object) -> bool:
    """Return True when *parsed* looks like a form fixture dict.

    A form fixture is identified by having ``form_id`` as a top-level key
    in a YAML mapping.

    Args:
        parsed: Python object parsed from YAML.

    Returns:
        True if *parsed* is a dict with a ``form_id`` key.
    """
    return isinstance(parsed, dict) and "form_id" in parsed


def already_tagged(parsed: dict) -> bool:  # type: ignore[type-arg]
    """Return True when the YAML dict already carries a ``tenant:`` key.

    Args:
        parsed: Python dict parsed from YAML.

    Returns:
        True if ``tenant`` is present at the top level.
    """
    return "tenant" in parsed


def tag_file(path: Path, *, dry_run: bool = False) -> str:
    """Inspect and (conditionally) tag a single YAML file.

    The insertion is diff-minimal: one line ``tenant: navigator`` is inserted
    immediately after the first line that begins with ``form_id:`` (matching
    the indent of that line).  If no ``form_id:`` line is found (very unlikely
    for a detected form fixture), the line is appended at the end.

    Args:
        path: Path to the YAML file to inspect/modify.
        dry_run: When ``True``, report what would be done without writing.

    Returns:
        One of:
        - ``"tagged"``: file was (or would be, in dry-run) tagged.
        - ``"already"``: file already has ``tenant:``; left untouched.
        - ``"not-a-fixture"``: file lacks ``form_id:`` at root; skipped.
        - ``"parse-error"``: YAML parse failed; skipped.
    """
    try:
        content = path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
    except Exception as exc:
        LOG.debug("parse error %s: %s", path, exc)
        return "parse-error"

    if not is_form_fixture(parsed):
        return "not-a-fixture"

    if already_tagged(parsed):
        return "already"

    if dry_run:
        return "tagged"

    # Diff-minimal insertion: insert tenant: after the form_id: line.
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.lstrip().startswith("form_id:"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}tenant: {DEFAULT_TENANT}\n")
            inserted = True

    if not inserted:
        # Fallback: append at end (very unlikely — form_id: must be present
        # for is_form_fixture() to return True, so we always reach the above
        # branch under normal circumstances).
        out.append(f"tenant: {DEFAULT_TENANT}\n")

    path.write_text("".join(out), encoding="utf-8")
    return "tagged"


def main(argv: list[str] | None = None) -> int:
    """Entry point for the fixture tagger.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (always 0 on success regardless of how many files were
        tagged; non-zero only on unexpected errors).
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would be changed without writing files.",
    )
    parser.add_argument(
        "--roots",
        nargs="*",
        default=DEFAULT_ROOTS,
        metavar="PATH",
        help=(
            "Root directories to search for YAML fixtures. "
            "Defaults to the in-repo parrot-formdesigner fixture roots."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    counts: dict[str, int] = {
        "tagged": 0,
        "already": 0,
        "not-a-fixture": 0,
        "parse-error": 0,
    }

    for root_str in args.roots:
        root_path = Path(root_str)
        if not root_path.exists():
            LOG.info("skip missing root %s", root_path)
            continue

        yaml_files = list(root_path.rglob("*.yaml")) + list(root_path.rglob("*.yml"))
        for yaml_file in sorted(yaml_files):
            result = tag_file(yaml_file, dry_run=args.dry_run)
            counts[result] += 1
            if result == "tagged":
                action = "would-tag" if args.dry_run else "tagged"
                LOG.info("%s %s", action, yaml_file)
            elif result == "parse-error":
                LOG.debug("parse-error %s", yaml_file)

    LOG.info("summary: %s", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
