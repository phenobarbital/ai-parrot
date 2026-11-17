"""Helpers behind /sdd-spec's design-research and intake sub-flows (FEAT-633 Q1 residual).

Replaces the inline ``python -c`` blocks of the shipped ``/sdd-spec`` and ``/sdd-task``
commands so a foreign repository needs no interpreter on ``PATH``: TASK-4088 moves this
module into ``parrot.sdd.scripts`` and TASK-4089 rewrites the invocations to
``parrot sdd run spec_tools …``. Every failure goes to stderr with exit code 1 so the
shell ``|| SKIP_REASON=…`` / ``$(…)`` consumers around each call keep working unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from parrot.sdd.scripts.reserve_ids import existing_feature_id

BRIEF_INPUTS: tuple[str, ...] = (
    "problem_statement",
    "constraints_and_goals",
    "recommended_option_or_scope",
    "code_context_paths",
    "open_questions",
    "question",
)
DEFAULT_PROMPT = Path("sdd/templates/design_research.prompt.md")
DEFAULT_SCHEMA = Path("sdd/templates/design_research.schema.json")


def _fail(msg: str) -> int:
    """Print ``msg`` to stderr and return the failure exit code."""
    print(f"spec_tools: {msg}", file=sys.stderr)
    return 1


def _load_json(path: Path) -> dict:
    """Load a JSON object from ``path`` (raises ``OSError`` / ``ValueError``)."""
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, data: dict) -> None:
    """Write ``data`` as 2-space-indented JSON, same shape as the legacy inline blocks."""
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def cmd_init_run(a: argparse.Namespace) -> int:
    """Write ``<dir>/run.json`` describing the codex design-research run."""
    probe_path = Path(a.probe_file) if a.probe_file else None
    probe = probe_path.read_text(encoding="utf-8") if probe_path and probe_path.is_file() else ""
    payload = {
        "model": a.model,
        "codex_cli_version": a.codex_version,
        "reasoning_effort": "high",
        "timeout_s": 600,
        "probe_output": probe,
    }
    try:
        _dump_json(Path(a.dir) / "run.json", payload)
    except OSError as exc:
        return _fail(f"cannot write run.json: {exc}")
    return 0


def cmd_render_brief(a: argparse.Namespace) -> int:
    """Render ``<dir>/brief.md`` from the prompt template and the six ``<name>.txt`` inputs."""
    dr = Path(a.dir)
    try:
        rendered = Path(a.template).read_text(encoding="utf-8")
        for name in BRIEF_INPUTS:
            value = (dr / f"{name}.txt").read_text(encoding="utf-8").strip()
            rendered = rendered.replace("{{" + name + "}}", value)
    except OSError as exc:
        return _fail(f"brief input missing: {exc}")
    if "{{" in rendered:
        return _fail("unfilled placeholder remains")
    (dr / "brief.md").write_text(rendered, encoding="utf-8")
    return 0


def cmd_stamp_run(a: argparse.Namespace) -> int:
    """Add ``started_at`` / ``ended_at`` / ``exit_code`` to an existing ``<dir>/run.json``."""
    path = Path(a.dir) / "run.json"
    try:
        data = _load_json(path)
    except (OSError, ValueError) as exc:
        return _fail(f"cannot read {path}: {exc}")
    data["started_at"] = a.started_at
    data["ended_at"] = a.ended_at
    data["exit_code"] = int(a.exit_code)
    _dump_json(path, data)
    return 0


def cmd_validate_suggestions(a: argparse.Namespace) -> int:
    """Validate ``<dir>/suggestions.json`` against the design-research schema."""
    try:
        schema = _load_json(Path(a.schema))
        doc = _load_json(Path(a.dir) / "suggestions.json")
        Draft202012Validator(schema).validate(doc)
        count = len(doc["suggestions"])
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        return _fail(f"suggestions.json failed schema validation: {exc}")
    print(f"{count} suggestions")
    return 0


def cmd_check_path(a: argparse.Namespace) -> int:
    """Exit 0 iff ``path`` resolves to ``root`` or somewhere inside it. Prints nothing."""
    p, root = os.path.realpath(a.path), os.path.realpath(a.root)
    return 0 if p == root or p.startswith(root + os.sep) else 1


def cmd_commit_intake(a: argparse.Namespace) -> int:
    """Stamp an intake ``intake.json`` with its feature id and ``phase: committed``."""
    path = Path(a.intake_json)
    try:
        data = _load_json(path)
    except (OSError, ValueError) as exc:
        return _fail(f"cannot read {path}: {exc}")
    data["feat_id"] = a.feat_id
    data["phase"] = "committed"
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _dump_json(path, data)
    return 0


def cmd_existing_feature_id(a: argparse.Namespace) -> int:
    """Print the feature id a slug already owns, or an empty line; always exit 0."""
    found = existing_feature_id(Path(a.root), a.label)
    print(found[0] if found else "")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse CLI with one sub-command per retired inline block."""
    p = argparse.ArgumentParser(
        prog="python -m parrot.sdd.scripts.spec_tools",
        description="Helpers behind /sdd-spec's design-research and intake sub-flows.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-run", help="write <dir>/run.json for a codex design-research run")
    s.add_argument("dir")
    s.add_argument("--model", required=True)
    s.add_argument("--codex-version", required=True)
    s.add_argument("--probe-file", default=None, help="probe output file; missing ⇒ empty string")
    s.set_defaults(func=cmd_init_run)

    s = sub.add_parser("render-brief", help="render <dir>/brief.md from the prompt template")
    s.add_argument("dir")
    s.add_argument("--template", default=str(DEFAULT_PROMPT))
    s.set_defaults(func=cmd_render_brief)

    s = sub.add_parser("stamp-run", help="add timing + exit code to <dir>/run.json")
    s.add_argument("dir")
    s.add_argument("--started-at", required=True)
    s.add_argument("--ended-at", required=True)
    s.add_argument("--exit-code", required=True, type=int)
    s.set_defaults(func=cmd_stamp_run)

    s = sub.add_parser("validate-suggestions", help="validate <dir>/suggestions.json against the schema")
    s.add_argument("dir")
    s.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    s.set_defaults(func=cmd_validate_suggestions)

    s = sub.add_parser("check-path", help="exit 0 iff PATH is inside --root")
    s.add_argument("path")
    s.add_argument("--root", default=".")
    s.set_defaults(func=cmd_check_path)

    s = sub.add_parser("commit-intake", help="stamp intake.json with --feat-id and phase=committed")
    s.add_argument("intake_json")
    s.add_argument("--feat-id", required=True)
    s.set_defaults(func=cmd_commit_intake)

    s = sub.add_parser("existing-feature-id", help="print the FEAT id a slug already owns (or nothing)")
    s.add_argument("label")
    s.add_argument("--root", default=".")
    s.set_defaults(func=cmd_existing_feature_id)
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
