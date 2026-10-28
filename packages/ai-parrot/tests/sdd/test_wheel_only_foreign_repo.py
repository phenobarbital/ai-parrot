"""C3 (FEAT-633 rev 0.2/0.3): prove the SDD flow from the BUILT WHEEL in a clean foreign repo.

Merge tier only (builds a wheel). Nothing here imports parrot: every assertion goes through
subprocesses whose PATH holds only $PARROT_HOME/bin and an allowlisted tools dir, with every
Python/venv/parrot override variable unset. Helpers are never mocked.

``PARROT_WHEEL_PATH`` (TASK-4094): when set, that wheel is installed instead of building one.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

pytestmark = pytest.mark.integration  # FEAT-563 auto-mark covers only integration/ dirs — mark explicitly

REPO_ROOT = Path(__file__).resolve().parents[4]
INVOCATION_RE = re.compile(r"parrot sdd run ([a-z0-9_]+)((?: [^\n`]*)?)")  # digits: check_e2e_closeout
#: A `\`-continued shell line is one command: join before matching, or the flags on the next lines are lost.
CONTINUATION_RE = re.compile(r"\\\n[ \t]*")
#: The argv ends at the first shell control operator — e.g. the C16 frontmatter hook
#: `parrot sdd run worktree_environment --hook || exit 2'` runs as `worktree_environment --hook`.
SHELL_CUT_RE = re.compile(r"\s+(?:\|\||&&|\|)\s+|;")
#: Shell-only tails that are not helper arguments.
REDIRECT_RE = re.compile(r"\s+2>(?:/dev/null|&1)")
COMMENT_RE = re.compile(r"\s+#.*$")
#: An optional `[--flag value]` group (also an unterminated one cut by the line end).
OPTIONAL_RE = re.compile(r"\[[^\]]*(?:\]|$)")
#: Every host's install tree is scanned (AC: "all three hosts").
INSTALLED_DIRS = (".claude", ".agents", ".agent", ".codex", "sdd")
#: ``CLAUDE_PROJECT_DIR`` is a launcher project pin too: inside a Claude Code session it would point the managed
#: launcher at the outer checkout's ``.venv`` instead of the wheel under test.
SCRUBBED_ENV = (
    "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PARROT_VENV", "PARROT_PROJECT", "CLAUDE_PROJECT_DIR", "CONDA_PREFIX",
)
#: System tools the fixture PATH may expose; anything else must come from the wheel.
TOOL_ALLOWLIST = ("git", "bash", "sh", "jq")
GUARD_LINE = "parrot sdd run worktree_environment --hook || exit 2"
FEAT = "FEAT-001"
SLUG = "demo-feature"

if shutil.which("uv") is None:  # pragma: no cover — this module must never import parrot itself
    pytest.skip("uv not on PATH", allow_module_level=True)


# --------------------------------------------------------------------------
# fixture state helpers (plain git + files; no parrot import)
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` with a fixed identity; return stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@x", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit_push(repo: Path, message: str = "fixture") -> None:
    """Commit everything under sdd/ plus the managed gitignore/gitattributes and push to origin main and dev."""
    paths = [p for p in ("sdd", ".gitignore", ".gitattributes") if (repo / p).exists()]
    _git(repo, "add", "-f", *paths)
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        _git(repo, "commit", "-qm", message)
    _git(repo, "push", "-q", "origin", "HEAD:main")
    _git(repo, "push", "-q", "origin", "HEAD:dev")


SPEC_MD = f"""---
type: feature
base_branch: dev
projects: []
tags: []
---

# Feature Specification: Demo Feature

**Feature ID**: {FEAT}
**Status**: approved

## 4. Test Specification

### Validation Contract

