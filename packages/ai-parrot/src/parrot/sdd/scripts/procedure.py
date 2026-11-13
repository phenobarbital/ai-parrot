"""``parrot sdd procedure`` — build, inspect and check the procedure graph (FEAT-891)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from parrot.knowledge.wiki.procedure.index import is_stale, read_index
from parrot.knowledge.wiki.procedure.models import PLANE_DIR, ProcedureSpec, Resolution
from parrot.knowledge.wiki.procedure.plane import ProcedurePlane
from parrot.knowledge.wiki.procedure.producers import load_manifest, manifest_specs
from parrot.knowledge.wiki.procedure.resolver import resolve
from parrot.knowledge.wiki.procedure.validate import validate_graph
from parrot.knowledge.wiki.project import find_shared_root
from parrot.sdd.config import ProcedureSettings, SddConfigError, load_sdd_config
from parrot.sdd.scripts.procedure_advice import checkout_root
from parrot.sdd.scripts.procedure_probes import PROBE_COSTS, SddProbeRunner, scope_for

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


def _render_check(probe: str, expect: bool | str) -> str:
    """Render a probe name and its string expectation when one is configured."""
    return f"{probe}={expect}" if isinstance(expect, str) else probe


def render_brief(resolution: Resolution, *, max_lines: int) -> str:
    """Render the task-start procedure block, or an empty string when nothing applies."""
    if not resolution.next and not resolution.mandatory or max_lines <= 0:
        return ""

    feature = resolution.scope.get("feature", "unknown")
    task = resolution.scope.get("task", "unknown")
    lines = ["### Procedure", f"Position: feature `{feature}`, task `{task}`."]
    for item in resolution.next:
        line = f"Next: {item.spec.title} — `{item.spec.command}`"
        unmet = [
            _render_check(result.check.probe, result.check.expect)
            for result in item.preconditions
            if result.value is not True
        ]
        if unmet:
            line += f" (unmet: {', '.join(unmet)})"
        lines.append(line)

    if resolution.mandatory:
        lines.append("Mandatory:")
        for spec in resolution.mandatory:
            line = f"- {spec.title}: `{spec.command}`"
            if spec.use_instead:
                line += f" (never by hand; use `{spec.use_instead}`)"
            lines.append(line)

    return "\n".join(lines[:max_lines])


def _scope_from_task_file(path: Path) -> tuple[str | None, str | None]:
    """Return ``(feature slug, task id)`` parsed from a task filename and Spec header."""
    try:
        parts = path.stem.split("-")
        if len(parts) < 3:
            return None, None
        if parts[0] == "TASK" and parts[1].isdigit():
            task_id = "-".join(parts[:2])
        elif parts[0] == "HOTFIX":
            digit_indexes = [index for index, part in enumerate(parts[1:], 1) if part.isdigit()]
            if not digit_indexes or digit_indexes[-1] == len(parts) - 1:
                return None, None
            digit_index = digit_indexes[-1]
            task_id = "-".join(parts[: digit_index + 1])
        else:
            return None, None

        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("**Spec**:"):
                continue
            _, _, value = line.partition(":")
            spec_path = value.strip().strip("`")
            if not spec_path.endswith(".spec.md"):
                return None, None
            feature = Path(spec_path).name.removesuffix(".spec.md")
            return (feature, task_id) if feature else (None, None)
    except (OSError, ValueError):
        return None, None
    return None, None


def _cmd_next(args: argparse.Namespace) -> int:
    """Resolve and print the procedures applicable to the current checkout state."""
    root = _repository_root()
    if root is None:
        return 2
    settings = _settings(root)
    specs, stale = _load_specs(root)
    checkout = checkout_root(Path.cwd()) or root
    scope = scope_for(checkout, feature=args.feature, task=args.task)
    resolution = resolve(
        specs,
        scope,
        SddProbeRunner(checkout, timeout=settings.remote_probe_timeout_seconds),
        allow_remote=not args.no_remote,
        stale=stale,
    )
    if args.json:
        sys.stdout.write(resolution.model_dump_json(indent=2) + "\n")
        return 0

    scope_text = ", ".join(f"{key}={value}" for key, value in sorted(resolution.scope.items()))
    sys.stdout.write(f"scope: {scope_text}\n")
    for item in resolution.next:
        line = f"{item.spec.id}  {item.spec.mode}  {item.spec.command}"
        unmet = [
            _render_check(result.check.probe, result.check.expect)
            for result in item.preconditions
            if result.value is not True
        ]
        if unmet:
            line += f"  unmet: {', '.join(unmet)}"
        sys.stdout.write(f"{line}\n")
    for spec in resolution.mandatory:
        sys.stdout.write(f"mandatory: {spec.id}  {spec.mode}  {spec.command}\n")
    return 0


def _cmd_brief(args: argparse.Namespace) -> int:
    """Print a task-start procedure block without allowing failures to block task starts."""
    try:
        root = find_shared_root(Path.cwd())
        if root is None:
            return 0
        settings = _settings(root)
        if not settings.enabled:
            return 0
        feature, task = _scope_from_task_file(args.task_file)
        if feature is None or task is None:
            return 0
        if not (root / PLANE_DIR / "procedures.json").is_file():
            return 0
        specs, stale = _load_specs(root)
        if stale:
            return 0
        checkout = checkout_root(Path.cwd()) or root
        resolution = resolve(
            specs,
            scope_for(checkout, feature=feature, task=task),
            SddProbeRunner(checkout, timeout=settings.remote_probe_timeout_seconds),
            allow_remote=False,
            stale=False,
        )
        max_lines = settings.brief_max_lines if args.max_lines is None else args.max_lines
        brief = render_brief(resolution, max_lines=max_lines)
        if brief:
            sys.stdout.write(f"{brief}\n")
    except Exception:
        return 0
    return 0


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
    p_next = sub.add_parser("next", help="Applicable procedures and the valid next step(s).")
    p_next.add_argument("--feature")
    p_next.add_argument("--task")
    p_next.add_argument("--no-remote", action="store_true")
    p_next.add_argument("--json", action="store_true")
    p_next.set_defaults(func=_cmd_next)
    p_brief = sub.add_parser("brief", help="Print the task-start procedure block.")
    p_brief.add_argument("--task-file", type=Path, required=True)
    p_brief.add_argument("--max-lines", type=int, default=None)
    p_brief.set_defaults(func=_cmd_brief)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch build, list, show, next, check, or brief and return its process exit code."""
    args = _parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
