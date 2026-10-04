"""Turn the Odoo 19 Development Cookbook (6E) code repo into one Markdown per chapter.

Each recipe folder is a full addon snapshot; only files that are new or changed
versus the previous recipe of the same chapter are emitted, so a chapter reads
as an incremental walkthrough instead of 14 copies of the same module.
"""

import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
OUT.mkdir(parents=True, exist_ok=True) if len(sys.argv) > 2 else None

TITLES = {
    "01": "Installing the Odoo Development Environment",
    "03": "Creating Odoo Add-On Modules",
    "04": "Application Models",
    "05": "Basic Server-Side Development",
    "06": "Managing Module Data",
    "07": "Debugging Modules",
    "08": "Advanced Server-Side Development Techniques",
    "09": "Backend Views",
    "10": "Security Access",
    "11": "Internationalization",
    "12": "Automation, Workflows, Emails, and Printing",
    "13": "Web Server Development",
    "14": "Web Client Development",
    "15": "The Odoo Web Library (OWL)",
    "16": "Automated Test Cases",
    "17": "Remote Procedure Calls in Odoo",
    "19": "Point of Sale",
    "20": "Managing Emails in Odoo",
    "21": "Managing the IoT Box",
    "22": "CMS Website Development",
}
LANG = {
    ".py": "python",
    ".xml": "xml",
    ".csv": "csv",
    ".js": "javascript",
    ".scss": "scss",
    ".po": "po",
    ".pot": "po",
    ".md": "markdown",
    ".txt": "text",
    ".cfg": "ini",
    ".conf": "ini",
    ".json": "json",
    ".html": "html",
    ".css": "css",
    ".sh": "bash",
    ".yml": "yaml",
    ".yaml": "yaml",
}
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
MAX_FILE = 120_000


def text_files(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in LANG or p.stat().st_size > MAX_FILE:
            continue
        try:
            out[str(p.relative_to(root))] = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    return out


def neutralize_hash_comments(code: str) -> str:
    """Turn ``# comment`` lines into ``#: comment`` (still valid Python/CSV/shell).

    The bookstore's Markdown parser is not fence-aware: any line whose stripped
    form starts with ``#`` + whitespace becomes a heading. ``#:`` is the Sphinx
    doc-comment form, so the code stays valid and readable.
    """
    return re.sub(r"^([ \t]*#+)([ \t]+)", r"\1:\2", code, flags=re.M)


def pretty(name: str) -> str:
    m = re.match(r"^(\d+)[_-]?(.*)$", name)
    num, rest = (m.group(1), m.group(2)) if m else ("", name)
    label = rest.replace("_", " ").strip().capitalize() or name
    return f"Recipe {num} — {label}" if num else label


def demote(md: str, levels: int) -> str:
    return re.sub(r"^(#{1,6})", lambda m: "#" * min(6, len(m.group(1)) + levels), md, flags=re.M)


def main() -> None:
    for chapter in sorted(SRC.glob("Chapter*")):
        num = chapter.name[len("Chapter") :]
        title = TITLES.get(num, chapter.name)
        lines = [
            f"# Chapter {num} — {title}",
            "",
            f"Code companion for chapter {num} of *Odoo 19 Development Cookbook, 6th Edition* "
            f"(Husen Daudi, Jay Vora — Packt). Source: "
            f"https://github.com/PacktPublishing/Odoo-19-Development-Cookbook-6E/tree/main/{chapter.name}. "
            "Each recipe shows only the files that are new or changed since the previous recipe.",
            "",
        ]
        readme = chapter / "README.md"
        if readme.exists():
            lines += ["## Chapter notes", "", demote(readme.read_text(encoding="utf-8"), 2), ""]
        prev: dict[str, str] = {}
        recipes = sorted(p for p in chapter.iterdir() if p.is_dir())
        for recipe in recipes:
            files = text_files(recipe)
            lines += [f"## {pretty(recipe.name)}", "", f"Folder: `{chapter.name}/{recipe.name}`", ""]
            changed = {k: v for k, v in files.items() if prev.get(k) != v}
            unchanged = sorted(k for k in files if k in prev and prev[k] == files[k])
            removed = sorted(k for k in prev if k not in files)
            if unchanged:
                lines += [f"Unchanged from the previous recipe: {', '.join(f'`{u}`' for u in unchanged)}", ""]
            if removed:
                lines += [f"Removed in this recipe: {', '.join(f'`{r}`' for r in removed)}", ""]
            for rel, body in changed.items():
                ext = Path(rel).suffix.lower()
                if ext == ".md" and Path(rel).name.upper() == "README.MD":
                    lines += [f"### {rel}", "", demote(body, 3), ""]
                    continue
                lines += [f"### {rel}", "", f"```{LANG[ext]}", neutralize_hash_comments(body.rstrip("\n")), "```", ""]
            prev = files
        out = OUT / f"odoo19-cookbook-ch{num}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')}.md"
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"{out.name}: {out.stat().st_size // 1024} KB, {len(recipes)} recipes")


if __name__ == "__main__":
    main()
