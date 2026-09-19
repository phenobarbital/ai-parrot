"""Capture verifiable source/environment identity for E2E evidence (FEAT-581, M2).

``capture_identity()`` is the single entry point every caller (the M3 runner,
before and after execution; the M2 evidence verifier landing in TASK-3523) uses
to snapshot exactly what a run was validated against, per spec §2 "Evidence
Identity and Gate Evaluation":

    Before and after execution, hash a canonical sorted manifest of tracked
    files plus nonignored untracked files, including modes and relevant
    symlink targets. Exclude only declared generated artifacts
    (``artifacts/logs/e2e/``, this feature's run evidence/candidates, pytest
    caches, bytecode) and SDD task bookkeeping (``sdd/tasks/``,
    ``sdd/ledger/``). Do not exclude arbitrary source, templates, specs,
    plans or dependencies. Hash the plan/spec separately. Any relevant
    mutation invalidates the run. Environment fingerprint includes
    interpreter version/path, installed distribution versions, ``uv.lock``,
    selected model, target/tool versions, nonsecret fixture configuration
    and opt-in settings; exclude credential values.

This module lists tracked/untracked files via async Git subprocesses (never
``subprocess.run``/``Popen`` blocking the event loop) and hashes their
content with the standard library. It has no target/provider imports of its
own (target adapters land in M4) and never persists or logs a credential
value — only whether an opt-in secret is *configured*, never its content.

Manifest entries never carry raw file bytes, only ``path``, ``mode`` (a
git-style octal mode: ``100644`` regular, ``100755`` executable,
``120000`` symlink) and a ``content`` marker (a ``sha256:<hex>`` digest for
regular files, or ``symlink:<target>`` recording the *raw* ``readlink()``
target string — never the dereferenced target's content, since a dangling
or escaping symlink target must still be captured as identity data without
resolving it).

``TargetConfig.options`` is deliberately excluded from the environment
fingerprint: per-adapter option-key allow-listing is deferred to M4 (see
``parrot.e2e.plan`` module docstring), so this module cannot yet tell a
nonsecret fixture toggle from a credential-shaped value placed there ahead
of that validation. Only each target's ``kind``/``profile`` (fixed,
schema-validated enums) are folded into the fingerprint as a target/tool
identity signal.

``verify_evidence()`` (TASK-3523) is this module's read-only counterpart: it
validates a previously persisted :class:`~parrot.e2e.models.E2EVerdict`
against the plan's declared coverage, its own artifact hashes and a freshly
recomputed :class:`SourceIdentity`, per spec §2 "Evidence Identity and Gate
Evaluation" and "New Public Interfaces". It never executes pytest or a
target adapter itself -- those are the M3 runner's (``parrot.e2e.runner``,
not yet implemented) responsibility, including *writing*
``sdd/state/<feature_id>/e2e/latest.json`` (an atomically-written pointer,
``{"run_id": ...}``, updated only once teardown/cleanup for that run is
verified complete) and
``sdd/state/<feature_id>/e2e/runs/<run_id>/e2e-verdict.json``. Both paths
already fall inside ``capture_identity``'s own excluded
``sdd/state/<feature_id>/e2e/`` manifest prefix, so persisting or reading
evidence never perturbs the very identity it is validated against.

Two distinct failure shapes are used deliberately: a normal, absent, or
objectively-failed/blocked run returns a :class:`VerificationResult`
(``MISSING``/``FAIL``/``BLOCKED``) -- "MISSING is synthesized by
verification, not a fabricated successful run" -- while a *malformed,
tampered or stale* evidence blob that cannot be trusted at all raises
:class:`~parrot.e2e.errors.E2EEvidenceError` ("fails closed"), matching
that exception class's own documented contract.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from parrot.e2e.errors import E2EConfigError, E2EEvidenceError
from parrot.e2e.models import E2EPlan, E2EVerdict, SourceIdentity, VerificationResult
from parrot.e2e.plan import load_plan

__all__ = ["capture_identity", "verify_evidence"]

_GIT_BINARY = "git"

# spec §2: exclude only declared generated E2E artifacts/caches and SDD
# task/ledger bookkeeping. Every other tracked/nonignored-untracked path --
# source, templates, specs, plans, uv.lock, config -- is included.
_EXCLUDED_PREFIXES = (
    "artifacts/logs/e2e/",
    "sdd/tasks/",
    "sdd/ledger/",
)
_EXCLUDED_PATH_SEGMENTS = frozenset({"__pycache__", ".pytest_cache"})
_EXCLUDED_SUFFIXES = (".pyc", ".pyo")


async def capture_identity(plan: E2EPlan, *, worktree: Path) -> SourceIdentity:
    """Hash the normative source manifest and nonsecret environment inputs.

    Args:
        plan: The already-validated :class:`E2EPlan` (e.g. from
            :func:`parrot.e2e.plan.load_plan`) whose ``feature_id`` scopes
            the excluded run-evidence directory, whose ``spec_path`` is
            hashed separately, and whose content (including
            ``budget.model``) is hashed as ``plan_sha256``.
        worktree: Candidate worktree root; must already exist and be a Git
            checkout with at least one commit.

    Returns:
        A fully validated :class:`SourceIdentity` snapshot.

    Raises:
        E2EConfigError: If ``worktree`` does not exist or is not a
            directory, the ``git`` executable is unavailable, any Git
            command fails (e.g. ``worktree`` is not a Git repository, or has
            no commits), ``plan.spec_path`` escapes ``worktree`` or does not
            resolve to a file, or a manifest-listed path vanishes or becomes
            unreadable while being hashed.
    """
    resolved_worktree = _resolve_root(worktree)

    commit = await _capture_commit(resolved_worktree)
    manifest_entries = await _capture_manifest(resolved_worktree, feature_id=plan.feature_id)
    manifest_sha256 = _hash_canonical(manifest_entries)

    resolved_spec_path = _resolve_spec_path(resolved_worktree, plan.spec_path)
    spec_sha256 = _hash_file(resolved_spec_path)

    plan_sha256 = _hash_canonical(plan.model_dump(mode="json"))

    environment_fingerprint = await asyncio.to_thread(_capture_environment, resolved_worktree, plan)
    environment_sha256 = _hash_canonical(environment_fingerprint)

    return SourceIdentity(
        commit=commit,
        manifest_sha256=manifest_sha256,
        spec_sha256=spec_sha256,
        plan_sha256=plan_sha256,
        environment_sha256=environment_sha256,
        worktree=str(resolved_worktree),
    )


# ---------------------------------------------------------------------------
# Path resolution (mirrors parrot.e2e.plan's containment policy; kept local
# and private since that module's helpers are not part of its public API)
# ---------------------------------------------------------------------------


def _resolve_root(worktree: Path) -> Path:
    """Resolve the worktree root, requiring it to already exist.

    Args:
        worktree: Candidate worktree root.

    Returns:
        The canonical (symlink-resolved, absolute) worktree path.

    Raises:
        E2EConfigError: If ``worktree`` cannot be resolved or does not exist.
    """
    try:
        resolved = worktree.resolve(strict=True)
    except OSError as exc:
        raise E2EConfigError(
            f"worktree root does not exist or is unreadable: {worktree}: {exc}", reason_code="worktree_missing"
        ) from exc
    if not resolved.is_dir():
        raise E2EConfigError(f"worktree root is not a directory: {worktree}", reason_code="worktree_not_directory")
    return resolved


def _resolve_spec_path(worktree: Path, spec_path: str) -> Path:
    """Resolve ``plan.spec_path`` against ``worktree`` and require it exists.

    Resolution follows symlinks, so a symlink whose target lies outside
    ``worktree`` is rejected the same way a literal ``..`` traversal would
    be (spec §2 "reject traversal and escaping symlinks").

    Args:
        worktree: Canonical worktree root the spec must resolve inside of.
        spec_path: The plan's worktree-relative spec path.

    Returns:
        The resolved, contained spec file path.

    Raises:
        E2EConfigError: If the path cannot be resolved, escapes ``worktree``,
            or does not resolve to an existing file.
    """
    candidate = worktree / spec_path
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise E2EConfigError(
            f"spec_path could not be resolved: {spec_path}: {exc}", reason_code="path_unresolvable"
        ) from exc

    if resolved != worktree and worktree not in resolved.parents:
        raise E2EConfigError(
            f"spec_path escapes worktree (traversal or symlink escape): {spec_path} resolves to {resolved}, "
            f"outside {worktree}",
            reason_code="path_escape",
        )
    if not resolved.is_file():
        raise E2EConfigError(f"E2E plan references a missing spec file: {spec_path!r}", reason_code="spec_path_missing")
    return resolved


# ---------------------------------------------------------------------------
# Async Git subprocesses
# ---------------------------------------------------------------------------


async def _run_git(worktree: Path, *args: str) -> bytes:
    """Run one Git subcommand asynchronously and return its raw stdout.

    Args:
        worktree: Git checkout the command runs against (``git -C``).
        *args: Git subcommand and its arguments.

    Returns:
        The command's raw stdout bytes.

    Raises:
        E2EConfigError: If the ``git`` executable is unavailable, or the
            command exits with a nonzero status.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            _GIT_BINARY,
            "-C",
            str(worktree),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
    except OSError as exc:
        raise E2EConfigError(
            f"git executable is unavailable to capture source identity: {exc}", reason_code="git_unavailable"
        ) from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise E2EConfigError(
            f"git {' '.join(args)} failed in {worktree} (exit {process.returncode}): {detail}",
            reason_code="git_command_failed",
        )
    return stdout


