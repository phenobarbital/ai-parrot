"""FEAT-798 (spec AC-10): docs/, examples/ and plugins/ do not present retired gemini-2.5 ids."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED = ("docs", "examples", "plugins")
SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".example", ".toml"}
# The migration guide names the retired ids on purpose.
EXCLUDED = {"docs/migration/gemini-2-5-retirement.md"}
RETIRED = re.compile(
    r"gemini-2\.5-(?:pro|flash)(?![-\w])|gemini-2\.5-flash-native-audio|gemini-2\.5-(?:flash|pro)-preview-tts"
)


def test_no_retired_gemini_id_in_docs_examples_plugins() -> None:
    """Report every retired Gemini identifier exposed by a user-facing surface."""
    hits: list[str] = []
    for top in SCANNED:
        for path in (REPO_ROOT / top).rglob("*"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if not path.is_file() or rel in EXCLUDED or "node_modules" in path.parts:
                continue
            if path.suffix not in SUFFIXES and not path.name.endswith(".env.example"):
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                if RETIRED.search(line):
                    hits.append(f"{rel}:{lineno}")
    assert not hits, "retired gemini-2.5 ids found:\n" + "\n".join(hits)
