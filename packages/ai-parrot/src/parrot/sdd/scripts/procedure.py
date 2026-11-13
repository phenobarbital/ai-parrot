"""``parrot sdd procedure`` — build, inspect and check the procedure graph (FEAT-891)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from parrot.knowledge.wiki.procedure.index import is_stale, read_index
from parrot.knowledge.wiki.procedure.models import PLANE_DIR, ProcedureSpec
from parrot.knowledge.wiki.procedure.plane import ProcedurePlane
from parrot.knowledge.wiki.procedure.producers import load_manifest, manifest_specs
from parrot.knowledge.wiki.procedure.validate import validate_graph
from parrot.knowledge.wiki.project import find_shared_root
from parrot.sdd.config import ProcedureSettings, SddConfigError, load_sdd_config
from parrot.sdd.scripts.procedure_probes import PROBE_COSTS

COMMANDS_DIR = Path(__file__).resolve().parent.parent / "_assets" / "claude" / "commands"


def _settings(root: Path) -> ProcedureSettings:
    """Return procedure settings, warning and using defaults for an invalid config."""
    try:
        config = load_sdd_config(root)
    except SddConfigError as exc:
        message = " ".join(str(exc).splitlines())
        sys.stderr.write(f"warning: {message}\n")
        return ProcedureSettings()
    return config.procedure or ProcedureSettings()


async def build(root: Path) -> dict[str, int]:
    """Validate manifest specs, then rebuild the procedure plane."""
    specs, sources = manifest_specs(root)
    findings = validate_graph(specs, known_probes=PROBE_COSTS)
    errors = [finding for finding in findings if finding.severity == "error"]
    if errors:
        details = "\n".join(f"{finding.code}: {finding.message}" for finding in errors)
        raise ValueError(details)
    return await ProcedurePlane(root / PLANE_DIR).build(specs, sources, root=root, probe_costs=PROBE_COSTS)


def _load_specs(root: Path) -> tuple[list[ProcedureSpec], bool]:
    """Return stored specs and staleness, rebuilding a stale plane when possible."""
    plane_dir = root / PLANE_DIR
    document = read_index(plane_dir)
    if is_stale(document, root=root):
        try:
            asyncio.run(build(root))
        except Exception as exc:
            reason = " ".join(str(exc).splitlines()) or exc.__class__.__name__
            sys.stderr.write(f"procedure plane is stale: {reason}\n")
        document = read_index(plane_dir)
    stale = is_stale(document, root=root)
    return asyncio.run(ProcedurePlane(plane_dir).specs()), stale


def _known_commands(root: Path, sources: Sequence[Path]) -> list[str]:
    """Return packaged SDD command names not exempted by a manifest."""
    uncovered_ok: set[str] = set()
    for source in sources:
        uncovered_ok.update(load_manifest(source, root=root).uncovered_ok)
    return sorted(path.stem for path in COMMANDS_DIR.glob("sdd-*.md") if path.stem not in uncovered_ok)


def _repository_root(start: Path | None = None) -> Path | None:
    """Resolve the primary checkout or report that no repository is available."""
    root = find_shared_root(start or Path.cwd())
    if root is None:
        sys.stderr.write("no repository found\n")
    return root


def _cmd_build(args: argparse.Namespace) -> int:
    """Build the procedure plane and report its object counts."""
    root = _repository_root(args.root)
    if root is None:
        return 2
    _settings(root)
    try:
        counts = asyncio.run(build(root))
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write(
        f"procedure plane: {counts['pages']} pages, {counts['edges']} edges, {counts['sources']} sources\n"
    )
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List stored procedure nodes, optionally filtered by mode."""
    root = _repository_root()
    if root is None:
        return 2
    _settings(root)
    specs, _ = _load_specs(root)
    selected = sorted(
        (spec for spec in specs if args.mode is None or spec.mode == args.mode),
        key=lambda spec: spec.id,
    )
    if args.json:
        payload = [spec.model_dump(mode="json") for spec in selected]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        for spec in selected:
            sys.stdout.write(f"{spec.id}  {spec.mode}  {spec.scope_kind}  {spec.title}\n")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    """Show one stored procedure node."""
    root = _repository_root()
    if root is None:
        return 2
    _settings(root)
    specs, _ = _load_specs(root)
    spec = next((item for item in specs if item.id == args.id), None)
    if spec is None:
        sys.stderr.write(f"unknown procedure: {args.id}\n")
        return 1
    payload = spec.model_dump(mode="json")
    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        for name, value in payload.items():
            rendered = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
            sys.stdout.write(f"{name}: {rendered}\n")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    """Validate procedure manifests and report deterministic findings."""
    root = _repository_root()
    if root is None:
        return 2
    _settings(root)
    try:
        specs, sources = manifest_specs(root)
        if not sources:
            sys.stdout.write("no procedure manifest\n")
            return 0
        known_commands = _known_commands(root, sources)
    except ValueError as exc:
        message = " ".join(str(exc).splitlines())
        sys.stderr.write(f"{message}\n")
        return 1
    findings = validate_graph(specs, known_probes=PROBE_COSTS, known_commands=known_commands)
    if args.json:
        payload = [finding.model_dump(mode="json") for finding in findings]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        for finding in findings:
            subjects = ", ".join(finding.subjects) or "-"
            sys.stdout.write(f"{finding.severity} {finding.code} {subjects}: {finding.message}\n")
    return 1 if any(finding.severity == "error" for finding in findings) else 0


def _parser() -> argparse.ArgumentParser:
    """Build the procedure CLI parser."""
    parser = argparse.ArgumentParser(prog="parrot sdd procedure", description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    p_build = sub.add_parser("build", help="Fold the manifests into the plane and publish the index.")
    p_build.add_argument("--root", type=Path, default=None)
    p_build.set_defaults(func=_cmd_build)
    p_list = sub.add_parser("list", help="List procedure nodes.")
    p_list.add_argument("--mode", choices=("advisory", "mandatory", "constraint"))
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)
    p_show = sub.add_parser("show", help="Show one node.")
    p_show.add_argument("id")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(func=_cmd_show)
    p_check = sub.add_parser("check", help="Validate the graph; exit 1 on any error finding.")
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=_cmd_check)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch build, list, show, or check and return its process exit code."""
    args = _parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