async def _capture_commit(worktree: Path) -> str:
    """Return the checkout's current commit SHA via ``git rev-parse HEAD``.

    Args:
        worktree: Resolved Git checkout root.

    Returns:
        The full commit SHA, stripped of surrounding whitespace.

    Raises:
        E2EConfigError: If Git is unavailable, fails, or reports no commit
            (e.g. an empty repository with no ``HEAD``).
    """
    stdout = await _run_git(worktree, "rev-parse", "HEAD")
    commit = stdout.decode("utf-8", errors="strict").strip()
    if not commit:
        raise E2EConfigError(f"git rev-parse HEAD returned no commit in {worktree}", reason_code="git_command_failed")
    return commit


async def _list_manifest_paths(worktree: Path) -> list[str]:
    """List every tracked file plus nonignored untracked file, sorted.

    Uses ``git ls-files -z --cached --others --exclude-standard``: ``--cached``
    lists tracked (indexed) paths, ``--others`` adds untracked paths, and
    ``--exclude-standard`` applies the checkout's own ``.gitignore``/
    ``.git/info/exclude``/``core.excludesFile`` rules so ignored untracked
    files never enter the manifest. ``-z`` null-terminates entries so exotic
    filenames survive intact.

    Args:
        worktree: Resolved Git checkout root.

    Returns:
        A sorted list of worktree-relative paths (POSIX separators, as Git
        reports them).

    Raises:
        E2EConfigError: If Git is unavailable or the command fails.
    """
    stdout = await _run_git(worktree, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    paths = stdout.decode("utf-8", errors="surrogateescape").split("\0")
    return sorted({path for path in paths if path})


# ---------------------------------------------------------------------------
# Manifest construction and exclusions
# ---------------------------------------------------------------------------


def _is_excluded(path: str, *, feature_id: str) -> bool:
    """Return whether ``path`` matches a spec §2 declared manifest exclusion.

    Args:
        path: A worktree-relative, POSIX-separated candidate path.
        feature_id: The owning plan's ``feature_id``, scoping the excluded
            per-feature run-evidence/candidates directory
            (``sdd/state/<feature_id>/e2e/``).

    Returns:
        ``True`` if ``path`` is a declared generated artifact/cache or SDD
        task/ledger bookkeeping path; ``False`` otherwise (the default —
        arbitrary source, templates, specs, plans and dependencies are never
        excluded).
    """
    if path.startswith(_EXCLUDED_PREFIXES):
        return True
    if path.startswith(f"sdd/state/{feature_id}/e2e/"):
        return True
    if any(segment in _EXCLUDED_PATH_SEGMENTS for segment in path.split("/")):
        return True
    if path.endswith(_EXCLUDED_SUFFIXES):
        return True
    return False


def _build_manifest_entries(worktree: Path, paths: list[str]) -> list[dict[str, str]]:
    """Build the canonical manifest entries for ``paths`` (blocking; run off-thread).

    Args:
        worktree: Resolved Git checkout root ``paths`` are relative to.
        paths: Already-filtered, worktree-relative candidate paths.

    Returns:
        A list of ``{"path", "mode", "content"}`` mappings, sorted by path.

    Raises:
        E2EConfigError: If a listed path vanishes or is unreadable while
            being hashed (a benign race with a concurrent mutation, treated
            as a manifest capture failure rather than silently skipped).
    """
    entries: list[dict[str, str]] = []
    for relative_path in paths:
        absolute_path = worktree / relative_path
        try:
            file_stat = absolute_path.lstat()
        except OSError as exc:
            raise E2EConfigError(
                f"manifest path vanished while capturing source identity: {relative_path}: {exc}",
                reason_code="manifest_path_missing",
            ) from exc

        if stat.S_ISLNK(file_stat.st_mode):
            mode = "120000"
            content = f"symlink:{os.readlink(absolute_path)}"
        else:
            mode = "100755" if file_stat.st_mode & stat.S_IXUSR else "100644"
            try:
                digest = hashlib.sha256(absolute_path.read_bytes()).hexdigest()
            except OSError as exc:
                raise E2EConfigError(
                    f"manifest path could not be read while capturing source identity: {relative_path}: {exc}",
                    reason_code="manifest_path_unreadable",
                ) from exc
            content = f"sha256:{digest}"
        entries.append({"path": relative_path, "mode": mode, "content": content})

    entries.sort(key=lambda entry: entry["path"])
    return entries


async def _capture_manifest(worktree: Path, *, feature_id: str) -> list[dict[str, str]]:
    """List, filter and hash the checkout's canonical source manifest.

    Args:
        worktree: Resolved Git checkout root.
        feature_id: The owning plan's ``feature_id``, scoping the excluded
            per-feature run-evidence directory.

    Returns:
        The canonical sorted manifest entries (never raw file contents).
    """
    paths = await _list_manifest_paths(worktree)
    included_paths = [path for path in paths if not _is_excluded(path, feature_id=feature_id)]
    return await asyncio.to_thread(_build_manifest_entries, worktree, included_paths)


# ---------------------------------------------------------------------------
# Environment fingerprint
# ---------------------------------------------------------------------------


def _capture_environment(worktree: Path, plan: E2EPlan) -> dict[str, Any]:
    """Build the nonsecret environment fingerprint (blocking; run off-thread).

    Args:
        worktree: Resolved Git checkout root (used to locate ``uv.lock``).
        plan: The plan being captured; ``budget.model`` and each target's
            ``kind``/``profile`` are folded in as identity signals.

    Returns:
        A JSON-serializable mapping. Every value is nonsecret: opt-in
        environment variables are recorded only as a boolean "configured"
        flag or their own nonsecret content (model name, call count), never
        a credential value.
    """
    distributions: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        version = distribution.version
        if not name or not version:
            continue
        distributions[name.lower()] = version

    lock_path = worktree / "uv.lock"
    uv_lock_sha256 = _hash_file(lock_path) if lock_path.is_file() else None

    resolved_executable = Path(sys.executable).resolve() if sys.executable else None

    return {
        "python_version": sys.version,
        "python_executable": str(resolved_executable) if resolved_executable else None,
        "distributions": distributions,
        "uv_lock_sha256": uv_lock_sha256,
        "model": plan.budget.model,
        "targets": sorted(f"{target_id}:{config.kind}:{config.profile}" for target_id, config in plan.targets.items()),
        "opt_ins": {
            "PARROT_TEST_E2E": os.environ.get("PARROT_TEST_E2E"),
            "PARROT_TEST_REAL_LLM": os.environ.get("PARROT_TEST_REAL_LLM"),
            "E2E_MODEL": os.environ.get("E2E_MODEL"),
            "E2E_MAX_LLM_CALLS": os.environ.get("E2E_MAX_LLM_CALLS"),
            "google_api_key_configured": bool(os.environ.get("GOOGLE_API_KEY")),
        },
    }


# ---------------------------------------------------------------------------
# Canonical hashing
# ---------------------------------------------------------------------------


def _hash_canonical(payload: Any) -> str:
    """Hash ``payload`` as canonical (sorted-key, whitespace-free) JSON.

    Args:
        payload: A JSON-serializable value (list/dict of primitives).

    Returns:
        The lowercase hex SHA-256 digest of the canonical JSON encoding.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    """Hash one file's raw bytes.

    Args:
        path: File to hash.

    Returns:
        The lowercase hex SHA-256 digest of the file's content.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# verify_evidence (TASK-3523)
# ---------------------------------------------------------------------------

# spec §2: "Persist immutable per-run evidence under
# sdd/state/<FEAT-ID>/e2e/runs/<run-id>/; atomically update e2e-verdict.json
# only after shutdown." A per-feature pointer, updated only once a run's
# cleanup is verified complete, is how verify_evidence -- which takes no
# run_id -- locates "the" run to validate for a given plan.
_RUNS_DIRNAME = "runs"
_POINTER_FILENAME = "latest.json"
_VERDICT_FILENAME = "e2e-verdict.json"

# Mirrors parrot.e2e.models._SAFE_ID_RE (private there; re-declared here per
# this module's existing containment-check convention, see TASK-3522).
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# spec §2 exit table: 130/143 are SIGINT/SIGTERM interruption; "Partial/
# interrupted runs may be inspected but cannot validate."
_INTERRUPTED_EXIT_CODES = frozenset({130, 143})


async def verify_evidence(plan_path: Path, *, worktree: Path) -> VerificationResult:
    """Validate immutable run artifacts and current implementation identity.

    Locates the plan's feature-scoped evidence pointer, loads and schema-
    validates the persisted :class:`E2EVerdict` it names, verifies every
    referenced artifact's hash, confirms the run's own before/after source
    identity never changed mid-execution, recomputes the *current*
    :class:`SourceIdentity` via :func:`capture_identity` and requires it to
    match the recorded one (spec §2: "accept only matching commit or
    content-identical descendant" -- content hashes, not the commit SHA
    itself, gate acceptance), then evaluates exact node coverage, required
    per-node pytest phase outcomes and target/runner cleanup.

    Args:
        plan_path: Path to the ``e2e-plan.md`` document (see
            :func:`parrot.e2e.plan.load_plan`); its resolved location must
            lie inside ``worktree``.
        worktree: Candidate worktree root; must already exist and be a Git
            checkout with at least one commit.

    Returns:
        A :class:`VerificationResult`:

        * ``PASS`` -- policy ``none`` (explicit exemption, no execution
          fabricated), or every required codified node passed with a clean
          setup/call/teardown and verified cleanup.
        * ``MISSING`` -- no evidence pointer/verdict found yet, or the
          recorded run was interrupted (SIGINT/SIGTERM) and therefore
          cannot be validated at all.
        * ``BLOCKED`` -- zero nodes were collected, or every collected node
          was merely skipped (a no-test/all-skipped run is never a PASS).
        * ``FAIL`` -- a required node did not pass (including a skip/xfail/
          xpass/missing outcome or a failed setup/call/teardown phase), or
          recorded target/runner cleanup was not verified complete.

    Raises:
        E2EConfigError: If ``worktree``/``plan_path`` cannot be resolved, or
            the plan itself fails :func:`parrot.e2e.plan.load_plan`
            validation (propagated unchanged).
        E2EEvidenceError: If the located evidence is malformed (invalid
            JSON, failed :class:`E2EVerdict` schema validation, an unsafe
            pointer ``run_id``, a ``feature_id`` mismatch), tampered (an
            artifact's content no longer matches its recorded hash, or
            ``selected_node_ids``/``collected_node_ids`` disagree with the
            plan's own current declared/selected node IDs), records a
            source identity mutation *during* its own execution (before !=
            after), or its recorded identity no longer matches the current
            implementation (stale: source, spec, plan or environment
            changed since the run) -- this "fails closed" per spec §2.
    """
    resolved_worktree = _resolve_root(worktree)
    plan = load_plan(plan_path, worktree=resolved_worktree)

    if plan.policy == "none":
        return VerificationResult(
            status="PASS",
            gate_satisfied=True,
            reason_codes=["policy_none_no_execution"],
        )

    evidence_root = resolved_worktree / "sdd" / "state" / plan.feature_id / "e2e"
    pointer_path = evidence_root / _POINTER_FILENAME
    if not pointer_path.is_file():
        return VerificationResult(status="MISSING", gate_satisfied=False, reason_codes=["evidence_pointer_missing"])

    run_id = _read_pointer_run_id(pointer_path)
    if run_id is None:
        return VerificationResult(status="MISSING", gate_satisfied=False, reason_codes=["evidence_pointer_malformed"])

    verdict_dir = _resolve_run_dir(evidence_root, run_id)
    if verdict_dir is None:
        raise E2EEvidenceError(
            f"E2E evidence pointer {pointer_path} references an unsafe or escaping run_id: {run_id!r}",
            reason_code="evidence_run_id_unsafe",
        )

    verdict_path = verdict_dir / _VERDICT_FILENAME
    if not verdict_path.is_file():
        return VerificationResult(status="MISSING", gate_satisfied=False, reason_codes=["evidence_verdict_missing"])

    verdict = _load_verdict(verdict_path)

    if verdict.feature_id != plan.feature_id:
        raise E2EEvidenceError(
            f"E2E verdict {verdict_path} feature_id {verdict.feature_id!r} does not match plan feature_id "
            f"{plan.feature_id!r}",
            reason_code="evidence_feature_mismatch",
        )

    if verdict.exit_code in _INTERRUPTED_EXIT_CODES:
        return VerificationResult(status="MISSING", gate_satisfied=False, reason_codes=["run_interrupted"])

    if verdict.source_identity_before != verdict.source_identity_after:
        raise E2EEvidenceError(
            f"E2E verdict {verdict_path} records a source identity change between its own before/after capture "
            "(a mutation occurred during execution)",
            reason_code="source_identity_changed_during_run",
        )

    _verify_artifact_hashes(verdict_dir, verdict.artifact_hashes)

    current_identity = await capture_identity(plan, worktree=resolved_worktree)
    recorded_identity = verdict.source_identity_after
    if (
        current_identity.manifest_sha256 != recorded_identity.manifest_sha256
        or current_identity.spec_sha256 != recorded_identity.spec_sha256
        or current_identity.plan_sha256 != recorded_identity.plan_sha256
        or current_identity.environment_sha256 != recorded_identity.environment_sha256
    ):
        raise E2EEvidenceError(
            f"E2E verdict {verdict_path} source identity no longer matches the current implementation "
            "(source, spec, plan or environment changed since the recorded run; a new run is required)",
            reason_code="source_identity_stale",
        )

    all_codified_node_ids = {
        node_id for scenario in plan.scenarios if scenario.tier != "exploratory" for node_id in scenario.node_ids
    }
    selected = set(verdict.selected_node_ids)
    if all_codified_node_ids and selected != all_codified_node_ids:
        raise E2EEvidenceError(
            f"E2E verdict {verdict_path} selected_node_ids does not match the plan's current codified node IDs",
            reason_code="selected_nodes_mismatch",
        )

    collected = set(verdict.collected_node_ids)
    if collected - selected:
        raise E2EEvidenceError(
            f"E2E verdict {verdict_path} collected_node_ids includes nodes outside its own selection",
            reason_code="collected_nodes_unselected",
        )

    if verdict.cleanup_results and not all(verdict.cleanup_results.values()):
        return VerificationResult(status="FAIL", gate_satisfied=False, reason_codes=["cleanup_incomplete"])

    # spec §2 / this task's own scope: "no-test/all-skipped is BLOCKED". A
    # *failing* (or xfailed/xpassed) required node still means pytest ran
    # and reported something -- that is a coverage FAIL below, not BLOCKED.
    # BLOCKED is reserved for "nothing was actually collected/executed at
    # all" (zero collection, or every collected node merely skipped).
    outcomes = [result.outcome for result in verdict.results]
    all_skipped = bool(outcomes) and all(outcome == "skipped" for outcome in outcomes)
    if all_codified_node_ids and (not collected or all_skipped):
        return VerificationResult(
            status="BLOCKED", gate_satisfied=False, reason_codes=["no_codified_scenario_executed"]
        )

    required_node_ids = {
        node_id
        for scenario in plan.scenarios
        if scenario.required and scenario.tier != "exploratory"
        for node_id in scenario.node_ids
    }
    results_by_node = {result.node_id: result for result in verdict.results}
    reason_codes: list[str] = []
    for node_id in sorted(required_node_ids):
        result = results_by_node.get(node_id)
        if result is None:
            reason_codes.append(f"required_node_missing:{node_id}")
            continue
        if result.outcome != "passed":
            reason_codes.append(f"required_node_not_passed:{node_id}:{result.outcome}")
            continue
        if result.setup_outcome not in (None, "passed"):
            reason_codes.append(f"required_node_setup_failure:{node_id}")
        if result.call_outcome not in (None, "passed"):
            reason_codes.append(f"required_node_call_failure:{node_id}")
        if result.teardown_outcome not in (None, "passed"):
            reason_codes.append(f"required_node_teardown_failure:{node_id}")

    if reason_codes:
        return VerificationResult(status="FAIL", gate_satisfied=False, reason_codes=reason_codes)

    return VerificationResult(status="PASS", gate_satisfied=True, reason_codes=[])


def _read_pointer_run_id(pointer_path: Path) -> Optional[str]:
    """Read and validate the ``run_id`` named by a per-feature evidence pointer.

    Args:
        pointer_path: Path to the ``latest.json`` pointer file.

    Returns:
        The pointed-to ``run_id`` if the pointer is valid JSON, is a
        mapping, and names a safe slug; ``None`` if the pointer is
        malformed in any way (never raises -- a malformed pointer is
        reported by the caller as :class:`VerificationResult` ``MISSING``,
        not treated as tampering).
    """
    try:
        raw = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    run_id = raw.get("run_id")
    if not isinstance(run_id, str) or not _RUN_ID_RE.match(run_id):
        return None
    return run_id


def _resolve_run_dir(evidence_root: Path, run_id: str) -> Optional[Path]:
    """Resolve one run's evidence directory, rejecting any path escape.

    Args:
        evidence_root: Resolved ``sdd/state/<feature_id>/e2e`` directory.
        run_id: Already slug-validated candidate run ID.

    Returns:
        The resolved, contained run evidence directory, or ``None`` if it
        cannot be resolved or escapes ``evidence_root/runs``.
    """
    runs_root = evidence_root / _RUNS_DIRNAME
    candidate = runs_root / run_id
    try:
        resolved_candidate = candidate.resolve(strict=False)
        resolved_runs_root = runs_root.resolve(strict=False)
    except OSError:
        return None
    if resolved_candidate != resolved_runs_root and resolved_runs_root not in resolved_candidate.parents:
        return None
    return resolved_candidate


def _load_verdict(verdict_path: Path) -> E2EVerdict:
    """Read and schema-validate one persisted :class:`E2EVerdict`.

    Args:
        verdict_path: Path to the run's ``e2e-verdict.json`` file.

    Returns:
        The validated :class:`E2EVerdict`.

    Raises:
        E2EEvidenceError: If the file cannot be read, is not valid JSON, or
            fails :class:`E2EVerdict` schema validation -- an unknown or
            malformed schema "fails closed" per spec §2.
    """
    try:
        raw = json.loads(verdict_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise E2EEvidenceError(
            f"E2E verdict file could not be read or is not valid JSON: {verdict_path}: {exc}",
            reason_code="evidence_verdict_invalid_json",
        ) from exc
    try:
        return E2EVerdict.model_validate(raw)
    except ValidationError as exc:
        raise E2EEvidenceError(
            f"E2E verdict file failed schema validation: {verdict_path}: {exc}",
            reason_code="evidence_verdict_malformed",
        ) from exc


def _verify_artifact_hashes(verdict_dir: Path, artifact_hashes: dict[str, str]) -> None:
    """Verify every recorded artifact still exists, is contained, and hashes match.

    Args:
        verdict_dir: The run's resolved evidence directory; every artifact
            path is relative to it.
        artifact_hashes: :class:`E2EVerdict.artifact_hashes` -- relative
            path to expected lowercase hex SHA-256 digest.

    Raises:
        E2EEvidenceError: If an artifact is missing, its resolved path
            escapes ``verdict_dir``, or its current content hash does not
            match the recorded digest (tampered or corrupted).
    """
    for relative_path, expected_digest in artifact_hashes.items():
        candidate = verdict_dir / relative_path
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise E2EEvidenceError(
                f"E2E evidence artifact is missing: {relative_path}: {exc}",
                reason_code="evidence_artifact_missing",
            ) from exc
        if resolved != verdict_dir and verdict_dir not in resolved.parents:
            raise E2EEvidenceError(
                f"E2E evidence artifact path escapes its run directory: {relative_path}",
                reason_code="evidence_artifact_path_escape",
            )
        if _hash_file(resolved) != expected_digest:
            raise E2EEvidenceError(
                f"E2E evidence artifact hash mismatch (tampered or corrupted): {relative_path}",
                reason_code="evidence_artifact_tampered",
            )
