"""FEAT-798 (spec AC-10): docs/, examples/ and plugins/ do not present retired gemini-2.5 ids or members."""

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
# Retired GoogleModel member names (removed in TASK-5155). GEMINI_2_5_FLASH_LITE and
# GEMINI_2_5_FLASH_IMAGE are still supported and must not match.
RETIRED_MEMBERS = re.compile(r"\bGEMINI_2_5_(?:FLASH(?:_PREVIEW|_TTS)?|PRO(?:_TTS)?)\b")


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
                if RETIRED.search(line) or RETIRED_MEMBERS.search(line):
                    hits.append(f"{rel}:{lineno}")
    assert not hits, "retired gemini-2.5 ids or members found:\n" + "\n".join(hits)


def test_retired_member_pattern_spares_supported_members() -> None:
    """The member guard flags removed names but not the still-supported 2.5 lite/image members."""
    for name in ("GEMINI_2_5_FLASH", "GEMINI_2_5_FLASH_PREVIEW", "GEMINI_2_5_PRO", "GEMINI_2_5_FLASH_TTS",
                 "GEMINI_2_5_PRO_TTS"):
        assert RETIRED_MEMBERS.search(f"model=GoogleModel.{name},"), name
    for name in ("GEMINI_2_5_FLASH_LITE", "GEMINI_2_5_FLASH_LITE_PREVIEW", "GEMINI_2_5_FLASH_IMAGE",
                 "GEMINI_2_5_FLASH_IMAGE_PREVIEW"):
        assert not RETIRED_MEMBERS.search(f"model=GoogleModel.{name},"), name