none — fallback
"""
SPEC_NO_SECTION_MD = SPEC_MD.split("### Validation Contract")[0]


def _task_entry() -> dict[str, object]:
    return {
        "id": "TASK-001",
        "slug": "demo-task",
        "title": "Demo task",
        "feature_id": FEAT,
        "feature": SLUG,
        "spec": f"sdd/specs/{SLUG}.spec.md",
        "status": "pending",
        "priority": "high",
        "effort": "S",
        "depends_on": [],
        "parallel": True,
        "parallelism_notes": "",
        "assigned_to": None,
        "started_at": None,
        "completed_at": None,
        "file": "sdd/tasks/active/TASK-001-demo-task.md",
    }


def _seed_feature(clone: Path) -> None:
    """Spec + per-spec index + one active task, committed and pushed to origin (main and dev)."""
    (clone / "sdd/specs").mkdir(parents=True, exist_ok=True)
    (clone / "sdd/tasks/active").mkdir(parents=True, exist_ok=True)
    (clone / "sdd/tasks/index").mkdir(parents=True, exist_ok=True)
    (clone / f"sdd/specs/{SLUG}.spec.md").write_text(SPEC_MD, encoding="utf-8")
    (clone / f"sdd/specs/{SLUG}-nosection.spec.md").write_text(SPEC_NO_SECTION_MD, encoding="utf-8")
    (clone / "sdd/tasks/active/TASK-001-demo-task.md").write_text(
        "# TASK-001: Demo task\n\n**Feature**: FEAT-001\n**Status**: pending\n\n## Validation Commands\n\n"
        "- `pytest tests/test_demo.py -q`\n", encoding="utf-8"
    )
    index = {
        "feature": SLUG,
        "feature_id": FEAT,
        "spec": f"sdd/specs/{SLUG}.spec.md",
        "type": "feature",
        "base_branch": "dev",
        "created_at": "2026-01-01T00:00:00+00:00",
        "completed_at": None,
        "parallel_semantics": "exclusive",
        "validation_contract": "required",
        "tasks": [_task_entry()],
    }
    (clone / f"sdd/tasks/index/{SLUG}.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    _commit_push(clone, "fixture: demo feature")


def _seed_worktree(clone: Path) -> None:
    """``_seed_feature`` plus the feature worktree (a plain `git worktree add`, as ensure_worktree would make)."""
    _seed_feature(clone)
    _git(clone, "fetch", "-q", "origin")
    _git(clone, "worktree", "add", "-q", f".claude/worktrees/feat-{FEAT}-{SLUG}", "-b", f"feat-{FEAT}-{SLUG}", "origin/dev")


def _seed_hook_context(clone: Path) -> None:
    """``_seed_worktree`` plus the closeout-hook context JSON that ``/sdd-done`` writes (FEAT-764)."""
    _seed_worktree(clone)
    hooks = clone / "hooks"
    hooks.mkdir()
    (hooks / "context.json").write_text(json.dumps({
        "feat_id": FEAT,
        "spec_path": f"sdd/specs/{SLUG}.spec.md",
        "branch": f"feat-{FEAT}-{SLUG}",
        "base_branch": "dev",
        "worktree": str(clone / f".claude/worktrees/feat-{FEAT}-{SLUG}"),
    }))


def _seed_on_dev(clone: Path) -> None:
    """``_seed_feature`` with ``dev`` checked out (tracking origin/dev), as /sdd-spec and /sdd-task run."""
    _seed_feature(clone)
    _git(clone, "fetch", "-q", "origin")
    _git(clone, "checkout", "-q", "-B", "dev", "origin/dev")


def _seed_brief(clone: Path) -> None:
    """A brief rendered from the installed sdd/templates/brief.md, its task list, and a worktree directory."""
    template = (clone / "sdd/templates/brief.md").read_text(encoding="utf-8")
    brief = (
        template.replace("<slug>", "demo")
        .replace("<key>", "KEY-1")
        .replace("<base_branch>", "main")
        .replace("<source_type>", "jira")
        .replace("<source_ref>", "KEY-1")
        .replace("<source_url>", "https://example.invalid/KEY-1")
        .replace("<created>", "'2026-01-01T00:00:00+00:00'")
        .replace("<Title>", "Demo")
    )
    (clone / "brief.md").write_text(brief, encoding="utf-8")
    task = {
        "id": "HOTFIX-KEY-1-1",
        "slug": "demo-task",
        "title": "Demo",
        "file": "sdd/briefs/demo/tasks/HOTFIX-KEY-1-1-demo-task.md",
    }
    (clone / "tasks.json").write_text(json.dumps([task]), encoding="utf-8")
    (clone / "wt").mkdir()


def _seed_brief_index(clone: Path) -> None:
    """A per-brief index under ``<wt>/sdd/briefs/demo.index.json`` (as ``brief_meta write-index`` writes it)."""
    _seed_brief(clone)
    index = {
        "feature": "demo",
        "feature_id": "BRIEF-KEY-1",
        "spec": "sdd/briefs/demo.brief.md",
        "type": "brief",
        "base_branch": "main",
        "created_at": "2026-01-01T00:00:00+00:00",
        "completed_at": None,
        "parallel_semantics": "exclusive",
        "validation_contract": "required",
        "tasks": [{**_task_entry(), "id": "HOTFIX-KEY-1-1", "feature_id": "BRIEF-KEY-1", "feature": "demo"}],
    }
    path = clone / "wt/sdd/briefs/demo.index.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def _seed_spec_tools(clone: Path) -> None:
    """``$DR`` with the six brief inputs + a sample ``suggestions.json``, and ``$STAGE/intake.json``."""
    dr = clone / "dr"
    dr.mkdir()
    for name in ("problem_statement", "constraints_and_goals", "recommended_option_or_scope", "code_context_paths",
                 "open_questions", "question"):
        (dr / f"{name}.txt").write_text(f"sample {name}\n", encoding="utf-8")
    suggestions = {
        "summary": "Looks fine.",
        "suggestions": [
            {
                "id": "S1",
                "kind": "testing",
                "title": "Add a test",
                "rationale": "README.md has no checks.",
                "affected_paths": ["README.md"],
                "risk": "low",
                "confidence": "high",
            }
        ],
    }
    (dr / "suggestions.json").write_text(json.dumps(suggestions), encoding="utf-8")
    (dr / "run.json").write_text("{}", encoding="utf-8")
    (dr / "probe.txt").write_text("codex 0.0\n", encoding="utf-8")
    (clone / "stage").mkdir()
    (clone / "stage/intake.json").write_text("{}", encoding="utf-8")


def _seed_proposal(clone: Path) -> None:
    """A brainstorm document for ``sdd_meta resolve-flow --doc``."""
    _seed_feature(clone)
    (clone / "sdd/proposals").mkdir(parents=True, exist_ok=True)
    (clone / "sdd/proposals/demo.brainstorm.md").write_text(
        "---\ntype: feature\nbase_branch: dev\nprojects: []\ntags: []\n---\n\n# Brainstorm: demo\n", encoding="utf-8"
    )


def _seed_evidence(clone: Path) -> None:
    """A worktree plus a (deliberately minimal) completion-evidence file for ``finalize_task``."""
    _seed_worktree(clone)
    (clone / "evidence.json").write_text(json.dumps({"task_id": "TASK-001"}), encoding="utf-8")


def _seed_venv_marker(clone: Path) -> None:
    """``<clone>/.venv/pyvenv.cfg`` — a project environment the guard hook must protect (C16)."""
    (clone / ".venv").mkdir()
    (clone / ".venv/pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")


def _hook_stdin(clone: Path) -> str:
    payload = {"cwd": str(clone), "tool_name": "Write", "tool_input": {"file_path": str(clone / ".venv/x.py")}}
    return json.dumps(payload)


# --------------------------------------------------------------------------
# scenarios — one per helper name found in installed markdown
# --------------------------------------------------------------------------

#: Placeholders every documented invocation may carry; a scenario adds or overrides its own. ``<repo>`` is the
#: scenario clone, ``<head>`` its HEAD sha. Keys are replaced longest first.
COMMON: dict[str, str] = {
    "<FEAT-ID>": FEAT,
    "FEAT-<NNN>": FEAT,
    "FEAT-<ID>": FEAT,
    "$FEAT_ID": FEAT,
    "TASK-<NNN>": "TASK-001",
    "<TASK-ID>": "TASK-001",
    "$TASK_ID": "TASK-001",
    "<feature-slug>": SLUG,
    "<suggested_slug>": SLUG,
    "<feature-name>": SLUG,
    "<slug>": SLUG,
    "$FEATURE_SLUG": SLUG,
    "<verification>": "verified",
    "$VERIFICATION": "verified",
    "<base_branch>": "dev",
    "$BASE_BRANCH": "dev",
    "$BASE": "dev",
    "<base>": "main",
    "<branch>": "main",
    "<KEY>": "KEY-1",
    "<issue-short-id>": "ab12cd34",
    "<suggested_slug>": "demo-fix",
    "<JIRA-KEY>": "KEY-1",
    "<N>": "2",
    "<spec-path>": f"sdd/specs/{SLUG}.spec.md",
    "<spec>": f"sdd/specs/{SLUG}.spec.md",
    "<idx>": f"sdd/tasks/index/{SLUG}.json",
    "<index>": f"sdd/tasks/index/{SLUG}.json",
    "$IDX": f"sdd/tasks/index/{SLUG}.json",
    "$INDEX": f"sdd/tasks/index/{SLUG}.json",
    "<wt>": f"<repo>/.claude/worktrees/feat-{FEAT}-{SLUG}",
    "<worktree>": f"<repo>/.claude/worktrees/feat-{FEAT}-{SLUG}",
    "<this worktree>": f"<repo>/.claude/worktrees/feat-{FEAT}-{SLUG}",
    "$WORKTREE_PATH": f"<repo>/.claude/worktrees/feat-{FEAT}-{SLUG}",
    "$WT": f"<repo>/.claude/worktrees/feat-{FEAT}-{SLUG}",
    "$TEST_REPORT_MD": "<repo>/test-report.md",
    "<full HEAD SHA>": "<head>",
    "<post-merge HEAD>": "<head>",
    "<uuid>": "11111111-1111-4111-8111-111111111111",
    "--evidence <path>": "--evidence <repo>/evidence.json",
    "--worktree <path>": f"--worktree <repo>/.claude/worktrees/feat-{FEAT}-{SLUG}",
    "<p>": "demo",
    "<t>": "demo",
    "$(printf -- '--task-file %s ' <every task file of the index>)": "--task-file sdd/tasks/active/TASK-001-demo-task.md",
    "$(printf -- '--task-file %s ' $TASK_FILES)": "--task-file sdd/tasks/active/TASK-001-demo-task.md",
}


@dataclass
class Scenario:
    """How to run one documented helper invocation: placeholder values + required state."""

    placeholders: dict[str, str] = field(default_factory=dict)
    prepare: Callable[[Path], None] = lambda repo: None  # creates ledger/task/index/evidence in a fresh clone
    #: Accepted exit codes. A non-zero code is only accepted for helpers whose success needs state a foreign
    #: fixture cannot reasonably fake; a ``Traceback`` on stderr is never accepted.
    expect_exit: tuple[int, ...] = (0,)
    tools: tuple[str, ...] = ("git",)
    stdin: Callable[[Path], str] | None = None  # e.g. the worktree_environment hook's PreToolUse payload
    expect_stdout: str = ""  # substring the helper's stdout must contain (e.g. '"permissionDecision": "deny"')
    #: Documented argv texts that are prose fragments (an abbreviated flag list, a sentence), not full command
    #: lines: they are exercised as ``--help`` so the helper is still dispatched and loaded.
    prose: tuple[str, ...] = ()
    #: Documented flags not passed to the helper (see the owning scenario for why).
    drop_flags: tuple[str, ...] = ()


_FEATURE = Scenario(prepare=_seed_feature)
_WORKTREE = Scenario(prepare=_seed_worktree)
_ANY_CLEAN = (0, 1, 2)  # a controlled refusal is fine; a traceback is not

SCENARIOS: dict[str, Scenario] = {
    "backfill_taxonomy": Scenario(prepare=_seed_feature),
    "brief_meta": Scenario(prepare=_seed_brief, placeholders={
        "<brief.md>": "<repo>/brief.md", "<tasks.json>": "<repo>/tasks.json", "<wt>": "<repo>/wt"}),
    "cache_test_contract": Scenario(prepare=_seed_feature),
    "check_e2e_closeout": Scenario(
        prepare=_seed_worktree,
        expect_exit=_ANY_CLEAN,
        prose=("--spec <spec-path>",),
    ),
    "check_task_graph": Scenario(
        prepare=lambda c: (_seed_feature(c), _seed_brief_index(c)),
        placeholders={"<wt>": "<repo>/wt", "<slug>": "demo"},  # the brief index is `<wt>/sdd/briefs/demo.index.json`
    ),
    "close_resolved_issues": Scenario(
        prepare=_seed_worktree,
        expect_exit=_ANY_CLEAN,  # shells out to `wikitoolkit ledger close`; a bare ledger is a clean refusal
        prose=("--worktree <worktree>",),
    ),
    "close_task": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN, prose=('always writes status "done"',)),
    "doc_taxonomy": Scenario(prepare=_seed_feature, prose=("--kind spec --paths-only ...",)),
    "ensure_worktree": Scenario(prepare=_seed_feature),
    "finalize_task": Scenario(
        prepare=_seed_evidence,
        expect_exit=_ANY_CLEAN,  # a minimal evidence file is rejected cleanly by the schema check
        prose=("--evidence <path> --worktree <path>",),
    ),
    "heal_orphans": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN),
    "install_hooks": Scenario(prepare=_seed_feature),
    "reserve_ids": Scenario(
        prepare=_seed_on_dev,  # reserve_ids must run with the base branch checked out
        # a new slug: the fixture feature already owns FEAT-001 and the allocator refuses a second reservation
        placeholders={"<feature-slug>": "new-feature", "<suggested_slug>": "new-feature", "<feature-name>": "new-feature"},
    ),
    # a minimal fixture has no per-feature settlement index: exit 3 is the helper's controlled refusal
    "review_checkpoint": Scenario(prepare=_seed_worktree, expect_exit=(0, 1, 2, 3)),
    # no `.parrot/sdd_hooks.toml` in the fixture: every event runs zero hooks; --record/--finalize need prior state
    "run_closeout_hooks": Scenario(
        prepare=_seed_hook_context,
        expect_exit=_ANY_CLEAN,
        placeholders={
            "<ctx>": "<repo>/hooks/context.json",
            "$HOOKS_DIR": "<repo>/hooks",
            "<name>": "demo-hook",
            "${DRY_RUN:+--dry-run}": "",  # the documented optional flag, expanded as when --dry-run is not given
            "pass|fail": "fail",
            "<one line>": "demo summary",
        },
    ),
    "sdd_meta": Scenario(prepare=_seed_proposal, placeholders={
        "<brainstorm-or-proposal-path>": "<repo>/sdd/proposals/demo.brainstorm.md",
        "<--type value>": "feature",
        "<--base-branch value>": "dev",
    }),
    # `--run` executes the planned runner, which a foreign repo may not have: a missing runner is a one-line
    # refusal (exit 1), never a traceback (rev 0.5 D2 / C21).
    "select_tests": Scenario(prepare=_seed_worktree, expect_exit=_ANY_CLEAN),
    "spec_tools": Scenario(prepare=_seed_spec_tools, placeholders={
        "$DR": "<repo>/dr", "$MODEL": "gpt", "$CODEX_VERSION": "0.0", "$STARTED_AT": "2026-01-01T00:00:00Z",
        "$ENDED_AT": "2026-01-01T00:00:01Z", "$rc": "0", "$STAGE": "<repo>/stage", "$REPO_ROOT": "<repo>",
        "<path>": "<repo>/README.md"}),
    "test_report": Scenario(prepare=_seed_worktree),
    "worktree_environment": Scenario(
        prepare=_seed_venv_marker,
        stdin=_hook_stdin,
        expect_stdout='"permissionDecision": "deny"',
    ),
    "worktree_status": Scenario(prepare=_seed_worktree),
    # present in the packaged scripts; markdown does not (yet) invoke them, so they are exercised only if it does
    "check_id_collisions": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN),
    "check_task_state": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN),
    "id_ledger": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN),
    "migrate_index": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN),
}


# --------------------------------------------------------------------------
# wheel + managed install
# --------------------------------------------------------------------------


def _python_for(wheel: Path) -> str:
    """The interpreter the wheel was built for (``cp311`` → 3.11); pure-Python wheels get 3.12."""
    match = re.search(r"-cp(\d)(\d+)-", wheel.name)
    return f"{match.group(1)}.{match.group(2)}" if match else "3.12"


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    prebuilt = os.environ.get("PARROT_WHEEL_PATH")
    if prebuilt:
        return Path(prebuilt)
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out), str(REPO_ROOT / "packages/ai-parrot")], check=True)
    return next(out.glob("ai_parrot-*.whl"))


@pytest.fixture(scope="module")
def managed_home(wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """~/.parrot-like tree whose venv has ONLY the wheel + its declared runtime deps (non-editable)."""
    home = tmp_path_factory.mktemp("parrot-home")
    subprocess.run(["uv", "venv", str(home / "venv"), "--python", _python_for(wheel)], check=True)
    subprocess.run(["uv", "pip", "install", "--python", str(home / "venv/bin/python"), str(wheel)], check=True)
    (home / "bin").mkdir()
    for name in ("parrot", "wikitoolkit", "bookstore"):
        os.symlink(home / "venv/bin" / name, home / "bin" / name)
    # navconfig derives its project root from the venv's parent and refuses to start without env/<env>/.env
    (home / "env/dev").mkdir(parents=True)
    (home / "env/dev/.env").write_text("", encoding="utf-8")
    return home


@pytest.fixture(scope="module")
def tools_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tools = tmp_path_factory.mktemp("tools")
    for name in TOOL_ALLOWLIST:
        if (found := shutil.which(name)) is not None:
            os.symlink(found, tools / name)
    assert (tools / "git").exists(), "git is a hard prerequisite of every scenario"
    return tools


def _env(home: Path, tools: Path, *, with_launcher: bool = True) -> dict[str, str]:
    """Scrubbed environment: PATH = ``$PARROT_HOME/bin`` (unless ``with_launcher`` is False) + allowlisted tools."""
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV and not k.startswith("GIT_")}
    env["PATH"] = f"{home / 'bin'}{os.pathsep}{tools}" if with_launcher else str(tools)
    env["PARROT_HOME"] = str(home)
    env["HOME"] = str(home / "user-home")
    (home / "user-home").mkdir(exist_ok=True)
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")
    return env


@pytest.fixture
def foreign_repo(tmp_path: Path) -> tuple[Path, Path]:
    """(working clone, bare origin) of an unrelated non-Python repo with one commit on main and dev."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    (repo / "README.md").write_text("# not a python project\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "push", "-q", "-u", "origin", "main")
    _git(repo, "push", "-q", "origin", "main:dev")
    return repo, origin


