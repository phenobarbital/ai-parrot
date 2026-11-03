"""Dispatch /sdd-done closeout hooks (FEAT-764). Exit: 0 ok · 1 blocking failure · 2 config/usage · 3 agents pending."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from parrot.sdd.scripts.closeout_builtins import run_builtin
from parrot.sdd.scripts.closeout_hooks_config import (
    _FEAT_ID_RE,
    EVENTS,
    Defaulting,
    HookContext,
    HookKind,
    HookResult,
    HookSpec,
    HooksConfig,
    HooksConfigError,
    load_hooks,
)

EXIT_OK, EXIT_BLOCKING, EXIT_USAGE, EXIT_PENDING = 0, 1, 2, 3


class EventOutcome(BaseModel):
    """Persisted result of one event run."""

    event: str
    feat_id: str
    results: list[HookResult] = Field(default_factory=list)
    pending_agents: list[dict[str, Any]] = Field(default_factory=list)
    blocking_failed: bool = False
    evidence_md: str = ""


def _validate_feat_id(feat_id: str) -> None:
    """Reject feat_id values that could escape the artifact root."""
    if not _FEAT_ID_RE.fullmatch(feat_id):
        raise ValueError(f"invalid feat_id: {feat_id!r}")


def artifact_root() -> Path:
    """Return $SDD_HOOKS_ARTIFACT_ROOT or /tmp/claude-<uid>/sdd-hooks."""
    env = os.environ.get("SDD_HOOKS_ARTIFACT_ROOT")
    return Path(env) if env else Path(f"/tmp/claude-{os.getuid()}") / "sdd-hooks"


def _outcome_path(feat_id: str, event: str) -> Path:
    """Return the durable outcome path for one feature event."""
    _validate_feat_id(feat_id)
    return artifact_root() / feat_id / f"{event}.json"


def _tail(text: str) -> str:
    """Return the last forty output lines, retaining a trailing newline when present."""
    lines = text.splitlines()
    return "\n".join(lines[-40:]) + ("\n" if lines else "")


def _write_output_log(hook_dir: Path, output: str) -> str:
    """Write the bounded combined command output and return its captured tail."""
    tail = _tail(output)
    (hook_dir / "output.log").write_text(tail, encoding="utf-8")
    return tail


def _glob_artifacts(hook_dir: Path, pattern: str | None) -> list[str]:
    """Return absolute file artifacts matching a hook's configured pattern."""
    if not pattern or ".." in pattern or os.path.isabs(pattern):
        return []
    return sorted(str(path.resolve()) for path in hook_dir.glob(pattern) if path.is_file())


def _persist(outcome: EventOutcome) -> None:
    """Refresh evidence and atomically write one outcome JSON document."""
    outcome.evidence_md = render_evidence(outcome)
    path = _outcome_path(outcome.feat_id, outcome.event)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    closed = False
    try:
        os.write(fd, (outcome.model_dump_json(indent=2) + "\n").encode("utf-8"))
        os.close(fd)
        closed = True
        os.replace(tmp, path)
    except BaseException:
        if not closed:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_outcome(event: str, feat_id: str) -> EventOutcome:
    """Read a previously persisted event outcome."""
    return EventOutcome.model_validate_json(_outcome_path(feat_id, event).read_text(encoding="utf-8"))


def _recompute_blocking_failed(outcome: EventOutcome) -> None:
    """Update the blocking-failure summary from individual results."""
    outcome.blocking_failed = any(
        result.blocking and result.status in {"fail", "timeout"} for result in outcome.results
    )


