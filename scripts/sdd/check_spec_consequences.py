"""Decision-audit gate for SDD specs (FEAT-784 M9).

Exit matrix: 0 pass|skipped · 1 conflict · 2 invalid · 3 incomplete (also stale/missing generated
sections and any operational failure). ``--advisory`` (the /sdd-task form) always returns 0 and only
prints a warning when an existing report is contrary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.decisions.consequences_render import check_spec, render_spec
from parrot.knowledge.wiki.decisions.models import AUDIT_NOT_CONFIGURED
from parrot.knowledge.wiki.decisions.render import DEFAULT_BUDGET_TOKENS
from parrot.knowledge.wiki.decisions.spec_audit import is_configured, open_consequence_service
from parrot.knowledge.wiki.decisions.spec_entries import DECISIONS_HEADING, extract_block

EXIT_BY_STATUS = {"pass": 0, "skipped": 0, "conflict": 1, "invalid": 2, "incomplete": 3}
EXIT_OPERATIONAL = 3
NOT_CONFIGURED_LINE = "decision audit not configured in this repository"


def _unconfigured(spec_text: str) -> tuple[int, dict[str, Any]]:
    """Return the portability result for a repository without audit configuration."""
    yaml_source, _start, _end = extract_block(spec_text, DECISIONS_HEADING)
    if yaml_source is None:
        return 0, {"status": "skipped", "exit_code": 0, "message": NOT_CONFIGURED_LINE}
    return 2, {
        "status": "invalid",
        "exit_code": 2,
        "diagnostics": [
            {"code": AUDIT_NOT_CONFIGURED, "message": "spec declares decisions but the repo is not configured"}
        ],
    }


async def _run(spec: Path, root: Path, base_branch: str, *, render: bool, budget: int) -> tuple[int, dict[str, Any], str]:
    """Return ``(exit_code, json_payload, check_status)`` for the configured repository."""
    service = open_consequence_service(root, base_branch=base_branch)
    if render:
        report = await render_spec(service, spec, budget_tokens=budget)
        return EXIT_BY_STATUS[report.status], report.model_dump(mode="json"), "rendered"

    result = await check_spec(service, spec)
    payload = result.report.model_dump(mode="json") | {"check": result.status}
    if result.status == "current":
        return EXIT_BY_STATUS[result.report.status], payload, result.status

    payload["message"] = f"consequences-{result.status}"
    return EXIT_OPERATIONAL, payload, result.status


def _operational_payload(exc: Exception) -> dict[str, Any]:
    """Return a deterministic payload for an operational gate failure."""
    return {"status": "incomplete", "exit_code": EXIT_OPERATIONAL, "message": str(exc)}


def _human_line(payload: dict[str, Any]) -> str:
    """Return the compact non-JSON CLI rendering for a gate payload."""
    if payload.get("message") == NOT_CONFIGURED_LINE:
        return NOT_CONFIGURED_LINE
    return f"{payload.get('status', 'incomplete')}: {len(payload.get('findings', []))} finding(s)"


def _requires_advisory_warning(payload: dict[str, Any], check_status: str) -> bool:
    """Return whether advisory mode must report a non-blocking warning."""
    return check_status == "stale" or payload.get("status") in {"conflict", "invalid", "incomplete"}


def main(argv: list[str] | None = None) -> int:
    """Run the decision-audit gate and return its frozen exit-matrix code."""
    parser = argparse.ArgumentParser(description="Check a spec's declared decisions against the decision plane.")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--base-branch", default="dev")
    parser.add_argument("--json", action="store_true", help="Emit the ConsequenceReport as JSON.")
    parser.add_argument("--render", action="store_true", help="Write ## Governing Decisions and ## Consequences.")
    parser.add_argument("--advisory", action="store_true", help="Warn instead of failing (the /sdd-task form).")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET_TOKENS)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    spec = args.spec if args.spec.is_absolute() else root / args.spec

    try:
        spec_text = spec.read_text(encoding="utf-8")
        if not is_configured(root):
            exit_code, payload = _unconfigured(spec_text)
            check_status = "unconfigured"
        else:
            exit_code, payload, check_status = asyncio.run(
                _run(spec, root, args.base_branch, render=args.render, budget=args.budget)
            )
    except Exception as exc:
        exit_code = EXIT_OPERATIONAL
        payload = _operational_payload(exc)
        check_status = "operational-failure"

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))  # noqa: T201 - CLI output
    elif not args.advisory:
        print(_human_line(payload))  # noqa: T201 - CLI output

    if args.advisory:
        if _requires_advisory_warning(payload, check_status):
            print(f"warning: {_human_line(payload)}", file=sys.stderr)  # noqa: T201 - CLI warning
        return 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
