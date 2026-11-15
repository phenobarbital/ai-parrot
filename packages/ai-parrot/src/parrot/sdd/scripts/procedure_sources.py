"""Stdlib-only source discovery shared by procedure builds and hooks."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SKILL_DIRECTORIES = ("skills",)


def skill_directories(root: Path) -> list[str]:
    """Read repository-relative skill directories, using defaults on invalid config."""
    try:
        config = json.loads((root / "sdd/config.json").read_text(encoding="utf-8"))
        directories = config.get("procedure", {}).get("skill_directories", list(DEFAULT_SKILL_DIRECTORIES))
        if not isinstance(directories, list) or not all(
            isinstance(value, str) and value and not Path(value).is_absolute() and ".." not in Path(value).parts
            for value in directories
        ):
            raise ValueError("skill_directories must contain repository-relative paths")
        return sorted(set(directories))
    except (OSError, ValueError, AttributeError, TypeError):
        return list(DEFAULT_SKILL_DIRECTORIES)


def skill_files(root: Path, directories: list[str]) -> list[Path]:
    """Discover single-file and composite skills, including each learned directory."""
    paths: set[Path] = set()
    for relative in directories:
        for directory in (root / relative, root / relative / "learned"):
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                if entry.is_file() and entry.suffix == ".md":
                    paths.add(entry)
                elif entry.is_dir() and (entry / "SKILL.md").is_file():
                    paths.add(entry / "SKILL.md")
    return sorted(paths)


def source_paths(root: Path, directories: list[str]) -> list[Path]:
    """Return all inputs, including skills that may later acquire procedure metadata."""
    return sorted(set((root / "sdd/procedures").glob("*.yaml")) | set(skill_files(root, directories)))
