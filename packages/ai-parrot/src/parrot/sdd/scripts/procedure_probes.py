"""Probe registry and scope resolution for the procedure graph (FEAT-891). No main()."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.procedure.models import ProbeCheck, ProbeCost
from parrot.sdd.config import SddConfigError, load_sdd_config
from parrot.sdd.scripts.procedure_advice import (
    LOCAL_PROBES,
    apply_check,
    checkout_root,
    current_branch,
    feature_index,
)

REMOTE_PROBES = ("branch.pushed", "pr.open")
PROBE_COSTS: dict[str, ProbeCost] = {
    **dict.fromkeys(LOCAL_PROBES, "local"),
    **dict.fromkeys(REMOTE_PROBES, "remote"),
}
_FEATURE_BRANCH = re.compile(r"^feat-(FEAT-\d+)-(.+)$")
_LOGGER = logging.getLogger(__name__)


class SddProbeRunner:
    """ProbeRunner over a checkout using the shared local and remote probes."""

    def __init__(self, checkout: Path, *, timeout: int = 5) -> None:
        """Initialize the runner for the checkout containing ``checkout``.

        Args:
            checkout: Repository checkout root or a path inside it.
            timeout: Maximum seconds allowed for each remote subprocess.
        """
        requested = Path(checkout)
        self.checkout = checkout_root(requested) or requested
        self.timeout = timeout
        self._probes: dict[str, Any] = {
            **LOCAL_PROBES,
            "branch.pushed": self._branch_pushed,
            "pr.open": self._pr_open,
        }
        self._hotfix_base: str | None = None

    def cost(self, probe: str) -> ProbeCost | None:
        """Return the cost class of a registered probe, or None."""
        return PROBE_COSTS.get(probe)

    def run(self, check: ProbeCheck, scope: Mapping[str, str]) -> bool | None:
        """Apply one check with the shared procedure-advice semantics."""
        if self._hotfix_base is None:
            try:
                self._hotfix_base = load_sdd_config(self.checkout).hotfix_base
            except SddConfigError:
                self._hotfix_base = "main"
        raw_check = {
            "probe": check.probe,
            "expect": check.expect,
            "args": {**check.args, "hotfix_base": self._hotfix_base},
        }
        return apply_check(raw_check, self.checkout, scope, probes=self._probes)

    def _branch_pushed(
        self,
        checkout: Path,
        scope: Mapping[str, str],
        args: Mapping[str, str],
    ) -> bool | None:
        """Return whether HEAD is not ahead of its configured upstream."""
        del scope, args
        try:
            completed = subprocess.run(
                ["git", "-C", str(checkout), "rev-list", "--count", "@{u}..HEAD"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (OSError, subprocess.SubprocessError):
            _LOGGER.debug("branch.pushed probe failed", exc_info=True)
            return None
        if completed.returncode != 0:
            return False
        if not isinstance(completed.stdout, str):
            return None
        output = completed.stdout.strip()
        if not output.isdecimal():
            return None
        return int(output) == 0

    def _pr_open(
        self,
        checkout: Path,
        scope: Mapping[str, str],
        args: Mapping[str, str],
    ) -> bool | None:
        """Return whether GitHub reports an open pull request for the branch."""
        del checkout, args
        branch = scope.get("branch")
        if not branch:
            return None
        try:
            completed = subprocess.run(
                ["gh", "pr", "list", "--head", branch, "--json", "number", "--limit", "1"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if completed.returncode != 0:
                return None
            payload = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, TypeError, ValueError):
            _LOGGER.debug("pr.open probe failed", exc_info=True)
            return None
        if not isinstance(payload, list):
            return None
        return bool(payload)


def scope_for(checkout: Path, *, feature: str | None = None, task: str | None = None) -> dict[str, str]:
    """Resolve feature, task, and branch scope from explicit values and checkout state.

    Args:
        checkout: Repository checkout root or a path inside it.
        feature: Explicit feature slug or ``FEAT-N`` identifier.
        task: Explicit ``TASK-N`` identifier.

    Returns:
        Known scope values, omitting keys that could not be resolved.
    """
    requested = Path(checkout)
    root = checkout_root(requested) or requested
    branch = current_branch(root)
    resolved_feature: str | None = None

    if feature:
        index = feature_index(root, {"feature": feature})
        index_feature = index.get("feature") if index is not None else None
        resolved_feature = index_feature if isinstance(index_feature, str) and index_feature else feature
    else:
        match = _FEATURE_BRANCH.fullmatch(branch or "")
        if match is not None:
            feature_id, branch_slug = match.groups()
            index = feature_index(root, {"feature": feature_id})
            index_feature = index.get("feature") if index is not None else None
            resolved_feature = index_feature if isinstance(index_feature, str) and index_feature else branch_slug
        elif task:
            index = feature_index(root, {"task": task})
            index_feature = index.get("feature") if index is not None else None
            if isinstance(index_feature, str) and index_feature:
                resolved_feature = index_feature

    scope: dict[str, str] = {}
    if resolved_feature:
        scope["feature"] = resolved_feature
    if task:
        scope["task"] = task
    if branch:
        scope["branch"] = branch
    return scope
