"""Scan SDD markdown/hook assets for assumptions that break outside the ai-parrot monorepo (FEAT-633 S5).

Usage:
    python -m parrot.sdd.audit [PATH ...] [--root DIR] [--output FILE]

Stdlib-only by contract: imported by ``parrot sdd install`` (TASK-4091) to warn about missing tooling.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

KINDS: tuple[str, ...] = (
    "repo-script", "venv-path", "uv-run", "external-tool", "posix-shell", "monorepo-path",
    "org-data", "claude-md-ref", "branch-literal",            # C11a — publication safety
    # rev 0.8 C29 — foreign-repo breakage found by the 2026-10-30 end-to-end review
    "bare-python", "worktree-artifact", "jira-org-default", "unshipped-command", "nonexistent-cli",
)
EXTERNAL_TOOLS: tuple[str, ...] = ("jq", "gh", "tmux", "codex", "git-lfs", "agy", "black", "pylint")
#: Placeholders shipped files MUST use instead of real organisation data (TASK-4089 rewrites to these).
PLACEHOLDER_ATLASSIAN_HOST = "your-org.atlassian.net"
PLACEHOLDER_TICKET_PREFIX = "PROJ"
# org-data (a): any *.atlassian.net host that is not the placeholder.
ORG_HOST_RE = re.compile(r"(?<![\w-])(?!your-org\.atlassian\.net\b)[a-z0-9][a-z0-9-]*\.atlassian\.net\b")
# org-data (b): a Jira-style ticket key. Allow-listed prefixes are SDD's own ids and common non-ticket tokens.
TICKET_KEY_ALLOW: tuple[str, ...] = (PLACEHOLDER_TICKET_PREFIX, "FEAT", "TASK", "AC", "SHA", "UTF", "ISO", "RFC", "PEP", "CVE")
TICKET_KEY_RE = re.compile(r"(?<![\w-])(?!(?:" + "|".join(TICKET_KEY_ALLOW) + r")-)[A-Z][A-Z0-9]{1,9}-\d+\b")
# claude-md-ref: any reference to CLAUDE.md, with or without a section anchor (`CLAUDE.md § …`, `CLAUDE.md#…`).
CLAUDE_MD_RE = re.compile(r"\bCLAUDE\.md\b")
# branch-literal: dev|staging|main ONLY in an operator position — git ref (`origin/dev`), git verb
# (`checkout dev`, `checkout -b x dev`, `pull origin dev`, `merge dev`, `rebase dev`, `push origin dev`),
# an SDD flag (`--base dev`, `--base-branch=dev`) or frontmatter (`base_branch: dev`). Prose words
# ("the main checkout", "dev-loop", "staging area") never match because they lack the operator prefix.
BRANCH_LITERAL_RE = re.compile(
    r"(?:\borigin/|--base(?:-branch)?[ =]|\bbase_branch:\s*|\b(?:checkout|switch)\s+(?:-b\s+\S+\s+)?"
    r"|\bpull\s+origin\s+|\bpush\s+(?:-u\s+)?origin\s+|\bmerge\s+(?:--no-ff\s+)?|\brebase\s+(?:-i\s+)?)"
    r"(?P<branch>dev|staging|main)\b(?![-_/])"
)
DEFAULT_GLOBS: tuple[str, ...] = (
    ".claude/commands/sdd-*.md",
    ".claude/agents/sdd-*.md",
    ".claude/rules/*.md",
    ".claude/hooks/sdd-worker-format.sh",
    "sdd/templates/*",
    "sdd/WORKFLOW.md",
    ".agents/skills/sdd-*/SKILL.md",      # rev 0.5 C24 — Codex/Google twins
    ".agents/agents/sdd-*/agent.md",
    ".agent/workflows/sdd-*.md",
    ".agent/agents/sdd-*/agent.md",
)
REPO_SCRIPT_RE = re.compile(r"scripts[./]sdd[./](?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\.py|\.sh)?")
# Command position only (line start, backtick, `$(`, pipe, `&&`, `;`) so prose like "ask codex for…" never matches.
EXTERNAL_TOOL_RE = re.compile(
    r"(?:^\s*|`|\$\(|\|\s*|&&\s*|;\s*)(?P<tool>" + "|".join(map(re.escape, EXTERNAL_TOOLS)) + r")\s+[-\w'\"./]"
)
VENV_PATH_RE = re.compile(r"\.venv/(?:bin|Scripts)\b|\bsource\s+\.venv\b")
UV_RUN_RE = re.compile(r"\buv\s+run\b")
POSIX_SHELL_RE = re.compile(
    r"(?:^\s*source\s|[`;&|]\s*source\s)|\$\(|(?<![\w.])/tmp/|<<-?\s*['\"]?\w+|\bset\s+-[euo]+(?:\s+pipefail)?"
    r"|^#!\s*/(?:usr/)?(?:bin/env\s+)?(?:ba|z)?sh\b"
)
MONOREPO_PATH_RE = re.compile(r"\bpackages/ai-parrot\w*|\.claude/worktrees/")
# bare-python: `python` (never `python3`) run as a command — many hosts ship no `python` (Ubuntu, Debian, macOS).
# `.venv/bin/python`, `sys.executable`-style names and prose ("Python", "python files") never match.
BARE_PYTHON_RE = re.compile(r"(?<![\w/.$-])python(?![\w.])(?=\s+(?:-|<<))")
# worktree-artifact: a file the workflow writes inside the feature worktree; an untracked one makes
# `git worktree remove` refuse in a repo that does not ignore it. Use ${SDD_LOGS_ROOT:-/tmp/claude-$(id -u)/sdd-logs}.
WORKTREE_ARTIFACT_RE = re.compile(r"(?<![\w/-])artifacts/(?:logs|reviews)/")
# jira-org-default: the ai-parrot organisation's Jira project, component and custom-field ids shipped as defaults.
JIRA_ORG_DEFAULT_RE = re.compile(r"\bNAV\b|\bNav-AI\b|\bcustomfield_100(?:21|22|35)\b|(?<![\w.])100(?:21|22|35)(?![\w.])")
#: Host built-ins and commands other parrot installers write; any other backticked `/name` must be a shipped
#: `/sdd-*` command (the asset globs ship every `sdd-*` except `/sdd-insight`, rev 0.5 C22).
HOST_COMMANDS: tuple[str, ...] = (
    "agent", "agents", "clear", "compact", "config", "copy", "help", "init", "mcp", "model", "parrotwiki",
    "permissions", "reload-plugins", "review", "security-review", "skills", "subagents", "tmp",
)
UNSHIPPED_COMMAND_RE = re.compile(
    r"(?<![\w`])`/(?!(?:sdd-(?!insight\b)[a-z0-9-]*|sdd-|" + "|".join(map(re.escape, HOST_COMMANDS)) + r")(?=[\s`]))"
    r"(?P<cmd>[a-z][a-z0-9-]*)(?=[\s`])"
)
#: Commands the assets tell an agent to run that exist nowhere (`parrot jiratoolkit` has only auth/status/logout).
NONEXISTENT_CLIS: tuple[str, ...] = ("jiratoolkit",)
NONEXISTENT_CLI_RE = re.compile(r"(?<![\w/.])(?:" + "|".join(map(re.escape, NONEXISTENT_CLIS)) + r")(?![\w.])")
# The three C11a kinds are FIXED above; `org-data` is the union of ORG_HOST_RE and TICKET_KEY_RE (one finding per line).
_ORG_DATA_RE = re.compile("|".join((ORG_HOST_RE.pattern, TICKET_KEY_RE.pattern)))
_KIND_PATTERNS: dict[str, re.Pattern[str]] = {
    "repo-script": REPO_SCRIPT_RE,
    "venv-path": VENV_PATH_RE,
    "uv-run": UV_RUN_RE,
    "external-tool": EXTERNAL_TOOL_RE,
    "posix-shell": POSIX_SHELL_RE,
    "monorepo-path": MONOREPO_PATH_RE,
    "org-data": _ORG_DATA_RE,
    "claude-md-ref": CLAUDE_MD_RE,
    "branch-literal": BRANCH_LITERAL_RE,
    "bare-python": BARE_PYTHON_RE,
    "worktree-artifact": WORKTREE_ARTIFACT_RE,
    "jira-org-default": JIRA_ORG_DEFAULT_RE,
    "unshipped-command": UNSHIPPED_COMMAND_RE,
    "nonexistent-cli": NONEXISTENT_CLI_RE,
}


@dataclass(frozen=True)
class AssumptionFinding:
    """One line of an asset that encodes a non-portable assumption."""

    path: str
    line: int
    kind: str
    snippet: str


def scan_text(text: str, path: str) -> list[AssumptionFinding]:
    """Scan ``text`` line by line; at most one finding per (line, kind); snippet = stripped line, max 160 chars."""
    findings: list[AssumptionFinding] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        for kind in KINDS:
            pattern = _KIND_PATTERNS.get(kind)
            if pattern is not None and pattern.search(raw):
                findings.append(AssumptionFinding(path, lineno, kind, raw.strip()[:160]))
    return findings


def scan_paths(paths: Iterable[Path]) -> list[AssumptionFinding]:
    """Read each existing file as UTF-8 (errors="replace") and return all findings sorted by (path, line, kind)."""
    findings: list[AssumptionFinding] = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        findings.extend(scan_text(text, path.as_posix()))
    return sorted(findings, key=lambda f: (f.path, f.line, f.kind))


def missing_tools(findings: Sequence[AssumptionFinding]) -> list[str]:
    """Sorted unique external tools named by ``external-tool`` findings that ``shutil.which`` cannot find."""
    names = {m.group("tool") for f in findings if f.kind == "external-tool" for m in EXTERNAL_TOOL_RE.finditer(f.snippet)}
    return sorted(name for name in names if shutil.which(name) is None)


def helper_map(findings: Sequence[AssumptionFinding]) -> dict[str, list[str]]:
    """Map each path to the sorted unique ``scripts/sdd`` helper names it references (repo-script findings)."""
    mapping: dict[str, set[str]] = {}
    for finding in findings:
        if finding.kind != "repo-script":
            continue
        names = {m.group("name") for m in REPO_SCRIPT_RE.finditer(finding.snippet)}
        mapping.setdefault(finding.path, set()).update(names)
    return {path: sorted(names) for path, names in sorted(mapping.items())}


def render_report(findings: Sequence[AssumptionFinding], *, scanned: Sequence[str]) -> str:
    """Markdown: summary counts per kind, Helper reference map, Rewrite list, findings per file, Missing tools."""
    by_kind: dict[str, list[AssumptionFinding]] = {kind: [] for kind in KINDS}
    for finding in findings:
        by_kind.setdefault(finding.kind, []).append(finding)
    lines = [
        "# S5 — SDD asset assumption inventory (FEAT-633)", "",
        f"Scanned {len(scanned)} file(s).", "",
        "## Summary", "", "| Kind | Findings | Files |", "|---|---|---|",
    ]
    for kind in KINDS:
        items = by_kind.get(kind, [])
        lines.append(f"| {kind} | {len(items)} | {len({f.path for f in items})} |")
    mapping = helper_map(findings)
    lines += ["", "## Helper reference map", "", "| Asset | Helpers |", "|---|---|"]
    for path, names in mapping.items():
        suffix = " — not shipped (C22)" if "sdd-insight" in path else ""
        lines.append(f"| `{path}`{suffix} | {', '.join(names)} |")
    helpers = sorted({name for names in mapping.values() for name in names})
    lines += ["", "## Rewrite list (drives TASK-4089)", ""]
    lines += [f"- `scripts/sdd/{name}` / `scripts.sdd.{name}` → `parrot sdd run {name}`" for name in helpers]
    lines += ["", "## Findings by file", ""]
    per_file: dict[str, list[AssumptionFinding]] = {}
    for finding in findings:
        per_file.setdefault(finding.path, []).append(finding)
    for path in sorted(per_file):
        lines += [f"### {path}", ""]
        lines += [f"- L{f.line} [{f.kind}] `{f.snippet}`" for f in per_file[path]]
        lines.append("")
    missing = missing_tools(findings)
    lines += [f"## Missing tools on the generating host ({sys.platform})", ""]
    lines += [f"- `{tool}`" for tool in missing] or ["- none"]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: scan PATHs (default: DEFAULT_GLOBS under --root) and write the report.

    Exit codes: 0 ok; 1 a finding of a ``--fail-on`` kind exists (C11c CI gate); 2 nothing to scan.
    A PATH that is a directory is scanned recursively (every regular file, sorted).
    """
    parser = argparse.ArgumentParser(prog="python -m parrot.sdd.audit", description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--fail-on", default="", metavar="KIND[,KIND...]",
        help="exit 1 when any finding of these kinds exists (e.g. org-data,claude-md-ref,branch-literal)",
    )
    args = parser.parse_args(argv)
    fail_kinds = [k.strip() for k in args.fail_on.split(",") if k.strip()]
    unknown = [k for k in fail_kinds if k not in KINDS]
    if unknown:
        parser.error(f"unknown --fail-on kind(s): {', '.join(unknown)} (choose from {', '.join(KINDS)})")
    root = args.root.resolve()
    files: list[Path] = []
    if args.paths:
        for given in args.paths:
            target = given if given.is_absolute() else Path.cwd() / given
            if target.is_dir():
                files.extend(sorted(p for p in target.rglob("*") if p.is_file()))
            elif target.is_file():
                files.append(target)
    else:
        for pattern in DEFAULT_GLOBS:
            files.extend(sorted(p for p in root.glob(pattern) if p.is_file()))
    files = sorted({p.resolve() for p in files})
    if not files:
        sys.stderr.write("parrot.sdd.audit: no files to scan\n")
        return 2

    def _rel(path: Path) -> Path:
        try:
            return path.relative_to(root)
        except ValueError:
            return Path(path.name)

    findings: list[AssumptionFinding] = []
    for file in files:
        findings.extend(scan_text(file.read_text(encoding="utf-8", errors="replace"), _rel(file).as_posix()))
    findings.sort(key=lambda f: (f.path, f.line, f.kind))
    report = render_report(findings, scanned=[_rel(f).as_posix() for f in files])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    offending = [f for f in findings if f.kind in fail_kinds]
    for finding in offending:
        sys.stderr.write(f"{finding.path}:{finding.line}: [{finding.kind}] {finding.snippet}\n")
    return 1 if offending else 0


if __name__ == "__main__":
    raise SystemExit(main())
