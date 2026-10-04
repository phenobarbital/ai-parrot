"""FEAT-595: prefilter decision-equivalence and lazy-import guarantees for the wiki hook.

The PreToolUse hook now rejects non-search payloads with stdlib-only
predicates before it loads the pydantic project config. These tests pin
that the reordering never changes a decision, and that importing the hook
runtime stays light.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.wiki.claude_code import hook
from parrot.knowledge.wiki.project import WikiProjectConfig

#: This checkout's sources, so a subprocess never imports another checkout's ``parrot``.
_SRC_ROOTS = [str(Path(__file__).resolve().parents[3] / "src")]

#: Modules the hook runtime must not import at module load (FEAT-595).
_HEAVY_MODULES = (
    "pydantic",
    "click",
    "parrot.knowledge.wiki.project",
    "parrot.knowledge.wiki.repo_scan",
    "parrot.knowledge.wiki.cli",
    "parrot.knowledge.wiki.claude_code.installer",
)


def _build_project(root: Path) -> None:
    """Built sqlite fixture: ``.git`` plus an (empty) ``.parrot/wiki/wiki.db``."""
    (root / ".git").mkdir(parents=True)
    wiki_dir = root / ".parrot" / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "wiki.db").write_bytes(b"")


def _unthrottled_config() -> WikiProjectConfig:
    """Default project config with throttling disabled, so only the decision logic is tested."""
    config = WikiProjectConfig()
    config.claude.nudge_cooldown_seconds = 0
    return config


def _payload(tool_name: str, tool_input: object = None, event: str | None = "PreToolUse") -> dict:
    payload: dict = {"tool_name": tool_name, "tool_input": tool_input if tool_input is not None else {}}
    if event is not None:
        payload["hook_event_name"] = event
    return payload


_DECISIONS = [
    pytest.param(_payload("Grep", {"pattern": "foo"}), True, id="grep"),
    pytest.param(_payload("Glob", {"pattern": "**/*.py"}), True, id="glob"),
    pytest.param(_payload("Read", {"file_path": "src/app.py"}), True, id="read-source"),
    pytest.param(_payload("Read", {"file_path": "docs/guide.md"}), True, id="read-doc"),
    pytest.param(_payload("Read", {"file_path": "logo.png"}), False, id="read-image"),
    pytest.param(_payload("Read", {}), False, id="read-no-path"),
    pytest.param(_payload("Bash", {"command": "rg foo src"}), True, id="bash-rg"),
    pytest.param(_payload("Bash", {"command": "git status"}), False, id="bash-git"),
    pytest.param(_payload("Bash", {"command": "cat README.md"}), True, id="bash-cat-doc"),
    pytest.param(_payload("Bash", {"command": "cat /etc/hosts"}), False, id="bash-cat-other"),
    pytest.param(_payload("Bash", {"command": "FOO=1 grep -n x a.py"}), True, id="bash-env-grep"),
    pytest.param(_payload("Bash", {"command": "ls -la && find . -name x"}), True, id="bash-chain-find"),
    pytest.param(_payload("Bash", {}), False, id="bash-no-command"),
    pytest.param(_payload("Write", {"file_path": "a.py"}), False, id="tool-not-configured"),
    pytest.param(_payload("Grep", {"pattern": "x"}, event="PostToolUse"), False, id="post-tool-use"),
    pytest.param(_payload("Grep", {"pattern": "x"}, event=None), True, id="event-missing"),
    pytest.param(_payload("Read", ["not", "a", "dict"]), False, id="read-input-not-dict"),
    pytest.param(_payload("Grep", "not-a-dict"), True, id="grep-input-not-dict"),
]


@pytest.mark.parametrize("payload, expect_nudge", _DECISIONS)
def test_build_nudge_decisions(tmp_path: Path, payload: dict, expect_nudge: bool) -> None:
    """build_nudge keeps the pre-FEAT-595 decision for every payload shape (AC5)."""
    _build_project(tmp_path)
    result = hook.build_nudge(payload, root=tmp_path, config=_unthrottled_config(), now=1000.0)
    assert (result is not None) == expect_nudge
    if expect_nudge:
        assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert result["hookSpecificOutput"]["additionalContext"] == hook.NUDGE_TEXT


@pytest.mark.parametrize("payload, expect_nudge", _DECISIONS)
def test_prefilter_only_rejects_what_build_nudge_rejects(payload: dict, expect_nudge: bool) -> None:
    """A prefilter rejection is never a payload that would otherwise nudge."""
    if hook._prefilter_rejects(payload):
        assert not expect_nudge


def test_prefilter_never_rejects_configurable_tools() -> None:
    """Grep/Glob and arbitrary tool names pass the prefilter; the config decides them."""
    for name in ("Grep", "Glob", "Write", "SomeFutureTool", ""):
        assert not hook._prefilter_rejects(_payload(name, {}))


def test_config_listed_custom_tool_still_nudges(tmp_path: Path) -> None:
    """A tool only the config lists is not dropped by the prefilter."""
    _build_project(tmp_path)
    config = _unthrottled_config()
    config.claude.nudge_tools = [*config.claude.nudge_tools, "Write"]
    assert hook.build_nudge(_payload("Write", {}), root=tmp_path, config=config, now=1.0) is not None


def test_unbuilt_repo_never_nudges(tmp_path: Path) -> None:
    """A repo without a retrieval plane yields None for a search payload."""
    (tmp_path / ".git").mkdir()
    payload = _payload("Grep", {"pattern": "x"})
    assert hook.build_nudge(payload, root=tmp_path, config=_unthrottled_config(), now=1.0) is None


def test_rejected_payload_does_not_consume_throttle_window(tmp_path: Path) -> None:
    """Throttling stays last: a rejected payload never claims the cooldown window."""
    _build_project(tmp_path)
    config = WikiProjectConfig()
    assert hook.build_nudge(_payload("Bash", {"command": "git log"}), root=tmp_path, config=config, now=5.0) is None
    assert hook.build_nudge(_payload("Grep", {"pattern": "x"}), root=tmp_path, config=config, now=5.0) is not None
    assert hook.build_nudge(_payload("Grep", {"pattern": "x"}), root=tmp_path, config=config, now=6.0) is None


def test_suffix_identity() -> None:
    """repo_scan re-exports the very same frozensets (AC6)."""
    from parrot.knowledge.wiki import file_suffixes, repo_scan

    assert repo_scan.CODE_SUFFIXES is file_suffixes.CODE_SUFFIXES
    assert repo_scan.DOC_SUFFIXES is file_suffixes.DOC_SUFFIXES
    assert ".py" in file_suffixes.CODE_SUFFIXES
    assert ".md" in file_suffixes.DOC_SUFFIXES


def test_lazy_package_exports() -> None:
    """Public installer names still resolve through the package; unknown names raise AttributeError."""
    import parrot.knowledge.wiki.claude_code as claude_code
    from parrot.knowledge.wiki.claude_code import installer

    for name in claude_code.__all__:
        assert getattr(claude_code, name) is getattr(installer, name)
    from parrot.knowledge.wiki.claude_code import install_claude_integration

    assert install_claude_integration is installer.install_claude_integration
    with pytest.raises(AttributeError):
        claude_code.does_not_exist  # noqa: B018


def _fresh_process_modules(code: str) -> set[str]:
    """Run ``code`` in a fresh interpreter importing this checkout; return its ``sys.modules`` keys."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([*_SRC_ROOTS, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    script = f"{code}\nimport json, sys\nprint(json.dumps(sorted(sys.modules)))"
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, timeout=30, check=True)
    return set(json.loads(result.stdout.decode().strip().splitlines()[-1]))


def test_hook_import_is_light() -> None:
    """Importing claude_code.hook in a fresh process loads no heavy module."""
    modules = _fresh_process_modules("import parrot.knowledge.wiki.claude_code.hook")
    assert not modules.intersection(_HEAVY_MODULES), sorted(modules.intersection(_HEAVY_MODULES))


def test_rejected_payload_run_stays_light() -> None:
    """A full hook run on a non-search payload never loads the pydantic config."""
    code = (
        "import io\n"
        "from parrot.knowledge.wiki.claude_code.hook import run_pre_tool_use_hook\n"
        "out = io.StringIO()\n"
        'rc = run_pre_tool_use_hook(io.StringIO(\'{"tool_name": "Bash", '
        '"tool_input": {"command": "git status"}}\'), out)\n'
        "assert rc == 0 and out.getvalue() == ''"
    )
    modules = _fresh_process_modules(code)
    assert not modules.intersection(_HEAVY_MODULES), sorted(modules.intersection(_HEAVY_MODULES))
