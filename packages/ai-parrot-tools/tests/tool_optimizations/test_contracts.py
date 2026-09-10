"""Unit tests for delegation-contract validation (TASK-3083, FEAT-543)."""

import asyncio
import json
import subprocess

import pytest

from parrot_tools.tool_optimizations.contracts import (
    ALLOWED_VALIDATION_PROGRAMS,
    CodeBlock,
    ContractError,
    find_placeholders,
    parse_task_file,
    render_prompt_sections,
    validate_contract,
)
from parrot_tools.tool_optimizations.models import WriterLimits
from parrot_tools.tool_optimizations.policy import OptimizationPolicy

from .fixtures import make_repo_with_target, make_valid_task, sha256_of


def _policy(repo):
    """Build a policy rooted at the fixture repository."""
    return OptimizationPolicy(repo_root=repo)


async def _validate(repo, task, **kwargs):
    """Validate a fixture TASK file by its repo-relative path."""
    return await validate_contract(_policy(repo), task.relative_to(repo).as_posix(), **kwargs)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
async def test_valid_task_validates(tmp_path):
    """The canonical fixture is eligible and reports accurate state."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    contract = await _validate(repo, task)

    assert contract.packet.task_id == "TASK-9999"
    assert set(contract.blocks) == {"impl-greeter", "impl-init"}
    assert contract.targets_state["pkg/greeter.py"] is None
    assert contract.targets_state["pkg/__init__.py"] == sha256_of(repo / "pkg" / "__init__.py")
    assert len(contract.references) == 1
    assert contract.references[0].content.startswith('"""Package."""')
    assert contract.task_path == "sdd/tasks/active/TASK-9999-greeter.md"


async def test_packet_identity_is_stable_and_context_bytes_match_formula(tmp_path):
    """packet_sha256 is reproducible and context_bytes follows the documented sum."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)

    first = await _validate(repo, task)
    second = await _validate(repo, task)
    assert first.packet_sha256 == second.packet_sha256
    assert len(first.packet_sha256) == 64

    from parrot_tools.tool_optimizations.policy import measure_json_bytes

    expected = (
        measure_json_bytes(first.packet.model_dump(mode="json"))
        + sum(len(block.text.encode("utf-8")) for block in first.blocks.values())
        + sum(len(ref.content.encode("utf-8")) for ref in first.references)
    )
    assert first.context_bytes == expected


# --------------------------------------------------------------------------- #
# Error codes — one test per documented code
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "mutator,code",
    [
        (lambda t: t.replace("## Delegation Contract", "## Something"), "no_delegation_section"),
        (lambda t: t + "\n## Delegation Contract\n\n```json\n{}\n```\n", "duplicate_delegation_section"),
        (lambda t: t.replace('"schema_version": 1', '"schema_version": 2'), "invalid_packet"),
        (lambda t: t.replace('"design_complete": true', '"design_complete": false'), "invalid_packet"),
        (lambda t: t.replace('"design_complete": true', '"design_complete": true, "extra": 1'), "invalid_packet"),
        (lambda t: t.replace('"impl-init"\n      ]', '"impl-missing"\n      ]'), "missing_block"),
        (lambda t: t.replace('    return f"hello {name}"', "    ..."), "placeholder_code"),
        (
            lambda t: t.replace('"tests/test_greeter.py",\n        "-q"', '"-rf",\n        "/"').replace(
                '"pytest"', '"rm"'
            ),
            "invalid_validation_command",
        ),
        (lambda t: t.replace('"task_id": "TASK-9999"', '"task_id": "NOPE-1"'), "invalid_packet"),
    ],
)
async def test_error_codes(tmp_path, mutator, code):
    """Each documented failure mode raises exactly its own code."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    task.write_text(mutator(task.read_text()))

    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == code


async def test_no_packet_block_and_duplicate_packet_block(tmp_path):
    """The delegation section needs exactly one json block."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    original = task.read_text()

    stripped = original.split("## Delegation Contract")[0] + "## Delegation Contract\n\nno block here\n"
    task.write_text(stripped)
    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == "no_packet_block"

    packet_block = "```json\n{}\n```"
    task.write_text(original.replace("## Implementation", packet_block + "\n\n## Implementation"))
    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == "duplicate_packet_block"


