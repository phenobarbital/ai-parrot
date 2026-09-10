"""Tests for the SDD delegation workflow documents (TASK-3090, FEAT-543).

These assert *meaning parity* between the Claude Code commands and the Codex
skills — shared key phrases and the review-before-apply ordering — rather
than identical prose, which the two hosts deliberately do not share.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

from parrot_tools.tool_optimizations.contracts import ContractError, extract_packet, parse_task_file, validate_contract
from parrot_tools.tool_optimizations.policy import OptimizationPolicy

#: tests/tool_optimizations -> tests -> ai-parrot-tools -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]

TASK_TEMPLATE = REPO_ROOT / "sdd" / "templates" / "task.md"
SPEC_TEMPLATE = REPO_ROOT / "sdd" / "templates" / "spec.md"
WORKER = REPO_ROOT / ".claude" / "agents" / "sdd-worker.md"

#: (Claude command, Codex skill) pairs that must agree in meaning.
PAIRS = [
    (REPO_ROOT / ".claude" / "commands" / "sdd-spec.md", REPO_ROOT / ".agents" / "skills" / "sdd-spec" / "SKILL.md"),
    (REPO_ROOT / ".claude" / "commands" / "sdd-task.md", REPO_ROOT / ".agents" / "skills" / "sdd-task" / "SKILL.md"),
    (REPO_ROOT / ".claude" / "commands" / "sdd-start.md", REPO_ROOT / ".agents" / "skills" / "sdd-start" / "SKILL.md"),
]


def _read(path: Path) -> str:
    """Read a workflow document, failing loudly when it is missing."""
    assert path.is_file(), f"missing workflow document: {path}"
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The template's example packet
# --------------------------------------------------------------------------- #
def test_template_packet_is_rejected_while_placeholders_remain():
    """The shipped example must not validate until real hashes are filled in.

    This is the safety net: a copy-pasted packet with `<sha256 ...>` left in
    is refused rather than silently delegated.
    """
    packet_json, blocks = parse_task_file(_read(TASK_TEMPLATE))
    with pytest.raises(ContractError) as info:
        extract_packet(packet_json)
    assert info.value.code == "invalid_packet"
    assert {"impl-greeter", "impl-init"} <= set(blocks)


def test_template_packet_validates_once_hashes_are_real(tmp_path):
    """With real digests substituted, the shipped example is a valid packet."""
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "sdd" / "specs").mkdir(parents=True)
    (repo / "sdd" / "specs" / "example.spec.md").write_text("# spec\n")
    init = repo / "pkg" / "__init__.py"
    init.write_text('"""Package."""\n\n__all__ = []\n')
    digest = hashlib.sha256(init.read_bytes()).hexdigest()

    text = _read(TASK_TEMPLATE)
    text = re.sub(r'"<sha256[^"]*>"', f'"{digest}"', text)
    text = text.replace('"task_id": "TASK-<NNN>"', '"task_id": "TASK-9999"')
    text = text.replace('"spec_path": "sdd/specs/<feature>.spec.md"', '"spec_path": "sdd/specs/example.spec.md"')

    task_file = repo / "sdd" / "tasks" / "active" / "TASK-9999-example.md"
    task_file.parent.mkdir(parents=True)
    task_file.write_text(text)

    contract = validate_contract  # imported for clarity of the call below
    import asyncio

    validated = asyncio.run(contract(OptimizationPolicy(repo_root=repo), task_file.relative_to(repo).as_posix()))
    assert validated.packet.design_complete is True
    assert set(validated.blocks) == {"impl-greeter", "impl-init"}
    assert validated.targets_state["pkg/greeter.py"] is None


def test_template_documents_removal_for_ineligible_tasks():
    """The default route must be stated plainly, so authors do not over-apply it."""
    text = _read(TASK_TEMPLATE)
    assert "Remove this section entirely if the task is not delegation-eligible" in text
    assert "OPTIONAL" in text
    assert "sha256sum" in text


def test_spec_template_has_the_eligibility_table():
    """Spec authors record eligibility per module, with a reason when not."""
    text = _read(SPEC_TEMPLATE)
    assert "Delegation-eligible modules" in text
    assert "Why not (if no)" in text
    assert "Architecture decisions stay with the thinking model" in text


# --------------------------------------------------------------------------- #
# Host parity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("command,skill", PAIRS, ids=lambda p: p.parent.name + "/" + p.name)
def test_command_and_skill_exist(command, skill):
    """Both hosts must carry the workflow."""
    assert command.is_file() and skill.is_file()


@pytest.mark.parametrize("pair", PAIRS, ids=lambda pair: pair[0].stem)
def test_delegation_key_phrases_are_present_in_both_hosts(pair):
    """Meaning parity: the same commitments appear for Claude and Codex."""
    command, skill = pair
    stem = command.stem
    if stem == "sdd-spec":
        required = ["delegation-eligible"]
    elif stem == "sdd-task":
        required = ["Delegation Contract", "sha256sum", "design_complete", "placeholder"]
    else:
        required = ["writer_generate", "writer_apply", "source_read", "review", "never silently invokes another coder"]

    for document in (command, skill):
        text = _read(document).lower()
        for phrase in required:
            assert phrase.lower() in text, f"{document} is missing {phrase!r}"


@pytest.mark.parametrize(
    "document",
    [PAIRS[2][0], PAIRS[2][1], WORKER],
    ids=["claude-command", "codex-skill", "sdd-worker"],
)
def test_review_happens_before_apply(document):
    """Generation, review and application must be documented in that order."""
    text = _read(document)
    generate = text.index("writer_generate")
    apply_at = text.index("writer_apply")
    read_at = text.index("source_read")

    assert generate < read_at < apply_at, f"{document}: review must sit between generate and apply"
    assert "not fully read" in text or "fully read" in text
    assert "never runs tests" in text


def test_sdd_worker_has_the_delegated_step_and_checklist_line():
    """The autonomous worker gains the same branch and a verification line."""
    text = _read(WORKER)
    assert "### b2) Delegated implementation" in text
    assert "□ Delegated patch hunks were all reviewed before writer_apply?" in text
    # Ordering: the delegated step sits between contract verification and implementation.
    assert text.index("### b) Verify Codebase Contract") < text.index("### b2) Delegated implementation")
    assert text.index("### b2) Delegated implementation") < text.index("### c) Implement")


# --------------------------------------------------------------------------- #
# Legacy route and SDD-state ownership
# --------------------------------------------------------------------------- #
async def test_legacy_task_without_a_contract_is_simply_ineligible(tmp_path):
    """A task with no packet is reported as such — never auto-converted."""
    repo = tmp_path / "repo"
    (repo / "sdd" / "tasks" / "active").mkdir(parents=True)
    legacy = repo / "sdd" / "tasks" / "active" / "TASK-0001-legacy.md"
    legacy.write_text("# TASK-0001: Legacy\n\n## Scope\n\nDo the thing.\n")

    with pytest.raises(ContractError) as info:
        await validate_contract(OptimizationPolicy(repo_root=repo), legacy.relative_to(repo).as_posix())
    assert info.value.code == "no_delegation_section"


@pytest.mark.parametrize(
    "document", [PAIRS[2][0], PAIRS[2][1], WORKER], ids=["claude-command", "codex-skill", "worker"]
)
def test_documents_state_that_sdd_files_are_never_delegated(document):
    """SDD state mutation always stays with the thinking model."""
    text = _read(document)
    assert "never edited by the writer" in text or "never delegated" in text


@pytest.mark.parametrize(
    "document", [PAIRS[2][0], PAIRS[2][1], WORKER], ids=["claude-command", "codex-skill", "worker"]
)
def test_documents_forbid_substituting_another_coder(document):
    """Delegation failure must fall back to the thinking model, not another tool."""
    assert "never silently invokes another coder" in _read(document).lower()
