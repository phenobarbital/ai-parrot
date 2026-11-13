"""CLI lifecycle operations for the experience plane."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from parrot.knowledge.wiki.experience.graduation import graduate
from parrot.knowledge.wiki.experience.models import Lesson, LessonDraft, LessonTrigger
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.experience.sync import export_shared, register_namespace, sync_global
from parrot.knowledge.wiki.ledger.service import LedgerService

logger = logging.getLogger(__name__)

_MAX_TASK_FILE_BYTES = 1024 * 1024
_STATES = ("candidate", "confirmed", "quarantined", "retired")
_TIERS = ("repo", "global")


def _parser() -> argparse.ArgumentParser:
    """Build the experience lifecycle argument parser."""
    parser = argparse.ArgumentParser(prog="parrot sdd experience", description=__doc__)
    verbs = parser.add_subparsers(dest="verb", required=True)

    verbs.add_parser("init", help="Initialize the experience plane.")

    brief = verbs.add_parser("brief", help="Show known pitfalls for a task.")
    brief.add_argument("--task-file", required=True, type=Path)
    brief.add_argument("--max", dest="max_entries", type=int, default=None)

    record = verbs.add_parser("record", help="Record a candidate lesson.")
    record.add_argument("--executable", required=True)
    record.add_argument("--solution", required=True)
    record.add_argument("--subcommand", default="")
    record.add_argument("--error", default="")
    record.add_argument("--symptom", default="")
    record.add_argument("--path", dest="paths", action="append", default=[])

    list_parser = verbs.add_parser("list", help="List experience lessons.")
    list_parser.add_argument("--state", choices=_STATES)
    list_parser.add_argument("--tier", choices=_TIERS)
    list_parser.add_argument("--json", action="store_true", dest="as_json")

    show = verbs.add_parser("show", help="Show one experience lesson.")
    show.add_argument("lesson_id")
    show.add_argument("--json", action="store_true", dest="as_json")

    retire = verbs.add_parser("retire", help="Retire one experience lesson.")
    retire.add_argument("lesson_id")
    retire.add_argument("--reason", required=True)

    verbs.add_parser("sync", help="Sync global experience events.")
    verbs.add_parser("export", help="Export shared lesson definitions.")
    verbs.add_parser("rebuild", help="Rebuild experience indexes.")
    return parser


def _task_context(path: Path) -> tuple[str, list[str]]:
    """Extract a task title and declared file paths from bounded Markdown."""
    with path.open("rb") as handle:
        payload = handle.read(_MAX_TASK_FILE_BYTES + 1)
    if len(payload) > _MAX_TASK_FILE_BYTES:
        raise ValueError(f"task file exceeds {_MAX_TASK_FILE_BYTES} bytes")
    text = payload.decode("utf-8")

    title = ""
    files: list[str] = []
    in_files = False
    for line in text.splitlines():
        if not title and line.startswith("# "):
            title = line[2:].strip()
            if ":" in title:
                title = title.split(":", 1)[1].strip()
        if line == "## Files to Create / Modify":
            in_files = True
            continue
        if in_files and line.startswith("## "):
            break
        if not in_files or "`" not in line:
            continue
        parts = line.split("`")
        if len(parts) >= 3 and parts[1] and parts[1] not in files:
            files.append(parts[1])
    return title, files


def _write(value: str) -> None:
    """Write one non-empty CLI result with a trailing newline."""
    if value:
        sys.stdout.write(value)
        if not value.endswith("\n"):
            sys.stdout.write("\n")


def _lesson_text(lesson: Lesson) -> str:
    """Render one lesson as a compact deterministic text row."""
    trigger = lesson.draft.trigger
    command = " ".join(part for part in (trigger.executable, trigger.subcommand) if part)
    return "\t".join((lesson.lesson_id, lesson.state, lesson.tier, command, lesson.draft.solution))


def _available(service: ExperienceService) -> bool:
    """Return whether an existing enabled plane can serve a normal verb."""
    try:
        return bool(service.config.enabled and service.plane_dir is not None and service.plane_dir.is_dir())
    except OSError:
        return False


def _initialize(service: ExperienceService) -> bool:
    """Create a non-symlink plane and register its read-only namespace."""
    if not service.config.enabled or service.root is None or service.plane_dir is None:
        return False
    try:
        parent = service.plane_dir.parent
        if (parent.exists() and (parent.is_symlink() or not parent.is_dir())) or service.plane_dir.is_symlink():
            return False
        parent.mkdir(parents=True, exist_ok=True)
        service.plane_dir.mkdir(exist_ok=True)
        if service.plane_dir.is_symlink() or not service.plane_dir.is_dir():
            return False
    except OSError:
        return False
    register_namespace(service.root)
    return True


async def _dispatch(args: argparse.Namespace) -> int:
    """Run one parsed lifecycle command."""
    service = ExperienceService.from_root()

    if args.verb == "init":
        if _initialize(service):
            await service.refresh()
        return 0
    if not _available(service):
        return 0

    if args.verb == "brief":
        title, files = _task_context(args.task_file)
        await service.refresh()
        _write(await service.brief(title, files, max_entries=args.max_entries))
    elif args.verb == "record":
        draft = LessonDraft(
            trigger=LessonTrigger(
                executable=args.executable,
                subcommand=args.subcommand,
                error_signature=args.error,
                error_excerpt=args.error,
                command_example=" ".join(part for part in (args.executable, args.subcommand) if part),
            ),
            symptom=args.symptom,
            solution=args.solution,
            scope_paths=args.paths,
        )
        _write(await service.record(draft, session="experience-cli", source="authored", seat="cli"))
    elif args.verb == "list":
        await service.refresh()
        lessons = await service.list_lessons(state=args.state, tier=args.tier)
        if args.as_json:
            _write(json.dumps([lesson.model_dump(mode="json") for lesson in lessons], ensure_ascii=False))
        else:
            _write("\n".join(_lesson_text(lesson) for lesson in lessons))
    elif args.verb == "show":
        await service.refresh()
        lesson = await service.get_lesson(args.lesson_id)
        if lesson is not None:
            output = (
                json.dumps(lesson.model_dump(mode="json"), ensure_ascii=False) if args.as_json else _lesson_text(lesson)
            )
            _write(output)
    elif args.verb == "retire":
        await service.refresh()
        await service.retire(args.lesson_id, reason=args.reason)
    elif args.verb == "sync":
        if service.plane_dir is not None:
            _write(str(sync_global(service.plane_dir)))
    elif args.verb == "export":
        if service.root is not None and service.plane_dir is not None:
            await service.refresh()
            ledger = LedgerService.from_root(service.root)
            await graduate(service, ledger, ledger_name=service.root.name)
            exported = export_shared(service.plane_dir, Path.cwd())
            if exported is not None:
                _write(str(exported))
    elif args.verb == "rebuild" and service.index is not None:
        _write(str(await service.index.rebuild()))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch lifecycle verbs; 0 on success/absent plane, 2 on invalid usage."""
    try:
        args = _parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        return asyncio.run(_dispatch(args))
    except (OSError, UnicodeError, ValueError):
        logger.error("experience CLI operation failed", exc_info=True)
        return 1
    except Exception:
        logger.exception("unexpected experience CLI failure")
        return 1


if __name__ == "__main__":
    sys.exit(main())
