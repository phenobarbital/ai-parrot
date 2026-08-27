"""DevLoopNode — shared base for the dev-loop flow nodes.

Adapts the dev-loop nodes to the FEAT-163 ``AgentsFlow`` scheduler
contract:

- carries the ``dependencies`` / ``successors`` / ``fsm`` fields the
  event-driven scheduler expects (the FSM is auto-created per node and
  re-created per run by ``AgentsFlow._materialize_nodes``);
- normalizes the execute signature to ``execute(ctx, deps, **kwargs)``
  where ``ctx`` is a :class:`FlowContext`. For unit-test ergonomics a
  plain dict is also accepted and treated as the shared state itself.

Cross-node payloads (``bug_brief``, ``research_output``,
``development_output``, ``qa_report``, ``run_id``, …) travel in
``FlowContext.shared_data``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from pydantic import Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node
from parrot.flows.dev_loop.models import QAReport

# Matches the userinfo (``user:secret@``) of an https remote URL, e.g. the
# ``x-access-token:<token>@github.com`` form GitToolkit injects for private
# clones — so a token can never surface in git CLI error output (R2).
_GIT_URL_USERINFO_RE = re.compile(r"(https://)[^@/\s]+:[^@/\s]+@")

# FEAT-466 TASK-2505: the Git Parrot Flow's long-lived branches. Deliberately
# a LOCAL copy of scripts.sdd.sdd_meta.KNOWN_BRANCHES — NOT an import.
# `scripts.sdd` is not importable from this package's actual install/test
# context (verified in TASK-2504's Completion Note: it fails once the
# interpreter's cwd is anything other than the repo root).
_LONG_LIVED_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})


def scrub_git_output(text: str) -> str:
    """Redact credentials from raw git CLI output before surfacing it.

    Scrubs the userinfo of any https remote URL and, defensively, the value of
    ``GITHUB_TOKEN`` if it appears verbatim. Used by the push paths so a
    ``git push`` failure message never leaks a token.
    """
    redacted = _GIT_URL_USERINFO_RE.sub(r"\1***@", text)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        redacted = redacted.replace(token, "***")
    return redacted


class BaseBranchMismatch(RuntimeError):
    """The head branch was cut from the wrong base (FEAT-466)."""


async def _git(cwd: str, *args: str) -> Tuple[int, str, str]:
    """Run a git subcommand, returning ``(returncode, stdout, stderr)``.

    Mirrors the subprocess idiom used by ``DeploymentHandoffNode._push_branch``
    — ``asyncio.create_subprocess_exec``, never a blocking call.

    Forces ``LC_ALL=C`` (and ``LANG=C``) so git's error messages are always
    emitted in English — ``assert_base_is_clean`` pattern-matches stderr
    (e.g. ``"couldn't find remote ref"``) to distinguish a genuinely-absent
    ref from a real fetch failure, and that match must not depend on the
    host's locale (FEAT-466 TASK-2505 code-review follow-up).
    """
    env = dict(os.environ, LC_ALL="C", LANG="C")
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        cwd,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    out, err = await proc.communicate()
    return (
        proc.returncode,
        out.decode(errors="replace").strip(),
        err.decode(errors="replace").strip(),
    )


def _cwd_is_unusable_repo(err: str) -> bool:
    """Detect the two git error shapes meaning "cwd is not a usable repo".

    Both are structural preconditions about ``cwd`` itself, not about a
    fetch/network/ref problem:

    * ``cannot change to '<path>': No such file or directory`` — ``cwd``
      does not exist at all.
    * ``not a git repository (or any of the parent directories): .git`` —
      ``cwd`` exists but was never ``git init``'d.

    Both messages are forced to English by ``_git``'s ``LC_ALL=C`` so this
    match is locale-independent.
    """
    lowered = err.lower()
    return "not a git repository" in lowered or "cannot change to" in lowered


async def assert_base_is_clean(
    branch: str,
    base: str,
    cwd: str,
    *,
    siblings: Optional[Iterable[str]] = None,
    logger: Any = None,
) -> None:
    """Raise when ``branch`` carries commits belonging to a sibling branch.

    FEAT-466: the backstop for any path that still drifts. An ancestry check
    is deliberately NOT the test. Measured on the FEAT-466 incident (PR
    #1250): ``git merge-base --is-ancestor <old main> <feat-465 tip>``
    returns true, because ``main`` was an ancestor of ``dev`` — so a branch
    cut from ``dev`` still descends from ``origin/main``. The discriminating
    signal is commit *membership*:

        adds = git rev-list --count origin/<base>..<branch>
        own  = git rev-list --count <branch> ^origin/<base> ^origin/<sib>...
        adds != own  =>  the branch carries a sibling's history.

    NOTE on the ``own`` form: this uses explicit ``^origin/<ref>`` exclusion
    prefixes, NOT ``origin/<base>..<branch> --not origin/<sib1> --not
    origin/<sib2> ...``. Empirically verified (real git repos, FEAT-466
    TASK-2505) that chaining multiple ``--not`` flags after a ``..`` range
    shorthand gives WRONG counts — each ``--not`` toggles the
    interesting/uninteresting state for what follows rather than
    accumulating exclusions, so two or more sibling refs chained this way
    can silently over- or under-count. The ``^``-prefixed form does not
    have this failure mode and was confirmed correct across the same
    scenarios (clean branch, incident topology, cherry-pick, 2+ siblings).

    Cherry-picked commits have distinct SHAs and therefore do not count as
    sibling commits, so a legitimately back-ported hotfix is not flagged.

    Args:
        branch: Local head branch name.
        base: Resolved base branch (no ``origin/`` prefix).
        cwd: Repository or worktree directory to run git in.
        siblings: Long-lived branches to treat as foreign. Defaults to
            ``_LONG_LIVED_BRANCHES`` minus ``base``, filtered to refs that
            exist on the remote.
        logger: Optional logger for the INFO/measurement trail.

    Raises:
        BaseBranchMismatch: When the branch carries sibling commits.
        RuntimeError: When a git command fails outright for a reason other
            than ``cwd`` not being a git repository at all (see below) —
            including a failure to fetch ``base``, or a sibling fetch that
            fails for a reason OTHER than the ref genuinely not existing on
            the remote (FEAT-466 TASK-2505 code-review follow-up: a
            transient fetch failure must never be silently treated the
            same as "this sibling doesn't exist" — that would let exactly
            the sibling that matters go unchecked).

    Note (code-review follow-up): ``cwd`` not being a git repository at all
    is treated as "cannot check, skip" (logged at INFO), not a hard
    failure — deliberately, not an oversight. In production this call
    always runs AFTER a successful push to ``cwd`` (both call sites push
    first), so a real run never reaches this function with an invalid
    ``cwd`` — the push itself would already have failed loudly. This shape
    is therefore purely a test-fixture artifact (many existing tests pass
    a throwaway ``tmp_path`` with no real git history for unrelated
    reasons — Jira wiring, docs artifacts, etc.), not a live failure mode
    worth hard-failing on.
    """
    candidates = [s for s in (siblings if siblings is not None else _LONG_LIVED_BRANCHES) if s != base]

    # Fetch base FIRST. Two distinct failure shapes:
    #  - `cwd` is not a usable git repository at all (missing entirely, or
    #    present but not initialized as one) — see the Note above; skip.
    #  - any OTHER fetch failure (network, auth, missing base ref on the
    #    remote, ...) is a real problem the guard must not silently
    #    swallow — raise loudly rather than fail open.
    rc, _, err = await _git(cwd, "fetch", "origin", base)
    if rc != 0:
        if _cwd_is_unusable_repo(err):
            if logger:
                logger.info(
                    "%r is not a usable git repository; skipping " "base-branch guard.",
                    cwd,
                )
            return
        raise RuntimeError(
            f"assert_base_is_clean: could not fetch origin/{base} — " f"refusing to guess: {scrub_git_output(err)}"
        )

    # Fetch candidates, and keep only refs that actually exist — `staging`
    # may not exist on the remote, and passing a missing ref as an
    # exclusion bound fails the entire command. A sibling ref that is
    # genuinely absent fails with git's own "couldn't find remote ref"
    # message (forced to English by `_git`'s LC_ALL=C) — ONLY that shape is
    # treated as "not applicable, skip it". Any other fetch failure
    # (network, auth, ...) is a real error and must not be silently
    # downgraded to "ref absent".
    existing: List[str] = []
    for sib in sorted(candidates):
        rc, _, err = await _git(cwd, "fetch", "origin", sib)
        if rc != 0:
            if "couldn't find remote ref" in err.lower():
                continue
            raise RuntimeError(
                f"assert_base_is_clean: could not fetch origin/{sib} — " f"refusing to guess: {scrub_git_output(err)}"
            )
        rc, _, _ = await _git(cwd, "rev-parse", "--verify", f"origin/{sib}")
        if rc == 0:
            existing.append(sib)

    if not existing:
        if logger:
            logger.info(
                "No sibling branches to check against base %r; guard passes.",
                base,
            )
        return

    rng = f"origin/{base}..{branch}"
    rc, adds_out, err = await _git(cwd, "rev-list", "--count", rng)
    if rc != 0:
        raise RuntimeError(f"git rev-list failed: {scrub_git_output(err)}")

    # Explicit ^-prefixed exclusions — NOT `rng --not origin/<sib1> --not
    # origin/<sib2>`. See the docstring NOTE: chained --not flags proved
    # order-sensitive and gave wrong counts with 2+ siblings.
    exclude_args = [f"^origin/{base}"] + [f"^origin/{sib}" for sib in existing]
    rc, own_out, err = await _git(cwd, "rev-list", "--count", branch, *exclude_args)
    if rc != 0:
        raise RuntimeError(f"git rev-list failed: {scrub_git_output(err)}")

    adds, own = int(adds_out or 0), int(own_out or 0)
    if logger:
        logger.info(
            "Base check for %s onto %s: adds=%d own=%d siblings=%s",
            branch,
            base,
            adds,
            own,
            existing,
        )
    if adds != own:
        raise BaseBranchMismatch(
            f"branch {branch!r} would add {adds} commit(s) to {base!r} but "
            f"only {own} are its own work — the remaining {adds - own} "
            f"already exist on {existing}. The branch was almost certainly "
            f"cut from the wrong base. Re-cut it from origin/{base} and "
            "re-run."
        )


async def transition_issue_with_candidates(
    jira: Any,
    issue: str,
    candidates: Sequence[str],
    *,
    logger: logging.Logger,
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """Apply the first candidate Jira transition that the workflow exposes.

    The dev-loop drives many Jira projects, each with its own workflow
    transition names — a single hard-coded label (e.g. ``"Ready to Deploy"``)
    only exists in one of them. Callers therefore pass an *ordered* list of
    synonym labels (most specific first). Each is handed to
    ``jira_transition_to``, which walks the project's declared workflow path
    (``JIRA_WORKFLOW_PATH`` / ``JIRA_WORKFLOW_PATH_<PROJECT>``) hop-by-hop when
    the target status is several transitions away, and otherwise falls back to
    a single direct transition. The first label that resolves is applied and
    its result returned.

    A non-matching label raises ``ValueError`` inside the toolkit (it lists the
    available transitions) — that is treated as "try the next candidate", not a
    failure. Any other exception (network/auth) propagates so the caller's own
    error handling sees it. Returns ``None`` when no candidate matched, leaving
    the decision of whether that is fatal to the caller.

    Args:
        jira: A ``JiraToolkit`` instance.
        issue: Issue key (e.g. ``"NAV-6239"``).
        candidates: Ordered transition-label synonyms; empties are skipped.
        logger: Logger for diagnostics.
        **kwargs: Forwarded to ``jira_transition_issue`` (``fields``,
            ``resolution``, ``assignee`` …).

    Returns:
        The toolkit's ``jira_transition_issue`` result on success, else
        ``None``.
    """
    preferred = next((c for c in candidates if c), None)
    last_error: Optional[ValueError] = None
    tried: list[str] = []
    for label in candidates:
        if not label:
            continue
        tried.append(label)
        try:
            transition_to = getattr(jira, "jira_transition_to", None)
            if transition_to is not None:
                result = await transition_to(issue=issue, target_status=label, **kwargs)
            else:  # pragma: no cover - older toolkit without the walker
                result = await jira.jira_transition_issue(issue=issue, transition=label, **kwargs)
            if label != preferred:
                logger.info(
                    "Applied fallback transition %r for %s (preferred %r unavailable).",
                    label,
                    issue,
                    preferred,
                )
            return result
        except ValueError as exc:
            last_error = exc
            logger.debug(
                "Transition candidate %r not available for %s: %s",
                label,
                issue,
                exc,
            )
    logger.warning(
        "No candidate transition resolved for %s (tried %s). Last error: %s",
        issue,
        tried,
        last_error,
    )
    return None


def condense_qa_failure(report: QAReport, *, max_chars: int = 2000) -> str:
    """Condense a failed :class:`QAReport` into a compact feedback summary.

    FEAT-377 TASK-1911 (Module 3 repair loop): shared by ``QANode`` (the
    ``QaAttemptRecorded.qa_notes`` persisted to session state) and
    ``DevelopmentNode`` (the redispatch brief's feedback) so both surfaces
    describe the same failure the same way. Per the spec: no new field is
    added to ``QAReport`` — the summary is composed from
    ``criterion_results`` + ``lint_output`` + ``notes`` +
    ``code_review_findings``, all budget-capped so this never balloons an
    LLM prompt with full logs.

    Args:
        report: The failing QA report to summarize.
        max_chars: Hard cap on the returned string's length.

    Returns:
        A short, human-readable failure summary (never raises).
    """
    lines: List[str] = []
    for c in report.criterion_results:
        if c.passed:
            continue
        tail = (c.stderr_tail or c.stdout_tail or "").strip()
        tail = tail[-300:] if tail else ""
        line = f"- {c.name} (exit={c.exit_code})"
        if tail:
            line += f": {tail}"
        lines.append(line)
    if not report.lint_passed and report.lint_output:
        lines.append(f"- lint: {report.lint_output.strip()[-300:]}")
    if report.notes:
        lines.append(f"- notes: {report.notes.strip()[:300]}")
    if report.code_review_findings:
        findings = "; ".join(report.code_review_findings[:5])
        lines.append(f"- code review: {findings[:300]}")
    summary = "\n".join(lines) or "QA failed with no detailed criterion output."
    return summary[:max_chars]


def run_label(output: Any, *, default: str = "run") -> str:
    """Return the best available human label for a run.

    FEAT-466: a hotfix reserves no ``FEAT-<NNN>`` (a bugfix is not a
    feature), so ``feat_id`` is legitimately ``""`` on those runs and the
    Jira issue key carries the identity — the same underlying fallback
    ``nodes/qa.py:194,342`` relies on (``jira_issue_key or feat_id``,
    checked in that order there because ``jira_issue_key`` is a required,
    always-non-empty field on ``ResearchOutput``). This helper checks
    ``feat_id`` first instead, because it is also used for
    ``PlannerOutput`` (feature-mode), where a `FEAT-<NNN>` id is the
    stronger, more specific identity when both are present.

    Args:
        output: Any object exposing ``feat_id`` / ``jira_issue_key``
            (``ResearchOutput`` or ``PlannerOutput``).
        default: Returned when neither identifier is available, so callers
            never interpolate an empty string into user-facing text.

    Returns:
        ``feat_id`` when set, else ``jira_issue_key`` when set, else
        ``default``.
    """
    for attr in ("feat_id", "jira_issue_key"):
        value = (getattr(output, attr, "") or "").strip()
        if value:
            return value
    return default


def register_dev_loop_node(name: str):
    """Idempotent ``@register_node`` for the dev-loop node types (FEAT-250).

    The engine's :func:`register_node` deliberately raises on a duplicate
    registration. The dev-loop's lazy-import guarantee (spec §7 R1, exercised
    by ``test_lazy_import``) re-imports ``parrot.flows.dev_loop`` after purging
    it from ``sys.modules`` while the engine's ``NODE_REGISTRY`` persists — so a
    plain ``@register_node`` decorator would raise on the second import. This
    wrapper makes registration a no-op when ``name`` is already registered.
    """

    def _decorator(cls):
        if name in NODE_REGISTRY:
            return cls
        return register_node(name)(cls)

    return _decorator


class DevLoopNode(Node):
    """Base node for the dev-loop flow (FEAT-129 / FEAT-132).

    Subclasses implement ``execute(ctx, deps, **kwargs)`` and use
    :meth:`shared_state` to read/write cross-node payloads.

    Args:
        node_id: Unique identifier within the flow graph.
        dependencies: Upstream node_ids (optional — ``AgentsFlow`` derives
            them from the edge list in explicit-edge mode).
        successors: Downstream node_ids (optional, same reason).
        fsm: Per-run task FSM; auto-created when ``None``.
    """

    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create the FSM; initialise the base logger."""
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        """Node identifier used by the flow router."""
        return self.node_id

    # ── Context helpers ──────────────────────────────────────────────────

    @staticmethod
    def shared_state(ctx: Union[FlowContext, Dict[str, Any]]) -> Dict[str, Any]:
        """Return the mutable cross-node state dict for *ctx*.

        Args:
            ctx: The flow execution context. A :class:`FlowContext` yields
                its ``shared_data``; a plain dict (unit tests) is returned
                as-is.

        Returns:
            The shared mutable mapping.

        Raises:
            TypeError: When *ctx* is neither a FlowContext nor a dict.
        """
        if isinstance(ctx, FlowContext):
            return ctx.shared_data
        if isinstance(ctx, dict):
            return ctx
        raise TypeError(f"dev-loop nodes expect FlowContext or dict, got {type(ctx)!r}")

    @staticmethod
    def initial_prompt(ctx: Union[FlowContext, Dict[str, Any]]) -> str:
        """Return the run's initial task/prompt string.

        Args:
            ctx: The flow execution context.

        Returns:
            ``FlowContext.initial_task`` (or the dict's ``"initial_task"``
            key), empty string when absent.
        """
        if isinstance(ctx, FlowContext):
            return ctx.initial_task or ""
        if isinstance(ctx, dict):
            return str(ctx.get("initial_task") or "")
        return ""


__all__ = [
    "DevLoopNode",
    "condense_qa_failure",
    "register_dev_loop_node",
    "scrub_git_output",
    "transition_issue_with_candidates",
]