async def test_invalid_packet_json(tmp_path):
    """A malformed JSON packet is distinguished from a schema violation."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    task.write_text(task.read_text().replace('"schema_version": 1,', '"schema_version": 1,,'))
    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == "invalid_packet_json"


async def test_duplicate_block_id(tmp_path):
    """Two blocks may not share an id."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    task.write_text(task.read_text() + "\n```python id=impl-greeter\nx = 1\n```\n")
    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == "duplicate_block_id"


async def test_task_not_found_and_outside_root(tmp_path):
    """A missing or escaping TASK path is refused before parsing."""
    repo = make_repo_with_target(tmp_path)
    with pytest.raises(ContractError) as info:
        await validate_contract(_policy(repo), "sdd/tasks/active/nope.md")
    assert info.value.code == "task_not_found"

    with pytest.raises(ContractError) as info:
        await validate_contract(_policy(repo), "../outside.md")
    assert info.value.code == "task_outside_root"


async def test_target_exists_for_create_and_missing_for_modify(tmp_path):
    """CREATE requires absence; MODIFY requires presence."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    (repo / "pkg" / "greeter.py").write_text("already here\n")
    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == "target_exists_for_create"

    (repo / "pkg" / "greeter.py").unlink()
    (repo / "pkg" / "__init__.py").unlink()
    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == "target_missing_for_modify"


async def test_underspecified_create(tmp_path):
    """A CREATE whose block carries no path= tag cannot be delegated."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    task.write_text(
        task.read_text().replace("```python id=impl-greeter path=pkg/greeter.py", "```python id=impl-greeter")
    )
    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == "underspecified_create"


async def test_stale_target_and_reference(tmp_path):
    """A file edited after the packet was written invalidates the contract."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    (repo / "pkg" / "__init__.py").write_text("changed\n")

    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code in {"stale_target", "stale_reference"}
    assert "current" in info.value.details
    assert info.value.details["expected"] != info.value.details["current"]


async def test_scope_path_invalid(tmp_path):
    """A target outside the root, or a secret file, is refused."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    task.write_text(task.read_text().replace('"path": "pkg/greeter.py"', '"path": "../escape.py"'))
    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == "scope_path_invalid"


async def test_reference_range_invalid(tmp_path):
    """A reference range past EOF is reported, not silently clamped."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    task.write_text(
        task.read_text().replace('"start_line": 1,\n      "end_line": 3', '"start_line": 900,\n      "end_line": 905')
    )
    with pytest.raises(ContractError) as info:
        await _validate(repo, task)
    assert info.value.code == "reference_range_invalid"


async def test_context_budget_exceeded_before_expensive_work(tmp_path):
    """The blocks alone can blow the budget, and that is detected early."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    with pytest.raises(ContractError) as info:
        await _validate(repo, task, limits_override=WriterLimits(max_context_bytes=1))
    assert info.value.code == "context_budget_exceeded"
    assert info.value.details["max_context_bytes"] == 1


