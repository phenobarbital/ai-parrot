"""Lazy, feature-scoped E2E gate invocation for the dev-loop QA node."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any

import yaml

_E2E_TIMEOUT_SECONDS = 660
_OUTPUT_TAIL_BYTES = 16_000


async def run_e2e_stage(*, worktree: Path, spec_path: Path, feature_id: str) -> dict[str, Any]:
    """Run the feature E2E plan without importing the optional server package.

    Args:
        worktree: Root of the worktree whose feature evidence is being checked.
        spec_path: Feature specification declaring the E2E policy.
        feature_id: Feature identifier used to locate its generated plan.

    Returns:
        A JSON-safe summary suitable for shared QA state and report notes.
    """
    policy = _read_policy(worktree, spec_path)
    plan_path = worktree / "sdd" / "state" / feature_id / "e2e-plan.md"
    if policy == "invalid":
        return {
            "policy": "invalid",
            "plan_path": str(plan_path.relative_to(worktree)),
            "required": True,
            "status": "BLOCKED",
            "gate_satisfied": False,
            "reason": "Feature E2E policy metadata is invalid.",
        }
    base = {
        "policy": policy,
        "plan_path": str(plan_path.relative_to(worktree)),
        "required": policy == "required",
    }
    if policy == "none":
        return {**base, "status": "SKIPPED", "gate_satisfied": True, "reason": "E2E policy is none."}
    if not plan_path.is_file():
        if policy == "required":
            return {**base, "status": "BLOCKED", "gate_satisfied": False, "reason": "Required E2E plan is missing."}
        return {**base, "status": "SKIPPED", "gate_satisfied": True, "reason": "Optional E2E plan is missing."}

    argv = ("parrot", "e2e", "run", "--plan", str(plan_path.relative_to(worktree)))
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(worktree),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return _missing_cli_result(base, argv)

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=_E2E_TIMEOUT_SECONDS)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        with contextlib.suppress(ProcessLookupError):
            await process.wait()
        return {
            **base,
            "status": "BLOCKED",
            "gate_satisfied": False,
            "argv": list(argv),
            "reason": f"E2E CLI exceeded {_E2E_TIMEOUT_SECONDS} seconds.",
        }

    stdout_text = stdout.decode("utf-8", errors="replace")[-_OUTPUT_TAIL_BYTES:]
    stderr_text = stderr.decode("utf-8", errors="replace")[-_OUTPUT_TAIL_BYTES:]
    payload = _parse_verdict(stdout_text)
    if payload is None:
        return {
            **base,
            "status": "BLOCKED",
            "gate_satisfied": False,
            "argv": list(argv),
            "exit_code": process.returncode,
            "stderr_tail": stderr_text,
            "reason": "E2E CLI did not emit a JSON verdict.",
        }

    status = str(payload.get("status", "BLOCKED"))
    gate_satisfied = payload.get("gate_satisfied") is True
    return {
        **base,
        "status": status,
        "gate_satisfied": gate_satisfied,
        "argv": list(argv),
        "exit_code": process.returncode,
        "stderr_tail": stderr_text,
        "verdict": payload,
    }


def _read_policy(worktree: Path, spec_path: Path) -> str:
    """Read a feature's E2E policy, defaulting absent legacy metadata to optional."""
    candidate = spec_path if spec_path.is_absolute() else worktree / spec_path
    try:
        document = candidate.read_text(encoding="utf-8")
    except OSError:
        return "optional"
    if not document.startswith("---\n"):
        return "optional"
    try:
        frontmatter = document.split("---", 2)[1]
        metadata = yaml.safe_load(frontmatter) or {}
    except (IndexError, yaml.YAMLError):
        return "invalid"
    if not isinstance(metadata, dict):
        return "invalid"
    if "e2e" not in metadata:
        return "optional"
    e2e = metadata["e2e"]
    if not isinstance(e2e, dict):
        return "invalid"
    policy = e2e.get("policy", "optional")
    return policy if policy in {"required", "optional", "none"} else "invalid"


def _missing_cli_result(base: dict[str, Any], argv: tuple[str, ...]) -> dict[str, Any]:
    """Return the policy-correct result when the optional server CLI is absent."""
    if base["required"]:
        return {
            **base,
            "status": "BLOCKED",
            "gate_satisfied": False,
            "argv": list(argv),
            "reason": "Required E2E CLI is unavailable; install ai-parrot-server.",
        }
    return {
        **base,
        "status": "BLOCKED",
        "gate_satisfied": False,
        "argv": list(argv),
        "reason": "Optional E2E CLI is unavailable; install ai-parrot-server.",
    }


def _parse_verdict(stdout: str) -> dict[str, Any] | None:
    """Return the CLI verdict object, rejecting non-object or malformed output."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