def test_parrot_resolves_to_managed_install(managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path]) -> None:
    repo, _ = foreign_repo
    env = _env(managed_home, tools_dir)
    which = subprocess.run(["bash", "-c", "command -v parrot"], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert Path(which.stdout.strip()).resolve() == (managed_home / "venv/bin/parrot").resolve()
    env_out = subprocess.run(["parrot", "self", "env"], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout
    assert str(managed_home / "venv") in env_out and "rule: managed" in env_out  # TASK-4080 `self env` format


# --------------------------------------------------------------------------
# every documented helper invocation
# --------------------------------------------------------------------------


def _collect_invocations(repo: Path) -> set[tuple[str, str]]:
    """``(helper, argv text)`` for every ``parrot sdd run`` form found in every host's installed markdown/toml."""
    texts = "\n".join(
        p.read_text(encoding="utf-8")
        for d in INSTALLED_DIRS
        if (repo / d).is_dir()
        for p in sorted((repo / d).rglob("*"))
        if p.is_file() and p.suffix in {".md", ".toml"}
    )
    texts = CONTINUATION_RE.sub(" ", texts)
    assert "python -m parrot.sdd.scripts" not in texts, "Q1: shipped markdown must use `parrot sdd run`"
    return {
        (m.group(1), SHELL_CUT_RE.split(m.group(2), maxsplit=1)[0].rstrip(")").strip())
        for m in INVOCATION_RE.finditer(texts)
    }


def _argv_for(name: str, argv: str, scenario: Scenario, clone: Path) -> list[str]:
    """Substitute placeholders and shell variables, drop optional groups/comments; ``--help`` for prose."""
    if not argv or argv in scenario.prose:
        return ["--help"]
    argv = REDIRECT_RE.sub("", argv)
    argv = COMMENT_RE.sub("", argv)
    argv = OPTIONAL_RE.sub("", argv)
    head = _git(clone, "rev-parse", "HEAD")
    values = {**COMMON, **scenario.placeholders}
    for key in sorted(values, key=len, reverse=True):
        argv = argv.replace(key, values[key].replace("<repo>", str(clone)).replace("<head>", head))
    argv = argv.replace(" ...", "").strip()
    tokens = [t for t in shlex.split(argv) if t not in scenario.drop_flags]
    unresolved = [t for t in tokens if re.search(r"[<$]|\.\.\.", t)]
    assert not unresolved, f"{name}: unresolved placeholder(s) {unresolved} in documented argv {argv!r}"
    return tokens


def _install_all_hosts(repo: Path, env: dict[str, str]) -> None:
    subprocess.run(
        ["parrot", "sdd", "install", "--host", "claude", "--host", "codex", "--host", "google"],
        cwd=repo, env=env, check=True, capture_output=True,
    )
    _commit_push(repo, "sdd: install")


def test_install_then_every_documented_helper_invocation(
    managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, origin = foreign_repo
    env = _env(managed_home, tools_dir)
    _install_all_hosts(repo, env)
    invocations = _collect_invocations(repo)
    assert invocations, "no `parrot sdd run` invocations found — TASK-4089 rewrite missing?"
    missing = sorted({name for name, _ in invocations} - set(SCENARIOS))
    assert not missing, f"helpers documented but without a C3 scenario: {missing}"
    failures: list[str] = []
    for i, (name, documented) in enumerate(sorted(invocations)):
        scenario = SCENARIOS[name]
        clone = tmp_path / f"scenario-{i}-{name}"
        # isolated state: a private bare copy of the origin per invocation (reserve_ids pushes to it)
        private_origin = tmp_path / f"origin-{i}.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(origin), str(private_origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", "-q", str(private_origin), str(clone)], check=True, capture_output=True)
        for d in INSTALLED_DIRS:
            if (repo / d).is_dir():
                shutil.copytree(repo / d, clone / d, dirs_exist_ok=True)
        scenario.prepare(clone)
        try:
            argv = _argv_for(name, documented, scenario, clone)
        except AssertionError as exc:
            failures.append(str(exc))
            continue
        stdin = scenario.stdin(clone) if scenario.stdin else None
        result = subprocess.run(
            ["parrot", "sdd", "run", name, *argv], cwd=clone, env=env, input=stdin, capture_output=True, text=True
        )
        expected = scenario.expect_exit if argv != ["--help"] else (0, 1, 2)  # prose forms: dispatch + load only (some helpers hand-parse argv and print usage with 1)
        problems = []
        if result.returncode not in expected:
            problems.append(f"exit {result.returncode} not in {expected}")
        if "Traceback" in result.stderr:
            problems.append("traceback on stderr")
        if scenario.expect_stdout and argv != ["--help"] and scenario.expect_stdout not in result.stdout:
            problems.append(f"stdout lacks {scenario.expect_stdout!r}")
        if problems:
            failures.append(
                f"{name} {documented!r} -> {argv}: {'; '.join(problems)}\n  stdout: {result.stdout[-400:]}\n"
                f"  stderr: {result.stderr[-600:]}"
            )
    assert not failures, f"{len(failures)}/{len(invocations)} documented invocation(s) failed:\n" + "\n".join(failures)


def test_installed_hook_denies_shared_environment_write(
    managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path]
) -> None:
    """C16 (proposal step 6): the hook command as installed in the sdd-coder / sdd-worker frontmatter still
    denies a shared-environment write in a foreign repo, with only $PARROT_HOME/bin + allowlisted tools on PATH."""
    repo, _ = foreign_repo
    env = _env(managed_home, tools_dir)
    subprocess.run(["parrot", "sdd", "install", "--host", "claude"], cwd=repo, env=env, check=True, capture_output=True)
    for agent in ("sdd-coder", "sdd-worker"):
        front = (repo / ".claude/agents" / f"{agent}.md").read_text(encoding="utf-8").split("---", 2)[1]
        line = next(ln for ln in front.splitlines() if "worktree_environment --hook" in ln)
        command = line.split("command:", 1)[1].strip().strip("'")
        assert command == GUARD_LINE, command  # managed launcher on PATH → the bare form
        denied = {"cwd": str(repo), "tool_name": "Write", "tool_input": {"file_path": str(managed_home / "venv" / "x.py")}}
        result = subprocess.run(["bash", "-c", command], cwd=repo, env=env, input=json.dumps(denied), capture_output=True, text=True)
        decision = json.loads(result.stdout)["hookSpecificOutput"].get("permissionDecision")
        assert decision == "deny", f"{agent}: {result.stdout}\n{result.stderr}"
        allowed = {"cwd": str(repo), "tool_name": "Write", "tool_input": {"file_path": str(repo / "README.md")}}
        result = subprocess.run(["bash", "-c", command], cwd=repo, env=env, input=json.dumps(allowed), capture_output=True, text=True)
        assert json.loads(result.stdout)["hookSpecificOutput"].get("permissionDecision") is None, result.stdout


