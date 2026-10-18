"""Nightly red set: junit directory -> failed/error node ids per suite (FEAT-699).

Stdlib-only on purpose: it must not import ``parrot``.

Usage: ``nightly_red_set.py <junit_dir> --out <json> [--previous <json>]``.
Exits 1 when there are reds that were not in the previous red set.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def nodeid_from_testcase(classname: str, name: str) -> str:
    """Rebuild a pytest node id from an xunit1 ``classname``/``name`` pair.

    The module path is every dotted part up to and including the first part
    starting with ``test_`` (or the whole classname when none does); remaining
    parts are class names.

    Args:
        classname: The ``classname`` attribute of the testcase.
        name: The ``name`` attribute of the testcase.

    Returns:
        A ``path/to/test_mod.py::Class::test_name`` style node id.
    """
    parts = [p for p in classname.split(".") if p]
    if not parts:
        return name
    split = len(parts)
    for idx, part in enumerate(parts):
        if part.startswith("test_") or part == "conftest":
            split = idx + 1
            break
    module = "/".join(parts[:split]) + ".py"
    return "::".join([module, *parts[split:], name])


def collect_reds(junit_dir: Path) -> dict[str, list[str]]:
    """Collect failed/errored node ids per suite from ``<suite>.xml`` files."""
    suites: dict[str, list[str]] = {}
    for xml_path in sorted(junit_dir.rglob("*.xml")):
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError:
            logger.warning("unparseable junit file: %s", xml_path)
            continue
        reds: set[str] = set()
        for case in root.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                reds.add(nodeid_from_testcase(case.get("classname", ""), case.get("name", "")))
        suites[xml_path.stem] = sorted(reds)
    return suites


def diff_new_reds(current: dict[str, list[str]], previous: dict[str, list[str]]) -> list[str]:
    """Return ``suite::nodeid`` entries red now but not in the previous set."""
    new: list[str] = []
    for suite, nodes in sorted(current.items()):
        known = set(previous.get(suite, []))
        new.extend(f"{suite}::{n}" for n in nodes if n not in known)
    return new


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns 1 when new reds exist, else 0."""
    parser = argparse.ArgumentParser(prog="nightly_red_set")
    parser.add_argument("junit_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--previous", type=Path, default=None)
    args = parser.parse_args(argv)

    current = collect_reds(args.junit_dir)
    previous: dict[str, list[str]] = {}
    if args.previous is not None and args.previous.is_file():
        try:
            previous = json.loads(args.previous.read_text(encoding="utf-8")).get("suites", {})
        except (ValueError, OSError):
            logger.warning("unreadable previous red set: %s", args.previous)
    new_reds = diff_new_reds(current, previous)
    payload = {"suites": current, "new_reds": new_reds}
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    total = sum(len(v) for v in current.values())
    sys.stdout.write(f"Red tests: {total}; new vs previous: {len(new_reds)}\n")
    for item in new_reds:
        sys.stdout.write(f"- NEW RED {item}\n")
    return 1 if new_reds else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
