"""FEAT-847 M5 — Google (agy) sub-agent assets."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import install_sdd_integration, load_manifest, sdd_status

NEW_AGENTS = ("sdd-coder", "code-reviewer", "qa-runner")
REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS_DIR = REPO_ROOT / ".agents" / "agents"
FORBIDDEN = ("Agent(", "TaskStop", "subagent_type", 'Model="haiku"', 'Model="sonnet"')


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    block = text.split("---\n", 2)[1]
    keys: dict[str, str] = {}
    for line in block.splitlines():
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match:
            keys[match.group(1)] = match.group(2).strip()
    return keys


@pytest.fixture
def google_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    install_sdd_integration(tmp_path, hosts=("google",))
    return tmp_path


def test_manifest_includes_all_google_agents(google_repo: Path) -> None:
    targets = {e["target"]: e["hosts"] for e in load_manifest()}
    status = sdd_status(google_repo)["hosts"]["google"]
    for name in NEW_AGENTS:
        target = f".agents/agents/{name}/agent.md"
        assert targets[target] == ["google"]
        assert (google_repo / target).is_file()
        assert target in status["current"]


def test_all_agent_frontmatter() -> None:
    agents = sorted(AGENTS_DIR.glob("*/agent.md"))
    assert len(agents) >= 12
    for path in agents:
        fm = _frontmatter(path)
        assert fm.get("name") == path.parent.name
        assert fm.get("subagent") == "true"
        assert fm.get("model") == "inherit"
        assert "tools" not in fm
        assert "hooks" not in fm


@pytest.mark.parametrize("name", NEW_AGENTS)
def test_new_prompts_have_no_claude_primitives(name: str) -> None:
    text = (AGENTS_DIR / name / "agent.md").read_text(encoding="utf-8")
    for token in FORBIDDEN:
        assert token not in text, f"{name} contains {token!r}"


@pytest.mark.parametrize("name", NEW_AGENTS)
def test_wt_usage_is_self_contained(name: str) -> None:
    text = (AGENTS_DIR / name / "agent.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if '"$WT"' in line and "WT=" not in line:
            # Fresh-shell rule: a line using "$WT" must either assign it or follow an assignment in the same
            # fenced snippet; prose lines must not rely on a previous command.
            stripped = line.strip()
            assert stripped.startswith(("git -C", "cd ", "#")) or "assign" in stripped or "..." in stripped, line


AUTOPILOT = AGENTS_DIR / "sdd-autopilot" / "agent.md"


def test_agents_dispatched_by_google_autopilot_are_installed(google_repo: Path) -> None:
    """Every `agy --agent <name>` the shipped Google autopilot runs resolves to a shipped Google agent."""
    text = (google_repo / ".agents/agents/sdd-autopilot/agent.md").read_text(encoding="utf-8")
    names = set(re.findall(r"agy --agent ([a-z][a-z-]*)", text))
    assert {"code-reviewer", "qa-runner"} <= names
    missing = sorted(n for n in names if not (google_repo / ".agents/agents" / n / "agent.md").is_file())
    assert not missing, missing


@pytest.mark.parametrize("token", ("claude --agent", "claude -p", "--setting-sources", "--mode auto"))
def test_google_autopilot_has_no_claude_cli(token: str) -> None:
    """The Google autopilot shells out to `agy` only, without Claude-only or account-gated flags."""
    assert token not in AUTOPILOT.read_text(encoding="utf-8")


def test_google_autopilot_stages_run_unattended() -> None:
    """The worker stage uses the guarded Google launcher; every `agy` stage call skips permission prompts."""
    text = AUTOPILOT.read_text(encoding="utf-8")
    assert 'parrot sdd launch worker "$FEAT_ID" --host google' in text
    assert "PARROT_SDD_AGY_UNATTENDED=1" in text
    lines = text.splitlines()
    calls = [i for i, line in enumerate(lines) if re.match(r"\s*\"?agy (--agent|--dangerously|-p)", line)]
    assert len(calls) >= 6
    for i in calls:
        window = " ".join(lines[i : i + 2])
        assert "--dangerously-skip-permissions" in window, lines[i]


def test_packaged_google_autopilot_matches_source() -> None:
    """The wheel copy is regenerated from `.agents/agents/sdd-autopilot/agent.md`."""
    packaged = REPO_ROOT / "packages/ai-parrot/src/parrot/sdd/_assets/agents/agents/sdd-autopilot/agent.md"
    assert packaged.read_text(encoding="utf-8") == AUTOPILOT.read_text(encoding="utf-8")