async def test_packet_too_large(tmp_path):
    """An oversized TASK file is refused before it is parsed."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    with pytest.raises(ContractError) as info:
        await _validate(repo, task, limits_override=WriterLimits(max_packet_bytes=10))
    assert info.value.code == "packet_too_large"


# --------------------------------------------------------------------------- #
# Parser behaviour
# --------------------------------------------------------------------------- #
def test_nested_shorter_fence_is_preserved_literally():
    """A shorter fence inside a longer-fenced block is content, not a close."""
    text = (
        "## Delegation Contract\n\n"
        "```json\n{}\n```\n\n"
        "````markdown id=impl-doc\n"
        "Here is an example:\n"
        "```python\n"
        "x = 1\n"
        "```\n"
        "done\n"
        "````\n"
    )
    packet_json, blocks = parse_task_file(text)
    assert packet_json == "{}"
    assert "```python" in blocks["impl-doc"].text
    assert blocks["impl-doc"].text.strip().endswith("done")


def test_placeholder_rule_is_line_anchored():
    """A bare `...` line is a placeholder; `"..."` inside an expression is not."""
    bad = CodeBlock(block_id="b", language="python", text="def f():\n    ...\n", start_line=1)
    good = CodeBlock(block_id="b", language="python", text='x = "..."\ny = 1\n', start_line=1)
    assert find_placeholders(bad)[0][1] == "bare_ellipsis"
    assert find_placeholders(good) == []

    for snippet, expected in [
        ("# TODO: later\n", "todo"),
        ("# FIXME\n", "fixme"),
        ("raise NotImplementedError\n", "not_implemented"),
        ("value = <the thing>\n", "angle_placeholder"),
    ]:
        block = CodeBlock(block_id="b", language="python", text=snippet, start_line=1)
        assert find_placeholders(block)[0][1] == expected


def test_blocks_outside_the_delegation_section_are_still_collected():
    """Implementation blocks live anywhere in the file; only the packet is scoped."""
    text = "## Delegation Contract\n\n```json\n{}\n```\n\n## Elsewhere\n\n```python id=impl-x\ny = 2\n```\n"
    packet_json, blocks = parse_task_file(text)
    assert packet_json == "{}"
    assert blocks["impl-x"].text == "y = 2"
    assert blocks["impl-x"].language == "python"


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #
def test_validation_program_allow_list_is_narrow():
    """Only well-known validation programs may appear in a packet."""
    assert ALLOWED_VALIDATION_PROGRAMS == {"pytest", "ruff", "black", "mypy", "python", "python3"}
    assert "rm" not in ALLOWED_VALIDATION_PROGRAMS
    assert "bash" not in ALLOWED_VALIDATION_PROGRAMS


async def test_no_subprocess_ever(tmp_path, monkeypatch):
    """Validation never executes anything, including validation_commands."""
    monkeypatch.setattr(asyncio, "create_subprocess_exec", lambda *a, **k: pytest.fail("spawned a process"))
    monkeypatch.setattr(asyncio, "create_subprocess_shell", lambda *a, **k: pytest.fail("spawned a shell"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("spawned a process"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("spawned a process"))

    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    contract = await _validate(repo, task)
    assert contract.packet.validation_commands == [["pytest", "tests/test_greeter.py", "-q"]]


# --------------------------------------------------------------------------- #
# Prompt rendering
# --------------------------------------------------------------------------- #
async def test_render_prompt_sections_snapshot(tmp_path):
    """The rendered prompt is deterministic and contains only approved content."""
    repo = make_repo_with_target(tmp_path)
    task = make_valid_task(repo)
    contract = await _validate(repo, task)
    sections = render_prompt_sections(contract)

    assert set(sections) == {"packet", "references", "blocks", "acceptance"}
    assert sections["packet"].startswith("## Packet\n\n```json\n")
    assert json.loads(sections["packet"].split("```json\n")[1].split("\n```")[0])["task_id"] == "TASK-9999"

    reference = contract.references[0]
    assert f"### pkg/__init__.py @ {reference.slice.sha256[:12]} lines 1-3 — existing exports" in sections["references"]
    assert sections["blocks"].index("### impl-greeter") < sections["blocks"].index("### impl-init")
    assert "(file: pkg/greeter.py)" in sections["blocks"]
    assert sections["acceptance"] == "## Acceptance criteria\n\n- pytest tests/test_greeter.py passes"

    assert render_prompt_sections(contract) == sections
