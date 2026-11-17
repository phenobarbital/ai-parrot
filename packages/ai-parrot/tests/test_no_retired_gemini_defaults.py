"""FEAT-798 (spec AC-1, codex S7): no retired gemini-2.5 id in shipped source."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN_ROOTS = tuple(sorted((REPO_ROOT / "packages").glob("*/src"))) + (
    REPO_ROOT / "packages" / "ai-parrot-server" / "ui" / "src",
)
SUFFIXES = {".py", ".ts", ".svelte", ".json"}
RETIRED_LITERALS = (
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
    "gemini-2.5-flash-native-audio",
    "gemini-2.5-computer-use",
)
RETIRED = re.compile(
    r"gemini-2\.5-(?:pro|flash)(?![-\w])|gemini-2\.5-(?:flash|pro)-preview-tts|"
    r"gemini-2\.5-flash-native-audio|gemini-2\.5-computer-use"
)
GUARD_EXCLUDED = {
    "packages/ai-parrot/src/parrot/clients/base.py",  # historical comments; file is a non-goal
    "packages/ai-parrot-server/ui/src/lib/ui/components/LlmModelPicker.svelte",  # documentation example
}


def test_no_retired_gemini_literal_in_src() -> None:
    """Shipped source contains no exact retired Gemini 2.5 model id."""
    hits: list[str] = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            if "build" in path.parts or "node_modules" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in GUARD_EXCLUDED:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if RETIRED.search(line):
                    hits.append(f"{rel}:{lineno}: {line.strip()}")
    assert not hits, "retired gemini-2.5 ids in src:\n" + "\n".join(hits)