def test_installed_hook_project_venv_only(
    wheel: Path, tools_dir: Path, foreign_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    """C25: ai-parrot lives ONLY in ``<repo>/.venv`` (no managed launcher on PATH). The install bakes that venv's
    `parrot` into the guard hook, and the installed command still denies a shared-environment write."""
    repo, _ = foreign_repo
    venv = repo / ".venv"
    subprocess.run(["uv", "venv", str(venv), "--python", _python_for(wheel)], check=True, capture_output=True)
    subprocess.run(["uv", "pip", "install", "--python", str(venv / "bin/python"), str(wheel)], check=True, capture_output=True)
    home = tmp_path / "no-managed-home"
    (home / "env/dev").mkdir(parents=True)  # navconfig needs env/<env>/.env next to the venv's parent
    (home / "env/dev/.env").write_text("", encoding="utf-8")
    env = _env(home, tools_dir, with_launcher=False)
    # navconfig derives its root from the venv's parent: give the repo its own env tree (ignored, untracked).
    (repo / "env/dev").mkdir(parents=True)
    (repo / "env/dev/.env").write_text("", encoding="utf-8")
    subprocess.run([str(venv / "bin/parrot"), "sdd", "install", "--host", "claude"], cwd=repo, env=env, check=True, capture_output=True)
    front = (repo / ".claude/agents/sdd-worker.md").read_text(encoding="utf-8").split("---", 2)[1]
    line = next(ln for ln in front.splitlines() if "worktree_environment --hook" in ln)
    command = line.split("command:", 1)[1].strip()
    command = command[1:-1].replace("''", "'") if command.startswith("'") else command
    assert command != GUARD_LINE and command.startswith(str(venv / "bin/parrot")), command
    denied = {"cwd": str(repo), "tool_name": "Write", "tool_input": {"file_path": str(venv / "x.py")}}
    result = subprocess.run(["sh", "-c", command], cwd=repo, env=env, input=json.dumps(denied), capture_output=True, text=True)
    decision = json.loads(result.stdout)["hookSpecificOutput"].get("permissionDecision")
    assert decision == "deny", f"{result.stdout}\n{result.stderr}"


def test_c21_test_step_outcomes(managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path]) -> None:
    """rev 0.5 C21 ("C3 pins each step's outcome"): the FEAT-699 helpers behave as pinned in a foreign repo."""
    repo, _ = foreign_repo
    env = _env(managed_home, tools_dir)
    subprocess.run(["parrot", "sdd", "install", "--host", "claude"], cwd=repo, env=env, check=True, capture_output=True)
    _seed_feature(repo)
    index = f"sdd/tasks/index/{SLUG}.json"

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["parrot", "sdd", "run", *argv], cwd=repo, env=env, capture_output=True, text=True)

    fallback = run("cache_test_contract", "--spec", f"sdd/specs/{SLUG}.spec.md", "--index", index)
    assert (fallback.returncode, fallback.stdout.strip()) == (0, "fallback"), fallback.stderr
    no_section = run("cache_test_contract", "--spec", f"sdd/specs/{SLUG}-nosection.spec.md", "--index", index)
    assert no_section.returncode == 2 and "Traceback" not in no_section.stderr
    decide = run("test_report", "decide-rerun", "--index", index)
    assert (decide.returncode, decide.stdout.strip()) == (0, "rerun"), decide.stderr
    assert run("test_report", "render", "--index", index).returncode == 0
    nothing = run("select_tests", "--tier", "task", "--worktree", str(repo))
    assert nothing.returncode == 2 and "Traceback" not in nothing.stderr, nothing.stderr
    # D2: `--run` with the declared `pytest` absent from the foreign repo's PATH is a one-line refusal.
    no_runner = run(
        "select_tests", "--tier", "merge", "--base", "origin/dev", "--worktree", str(repo),
        "--task-file", "sdd/tasks/active/TASK-001-demo-task.md", "--run",
    )
    assert no_runner.returncode == 1 and "Traceback" not in no_runner.stderr, no_runner.stderr
    assert "not run" in no_runner.stderr and "test_command" in no_runner.stderr, no_runner.stderr


def test_c23_codex_install_writes_ledger_gitattributes_and_hooks(
    managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path]
) -> None:
    """rev 0.5 C23 done-when: after `parrot sdd install --host codex` the foreign repo has the block and the hooks."""
    repo, _ = foreign_repo
    env = _env(managed_home, tools_dir)
    subprocess.run(["parrot", "sdd", "install", "--host", "codex"], cwd=repo, env=env, check=True, capture_output=True)
    attributes = (repo / ".gitattributes").read_text(encoding="utf-8")
    assert "sdd/ledger/events.jsonl merge=union" in attributes
    assert "sdd/ledger/archive/*.jsonl merge=union" in attributes
    for event in ("pre-commit", "post-merge", "post-checkout", "post-rewrite"):
        assert "# >>> parrot-ledger >>>" in (repo / ".git/hooks" / event).read_text(encoding="utf-8")
