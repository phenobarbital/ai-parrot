"""FEAT-722: worktree docs describe native-artifact synchronization consistently."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUBAGENT = "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data"
WORKER_FILES = [
    ".claude/agents/sdd-worker.md",
    ".agent/agents/sdd-worker/agent.md",
    f"{SUBAGENT}/sdd-worker.md",
]
RULE_FILES = [
    ".claude/rules/worktree-management.md",
    ".agent/skills/worktree-management/SKILL.md",
]
REQUIRED_STRINGS = (
    "[tool.parrot.worktree]",
    "cd packages/ai-parrot && python setup.py build_ext --inplace",
    "make -C packages/navrules build-rust-wheel",
)
WORKER_NOTICE = """The command also copies the declared native build artifacts into the worktree —
the declaration lives in the root `pyproject.toml` under `[tool.parrot.worktree]`;
`parrot.utils.types` and the other compiled extensions are gitignored, so without this
step `import parrot.utils` fails inside the tree (FEAT-722). It builds a missing one
automatically and prints a `warning:` line on **stderr** if it could not; only then run
the build yourself (`cd packages/ai-parrot && python setup.py build_ext --inplace`, or
`make -C packages/navrules build-rust-wheel`). Never hand-copy `.so` files, and never
`maturin develop` — it rewrites the shared `.venv`."""


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", WORKER_FILES + RULE_FILES)
def test_mentions_the_declaration(rel: str) -> None:
    text = _text(rel)
    for required in REQUIRED_STRINGS:
        assert required in text, (rel, required)


@pytest.mark.parametrize("rel", WORKER_FILES + RULE_FILES)
def test_never_recommends_maturin_develop(rel: str) -> None:
    text = _text(rel).lower()
    offset = 0
    while True:
        occurrence = text.find("maturin develop", offset)
        if occurrence < 0:
            break
        context = text[max(0, occurrence - 120) : occurrence + 120]
        assert "never" in context or "do not" in context, (rel, context)
        offset = occurrence + len("maturin develop")


def test_worker_twins_carry_the_same_sentence() -> None:
    notices = [_text(rel).count(WORKER_NOTICE) for rel in WORKER_FILES]
    assert notices == [1, 1, 1]