def _run_command(hook: HookSpec, ctx: HookContext, ctx_path: Path, hook_dir: Path) -> HookResult:
    """Run one command hook and save its last forty output lines."""
    started = time.monotonic()
    environment = os.environ.copy()
    environment.update(
        {
            "SDD_HOOK_CONTEXT": str(ctx_path.resolve()),
            "SDD_HOOK_ARTIFACT_DIR": str(hook_dir.resolve()),
            "SDD_FEAT_ID": ctx.feat_id,
            "SDD_PR_URL": ctx.pr_url or "",
        }
    )
    try:
        completed = subprocess.run(
            hook.run,
            shell=True,
            cwd=ctx.worktree,
            timeout=hook.timeout_s,
            env=environment,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        output = f"{completed.stdout}{completed.stderr}"
        tail = _write_output_log(hook_dir, output)
        status = "pass" if completed.returncode == 0 else "fail"
        summary = tail.strip() or f"Command exited with {completed.returncode}"
        return HookResult(
            name=hook.name,
            kind=HookKind.COMMAND,
            status=status,
            blocking=hook.blocking,
            duration_s=round(time.monotonic() - started, 3),
            summary=summary,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        tail = _write_output_log(hook_dir, f"{stdout}{stderr}")
        summary = tail.strip() or f"Command timed out after {hook.timeout_s}s"
        return HookResult(
            name=hook.name,
            kind=HookKind.COMMAND,
            status="timeout",
            blocking=hook.blocking,
            duration_s=round(time.monotonic() - started, 3),
            summary=summary,
        )


def run_event(event: str, ctx: HookContext, cfg: HooksConfig, ctx_path: Path) -> EventOutcome:
    """Run every enabled hook for ``event`` in declaration order.

    Short-circuits after a blocking ``pre_pr`` failure: remaining hooks are
    skipped once a blocker fails or times out.
    """
    outcome = EventOutcome(event=event, feat_id=ctx.feat_id)
    short_circuit = False
    for hook in cfg.for_event(event):
        hook_dir = artifact_root() / ctx.feat_id / hook.name
        hook_dir.mkdir(parents=True, exist_ok=True)
        if short_circuit:
            result = HookResult(
                name=hook.name,
                kind=hook.kind,
                status="skipped",
                blocking=hook.blocking,
                summary="skipped after blocking failure",
            )
        elif ctx.dry_run and event in {"post_pr", "on_failure"}:
            result = HookResult(
                name=hook.name,
                kind=hook.kind,
                status="skipped",
                blocking=hook.blocking,
                summary="dry-run",
            )
        elif hook.kind is HookKind.COMMAND:
            result = _run_command(hook, ctx, ctx_path, hook_dir)
        elif hook.kind is HookKind.BUILTIN:
            result = run_builtin(hook, ctx, hook_dir)
        else:
            prompt_data = Defaulting(ctx.model_dump())
            prompt_data["artifact_dir"] = str(hook_dir.resolve())
            try:
                prompt = (hook.prompt or "").format_map(prompt_data)
            except (KeyError, IndexError, ValueError) as exc:
                result = HookResult(
                    name=hook.name,
                    kind=HookKind.AGENT,
                    status="fail",
                    blocking=hook.blocking,
                    summary=f"invalid prompt template: {type(exc).__name__}: {exc}",
                )
            else:
                result = HookResult(
                    name=hook.name,
                    kind=HookKind.AGENT,
                    status="pending",
                    blocking=hook.blocking,
                    summary="Agent hook pending",
                )
                outcome.pending_agents.append(
                    {
                        "name": hook.name,
                        "agent": hook.agent,
                        "prompt": prompt,
                        "artifact_dir": str(hook_dir.resolve()),
                        "blocking": hook.blocking,
                    }
                )
        result.artifacts = _glob_artifacts(hook_dir, hook.artifacts)
        outcome.results.append(result)
        if event == "pre_pr" and result.blocking and result.status in {"fail", "timeout"}:
            short_circuit = True
    _recompute_blocking_failed(outcome)
    _persist(outcome)
    return outcome


def record(event: str, feat_id: str, name: str, status: str, summary: str, root: Path) -> EventOutcome:
    """Record a host-dispatched agent hook's outcome."""
    outcome = _load_outcome(event, feat_id)
    result = next((item for item in outcome.results if item.name == name and item.status == "pending"), None)
    if result is None:
        raise ValueError(f"Hook {name!r} is not pending")
    hook = next((item for item in load_hooks(root).for_event(event) if item.name == name), None)
    if hook is None:
        raise ValueError(f"Hook {name!r} is not configured for {event}")
    result.status = status
    result.summary = summary
    hook_dir = artifact_root() / feat_id / name
    result.artifacts = _glob_artifacts(hook_dir, hook.artifacts)
    outcome.pending_agents = [item for item in outcome.pending_agents if item["name"] != name]
    _recompute_blocking_failed(outcome)
    _persist(outcome)
    return outcome


def finalize(event: str, feat_id: str, root: Path) -> EventOutcome:
    """Turn unrecorded pending hooks into failures and recompute blocking_failed (AC6)."""
    del root
    outcome = _load_outcome(event, feat_id)
    for result in outcome.results:
        if result.status == "pending":
            result.status = "fail"
            result.summary = "agent hook not recorded"
    outcome.pending_agents = []
    _recompute_blocking_failed(outcome)
    _persist(outcome)
    return outcome


def render_evidence(outcome: EventOutcome) -> str:
    """Render the PR `## Evidence` section (absolute artifact paths)."""
    if not outcome.results:
        return ""
    lines = ["## Evidence"]
    for result in outcome.results:
        lines.append(f"- {result.name} — {result.status} — {result.summary}")
        lines.extend(f"  - {artifact}" for artifact in result.artifacts)
    return "\n".join(lines)


def exit_code(outcome: EventOutcome) -> int:
    """Map an outcome to the CLI contract."""
    if outcome.pending_agents and any(result.status == "pending" for result in outcome.results):
        return EXIT_PENDING
    if outcome.event == "pre_pr" and outcome.blocking_failed:
        return EXIT_BLOCKING
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(prog="run_closeout_hooks", description=__doc__)
    parser.add_argument("--event", required=True, choices=EVENTS)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--feat-id")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--record", metavar="NAME")
    parser.add_argument("--status", choices=("pass", "fail"))
    parser.add_argument("--summary", default="")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args(argv)

    if args.record and args.finalize:
        parser.error("--record and --finalize cannot be used together")
    if (args.record or args.finalize) and not args.feat_id:
        parser.error("--feat-id is required with --record or --finalize")
    if args.record and not args.status:
        parser.error("--status is required with --record")
    if not (args.record or args.finalize) and args.context is None:
        parser.error("--context is required unless --record or --finalize is used")

    try:
        if args.record:
            outcome = record(args.event, args.feat_id, args.record, args.status, args.summary, args.root)
        elif args.finalize:
            outcome = finalize(args.event, args.feat_id, args.root)
        else:
            context = HookContext.model_validate_json(args.context.read_text(encoding="utf-8"))
            if args.dry_run:
                context = context.model_copy(update={"dry_run": True})
            outcome = run_event(args.event, context, load_hooks(args.root), args.context)
    except (HooksConfigError, OSError, ValidationError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    print(outcome.model_dump_json())
    return exit_code(outcome)


if __name__ == "__main__":
    raise SystemExit(main())
