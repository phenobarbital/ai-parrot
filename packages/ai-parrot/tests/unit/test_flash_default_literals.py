"""FEAT-798: the core/server source files swept by TASK-5151 no longer name a retired 2.5 id."""

import inspect
import re
from pathlib import Path

import pytest

from parrot.memory.episodic.reflection import ReflectionEngine
from parrot.setup.providers.google import GoogleWizard

REPO_ROOT = Path(__file__).resolve().parents[4]
RETIRED = re.compile(r"gemini-2\.5-(?:pro|flash)(?![-\w])")
SWEPT_FILES = (
    "packages/ai-parrot/src/parrot/conf.py",
    "packages/ai-parrot/src/parrot/bots/base.py",
    "packages/ai-parrot/src/parrot/bots/voice.py",
    "packages/ai-parrot/src/parrot/bots/scraper/scraper.py",
    "packages/ai-parrot/src/parrot/bots/factory/builders/rag_builder.py",
    "packages/ai-parrot/src/parrot/bots/factory/builders/tool_agent_builder.py",
    "packages/ai-parrot/src/parrot/bots/mixins/model_switching.py",
    "packages/ai-parrot/src/parrot/bots/abstract.py",
    "packages/ai-parrot/src/parrot/interfaces/images/plugins/classifybase.py",
    "packages/ai-parrot/src/parrot/interfaces/images/plugins/classify.py",
    "packages/ai-parrot/src/parrot/interfaces/images/plugins/analisys.py",
    "packages/ai-parrot/src/parrot/memory/episodic/reflection.py",
    "packages/ai-parrot/src/parrot/setup/providers/google.py",
    "packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py",
    "packages/ai-parrot-server/src/parrot/handlers/google_generation.py",
    "packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py",
)


@pytest.mark.parametrize("rel_path", SWEPT_FILES)
def test_no_retired_gemini_literal(rel_path: str) -> None:
    """Verify a swept source file contains no retired whole model ID."""
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    hits = [n for n, line in enumerate(text.splitlines(), 1) if RETIRED.search(line)]
    assert not hits, f"{rel_path}: retired gemini-2.5 id on lines {hits}"


def test_reflection_and_wizard_defaults() -> None:
    """The two constructor-level defaults are the flash successor."""
    reflection_default = inspect.signature(ReflectionEngine.__init__).parameters["model"].default

    assert reflection_default == "gemini-3.8-flash"
    assert GoogleWizard.default_model == "gemini-3.8-flash"
