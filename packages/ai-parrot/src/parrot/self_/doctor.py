"""`parrot self doctor` checks (FEAT-633, spec §3 M3; rev 0.2 C14/C15; rev 0.5 C20/C23/C24). Read-only diagnostics.

Scopes: "runtime-only" (bootstrap: uv, Python, entry points, PATH, parrot_tools.wiki — offline, repo-free),
"full" (runtime + host configs + toolkits + SDD readiness iff <root>/sdd exists),
"sdd" (full with SDD readiness forced). Every parrot.sdd.* import is lazy and absence-tolerant.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from parrot.launcher import MANAGED_PYTHON, parrot_home, script_path  # TASK-4071
from parrot.self_.components import managed_venv  # TASK-4079

logger = logging.getLogger(__name__)

#: Kept in sync with the pin in scripts/install/install-parrot.{sh,ps1} (--global mode).
PINNED_UV_VERSION: str = "0.11.28"
DoctorScope = Literal["full", "runtime-only", "sdd"]
RUNTIME_ENTRYPOINTS: tuple[str, ...] = ("parrot", "wikitoolkit", "bookstore")
HOST_CLIS: dict[str, str] = {"claude": "claude", "codex": "codex", "google": "agy"}
SDD_LEDGER = Path("sdd/tasks/.id_ledger.json")


class DoctorCheck(BaseModel):
    """One diagnostic result. ``informational`` checks never fail doctor (C15 host-CLI checks, warnings)."""

    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    informational: bool = False


def failed(checks: list[DoctorCheck]) -> list[DoctorCheck]:
    """Non-informational failures — the only thing that makes ``parrot self doctor`` exit 1."""
    return [c for c in checks if not c.ok and not c.informational]


def installed_version(venv: Path) -> str | None:
    """ai-parrot version installed in ``venv`` (None when absent or not queryable)."""
    python = script_path(venv, "python")
    if not python.exists():
        return None
    code = "import importlib.metadata as m; print(m.version('ai-parrot'))"
    result = subprocess.run([str(python), "-c", code], capture_output=True, text=True, check=False)
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def _check_uv() -> DoctorCheck:
    """Pinned uv present under ~/.parrot/bin and at PINNED_UV_VERSION."""
    bundled = parrot_home() / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    fix = "re-run install-parrot --global"
    if not bundled.is_file():
        return DoctorCheck(name="uv", ok=False, detail=f"pinned uv not found at {bundled}", fix=fix)
    try:
        result = subprocess.run([str(bundled), "--version"], capture_output=True, text=True, check=False)
    except OSError as exc:
        return DoctorCheck(name="uv", ok=False, detail=f"cannot run {bundled}: {exc}", fix=fix)
    tokens = result.stdout.split()
    version = tokens[1] if result.returncode == 0 and len(tokens) > 1 else ""
    if version != PINNED_UV_VERSION:
        return DoctorCheck(
            name="uv", ok=False, detail=f"uv {version or 'unknown'} at {bundled}, expected {PINNED_UV_VERSION}", fix=fix
        )
    return DoctorCheck(name="uv", ok=True, detail=f"uv {version} at {bundled}")


def _check_python() -> DoctorCheck:
    """Managed venv's pyvenv.cfg ``version_info`` equals MANAGED_PYTHON (uv may record ``3.12``) or starts with MANAGED_PYTHON + '.'."""
    cfg = managed_venv() / "pyvenv.cfg"
    fix = "parrot self update (or re-run install-parrot --global)"
    try:
        lines = cfg.read_text(encoding="utf-8").splitlines()
    except OSError:
        return DoctorCheck(name="python", ok=False, detail=f"no managed venv ({cfg} missing)", fix=fix)
    version = ""
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip() == "version_info":
            version = value.strip()
            break
    ok = version == MANAGED_PYTHON or version.startswith(f"{MANAGED_PYTHON}.")
    return DoctorCheck(
        name="python", ok=ok, detail=f"managed Python {version or 'unknown'} (expected {MANAGED_PYTHON})",
        fix="" if ok else fix,
    )


def _check_path() -> DoctorCheck:
    """PATH contains ~/.parrot/bin (resolved comparison, os.pathsep split)."""
    home_bin = parrot_home() / "bin"

    def _norm(value: str) -> str:
        try:
            return str(Path(value).expanduser().resolve())
        except (OSError, RuntimeError):
            return value

    target = _norm(str(home_bin))
    entries = [_norm(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    ok = target in entries
    if os.name == "nt":
        fix = f'add "{home_bin}" to your user PATH (Settings > Environment Variables) and open a new terminal'
    else:
        fix = f"add to your shell profile: export PATH=\"{home_bin}:$PATH\""
    return DoctorCheck(
        name="PATH", ok=ok, detail=f"{home_bin} {'is' if ok else 'is NOT'} on PATH", fix="" if ok else fix
    )


def _check_entrypoints() -> DoctorCheck:
    """C14 runtime scope: the three console-script shims exist under ~/.parrot/bin AND resolve in the managed venv."""
    home_bin = parrot_home() / "bin"
    missing = [n for n in RUNTIME_ENTRYPOINTS if not (home_bin / (f"{n}.exe" if os.name == "nt" else n)).exists()
               or not script_path(managed_venv(), n).exists()]
    return DoctorCheck(
        name="runtime entry points", ok=not missing,
        detail="all present" if not missing else f"missing: {', '.join(missing)}",
        fix="" if not missing else "re-run install-parrot --global (or: parrot self update)",
    )


def _check_tools_wiki() -> DoctorCheck:
    """Rev 0.5 C20: ``parrot_tools.wiki`` imports in the managed venv (ai-parrot-tools is base runtime)."""
    python = script_path(managed_venv(), "python")
    fix = "parrot self update"
    if not python.exists():
        return DoctorCheck(name="parrot_tools.wiki", ok=False, detail=f"no interpreter at {python}", fix=fix)
    try:
        result = subprocess.run([str(python), "-c", "import parrot_tools.wiki"], capture_output=True, text=True, check=False)
    except OSError as exc:
        return DoctorCheck(name="parrot_tools.wiki", ok=False, detail=f"cannot run {python}: {exc}", fix=fix)
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        return DoctorCheck(name="parrot_tools.wiki", ok=False, detail=lines[-1] if lines else "import failed", fix=fix)
    return DoctorCheck(name="parrot_tools.wiki", ok=True, detail="importable in the managed venv")


# --- C15: SDD readiness (lazy, absence-tolerant; run only in "full" with <root>/sdd present, or "sdd") ---

#: Upper bound for any single ``git`` call the doctor makes (``ls-remote`` over a dead network would hang it).
GIT_TIMEOUT_S: float = 20.0


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``git -C root ...`` with a timeout and no credential prompt; a timeout is a non-zero result."""
    cmd = ["git", "-C", str(root), *args]
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=GIT_TIMEOUT_S,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {GIT_TIMEOUT_S:g}s")


def _sdd_base_branch(root: Path) -> tuple[str, DoctorCheck | None]:
    """(branch, informational check when the config module is unavailable). Default 'dev'."""
    try:
        from parrot.sdd.config import load_sdd_config  # TASK-4299 — lazy on purpose
    except ImportError:
        return "dev", DoctorCheck(name="sdd config", ok=True, informational=True,
                                  detail="parrot.sdd.config unavailable in this build; assuming base branch 'dev'")
    try:
        return load_sdd_config(root).base_branch, None
    except (OSError, ValueError) as exc:  # unreadable / invalid sdd/config.json is itself a failed check
        return "dev", DoctorCheck(name="sdd config", ok=False, detail=f"sdd/config.json invalid: {exc}",
                                  fix="fix sdd/config.json (parrot sdd install --dry-run shows the seed shape)")


def _check_sdd(root: Path) -> list[DoctorCheck]:
    """C15 check list, in proposal order. Never raises; never writes."""
    checks: list[DoctorCheck] = []
    origin = _git(root, "remote", "get-url", "origin")
    checks.append(DoctorCheck(name="sdd: origin remote", ok=origin.returncode == 0,
                              detail=origin.stdout.strip() or origin.stderr.strip(),
                              fix="git remote add origin <url>"))
    branch, cfg_check = _sdd_base_branch(root)
    if cfg_check:
        checks.append(cfg_check)
    checks.extend(_check_sdd_git(root, branch))
    checks.append(_check_gh())
    status = _sdd_status(root)
    checks.extend(_check_sdd_assets(root, status))
    checks.append(_check_ledger_attributes(root))
    checks.append(_check_ledger_hooks(root))
    checks.append(_check_guard_hook(status))
    return checks


def _check_sdd_git(root: Path, branch: str) -> list[DoctorCheck]:
    """Base branch on origin, ledger tracked, worktrees ignored."""
    checks: list[DoctorCheck] = []
    remote = _git(root, "ls-remote", "--heads", "origin", branch)
    if remote.returncode != 0:
        reason = remote.stderr.strip().splitlines()
        checks.append(DoctorCheck(name="sdd: base branch on origin", ok=True, informational=True,
                                  detail=f"could not reach origin: {reason[-1] if reason else 'unknown error'}"))
    else:
        found = bool(remote.stdout.strip())
        checks.append(DoctorCheck(name="sdd: base branch on origin", ok=found,
                                  detail=f"origin/{branch} {'exists' if found else 'does not exist'}",
                                  fix="" if found else f"git push -u origin {branch}"))
    tracked = _git(root, "ls-files", "--error-unmatch", str(SDD_LEDGER))
    checks.append(DoctorCheck(
        name="sdd: id ledger tracked", ok=tracked.returncode == 0,
        detail=f"{SDD_LEDGER} {'is' if tracked.returncode == 0 else 'is NOT'} git-tracked",
        fix="" if tracked.returncode == 0 else f'git add {SDD_LEDGER} && git commit -m "sdd: seed id ledger"'))
    ignored = _git(root, "check-ignore", "-q", ".claude/worktrees/x")
    checks.append(DoctorCheck(
        name="sdd: worktrees ignored", ok=ignored.returncode == 0,
        detail=f".claude/worktrees/ {'is' if ignored.returncode == 0 else 'is NOT'} git-ignored",
        fix="" if ignored.returncode == 0 else "parrot sdd install (adds the .gitignore block)"))
    return checks


def _check_gh() -> DoctorCheck:
    """``gh`` present and authenticated."""
    if not shutil.which("gh"):
        return DoctorCheck(name="sdd: gh", ok=False, detail="gh not found on PATH",
                           fix="install gh (https://cli.github.com), then: gh auth login")
    try:
        auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, check=False)
    except OSError as exc:
        return DoctorCheck(name="sdd: gh", ok=False, detail=f"cannot run gh: {exc}", fix="gh auth login")
    ok = auth.returncode == 0
    return DoctorCheck(name="sdd: gh", ok=ok, detail="gh authenticated" if ok else "gh is not authenticated",
                       fix="" if ok else "gh auth login")


def _sdd_status(root: Path) -> dict[str, Any] | None:
    """``sdd_status(root)`` from TASK-4091, or None when the module is absent / fails."""
    try:
        from parrot.sdd.installer import sdd_status  # TASK-4091 — lazy on purpose
    except ImportError:
        return None
    try:
        status = sdd_status(root)
    except Exception as exc:  # noqa: BLE001 — doctor never raises
        logger.warning("sdd_status failed: %s", exc)
        return None
    return status if isinstance(status, dict) else None


def _check_sdd_assets(root: Path, status: dict[str, Any] | None) -> list[DoctorCheck]:
    """jq (while referenced), installed files current, host CLIs (informational)."""
    checks: list[DoctorCheck] = []
    hosts: dict[str, Any] = (status or {}).get("hosts") or {}
    if status is None:
        checks.append(DoctorCheck(name="sdd: files current", ok=True, informational=True,
                                  detail="SDD flow not installed (parrot.sdd.installer unavailable in this build)"))
    elif not any(hosts.values()):
        checks.append(DoctorCheck(name="sdd: files current", ok=True, informational=True,
                                  detail="SDD flow not installed"))
    else:
        problems: list[str] = []
        edited = False
        for host, groups in hosts.items():
            for kind in ("outdated", "edited"):
                targets = list((groups or {}).get(kind) or [])
                if targets:
                    edited = edited or kind == "edited"
                    problems.append(f"{host} {kind}: {', '.join(str(t) for t in targets)}")
        checks.append(DoctorCheck(
            name="sdd: files current", ok=not problems,
            detail="all installed SDD files current" if not problems else "; ".join(problems),
            fix="" if not problems else ("parrot sdd status" if edited else "parrot sdd install")))
    # jq — only while an installed shipped file still references it.
    try:
        from parrot.sdd.audit import missing_tools, scan_paths  # TASK-4070 — lazy on purpose
    except ImportError:
        pass
    else:
        installed = [
            root / str(t) for groups in hosts.values() for targets in (groups or {}).values()
            if isinstance(targets, (list, tuple)) for t in targets
        ]
        try:
            referenced = any(f.kind == "external-tool" and "jq" in f.snippet for f in scan_paths(installed))
        except Exception as exc:  # noqa: BLE001
            logger.warning("sdd audit scan failed: %s", exc)
            referenced = False
        if referenced:
            present = "jq" not in missing_tools(scan_paths(installed))
            checks.append(DoctorCheck(name="sdd: jq", ok=present, detail="jq " + ("found" if present else "not found"),
                                      fix="" if present else "install jq (https://jqlang.github.io/jq/)"))
    for host, groups in hosts.items():
        if not (groups or {}).get("current"):
            continue
        cli_name = HOST_CLIS.get(host, host)
        found = shutil.which(cli_name) is not None
        checks.append(DoctorCheck(
            name=f"sdd: host cli {host}", ok=found, informational=True,
            detail=f"{cli_name} {'found' if found else 'not found on PATH'}",
            fix="" if found else f"install the {cli_name} CLI"))
    return checks


def _check_ledger_attributes(root: Path) -> DoctorCheck:
    """Rev 0.5 C23: ``.gitattributes`` carries both ledger ``merge=union`` lines."""
    wanted = ("sdd/ledger/events.jsonl", "sdd/ledger/archive/*.jsonl")
    try:
        lines = (root / ".gitattributes").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    present = {ln.split()[0] for ln in lines if ln.split() and "merge=union" in ln.split()[1:]}
    missing = [w for w in wanted if w not in present]
    return DoctorCheck(
        name="sdd: ledger merge=union", ok=not missing,
        detail="ledger merge=union lines present" if not missing else f"missing in .gitattributes: {', '.join(missing)}",
        fix="" if not missing else "parrot sdd install (writes the .gitattributes ledger block)")


def _check_ledger_hooks(root: Path) -> DoctorCheck:
    """Rev 0.5 C23: the four ledger hooks carry the ``parrot-ledger`` block."""
    from parrot.knowledge.wiki.claude_code import assets as claude_assets
    from parrot.knowledge.wiki.claude_code.installer import _git_hook_path

    fix = "parrot sdd install (installs the four ledger hooks)"
    missing: list[str] = []
    for event in claude_assets.LEDGER_HOOK_EVENTS:
        hook = _git_hook_path(root, event)
        if hook is None:
            return DoctorCheck(name="sdd: ledger hooks", ok=False, detail="not a git repository", fix=fix)
        try:
            text = hook.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if claude_assets.LEDGER_HOOK_BEGIN not in text:
            missing.append(event)
    return DoctorCheck(name="sdd: ledger hooks", ok=not missing,
                       detail="all four ledger hooks installed" if not missing else f"missing hooks: {', '.join(missing)}",
                       fix="" if not missing else fix)


def _check_guard_hook(status: dict[str, Any] | None) -> DoctorCheck:
    """Rev 0.6 C25: read ``sdd_status()["guard_hook"]``."""
    name = "sdd: guard hook"
    guard = (status or {}).get("guard_hook")
    if not isinstance(guard, dict) or guard.get("form") is None:
        return DoctorCheck(name=name, ok=True, informational=True, detail="no sdd-coder/sdd-worker agents")
    form, command, targets = guard.get("form"), guard.get("command"), guard.get("targets")
    if form == "other":
        return DoctorCheck(name=name, ok=False, fix="delete the hand-copied agent files and re-run `parrot sdd install`",
                           detail=f"guard hook was hand-patched or copied by hand: targets={targets}, command={command}")
    if guard.get("resolvable") is False:
        return DoctorCheck(
            name=name, ok=False, detail=f"guard hook command {command!r} does not resolve (targets={targets})",
            fix="re-run `parrot sdd install` (re-bakes the path), or install the global launcher "
                "(`install-parrot.sh --global`) and re-install with `--portable`")
    return DoctorCheck(name=name, ok=True,
                       detail=f"{form} guard hook resolves (checks the shell's PATH, not the Claude Code process's)")


def _command_problem(entry: Any, root: Path) -> str | None:
    """Return why one MCP entry's command is broken, else None.

    Absolute command → must exist; bare command → must resolve via ``shutil.which``.
    """
    if not isinstance(entry, dict):
        return None
    command = entry.get("command")
    if not isinstance(command, str) or not command:
        return None  # remote (http/url) entries carry no command
    if os.path.isabs(command):
        return None if Path(command).exists() else f"{command} (missing)"
    return None if shutil.which(command) else f"{command} (not on PATH)"


def _other_root(entry: Any, root: Path) -> str | None:
    """The foreign repo root an entry is baked for (``cwd`` or absolute ``--config`` arg), else None."""
    if not isinstance(entry, dict):
        return None
    mine = root.resolve()
    candidates: list[str] = []
    if isinstance(entry.get("cwd"), str):
        candidates.append(entry["cwd"])
    args = entry.get("args")
    if isinstance(args, list):
        for pos, arg in enumerate(args[:-1]):
            if arg == "--config" and isinstance(args[pos + 1], str) and os.path.isabs(args[pos + 1]):
                candidates.append(str(Path(args[pos + 1]).parent.parent))  # <root>/.parrot/mcp-toolkits.yaml
    for cand in candidates:
        try:
            resolved = Path(cand).resolve()
        except (OSError, RuntimeError):
            continue
        if resolved != mine:
            return str(resolved)
    return None


def _check_host_configs(root: Path) -> list[DoctorCheck]:
    """Claude .mcp.json, Codex .codex/config.toml, both Google mcp_config.json files (rev 0.5 C24).

    The user-global Google file also flags the cross-repo collision: a ``wikitoolkit`` / ``parrot-*``
    entry whose ``cwd`` (or absolute ``--config`` arg) belongs to another root — fix: re-install with
    ``--portable`` (spec §7). The repo-local Google file gets the command check only (C24).
    """
    from parrot.knowledge.wiki.google.installer import toolkit_config_paths  # verified: google/installer.py:142

    claude = root / ".mcp.json"
    codex = root / ".codex" / "config.toml"
    google, google_local = toolkit_config_paths(root)  # (default_mcp_config_path(), root/.agents/plugins/parrot/mcp_config.json)
    checks: list[DoctorCheck] = []
    targets: list[tuple[str, Path, str, bool]] = [
        ("claude .mcp.json", claude, "json", False),
        ("codex config.toml", codex, "toml", False),
        ("google mcp_config.json (user-global)", google, "json", True),
        ("google mcp_config.json (repo-local)", google_local, "json", False),
    ]
    for label, path, kind, global_file in targets:
        if not path.is_file():
            continue
        name = f"host config: {label}"
        try:
            if kind == "toml":
                with path.open("rb") as handle:
                    servers = tomllib.load(handle).get("mcp_servers") or {}
            else:
                servers = (json.loads(path.read_text(encoding="utf-8")) or {}).get("mcpServers") or {}
            if not isinstance(servers, dict):
                raise ValueError("MCP servers section is not a mapping")
        except (OSError, ValueError) as exc:  # tomllib.TOMLDecodeError and JSONDecodeError are ValueError
            checks.append(DoctorCheck(name=name, ok=False, detail=f"cannot parse {path}: {exc}",
                                      fix=f"fix or regenerate {path} (parrot toolkits / parrot claude|codex|google install)"))
            continue
        broken = [f"{key}: {problem}" for key, entry in servers.items() if (problem := _command_problem(entry, root))]
        checks.append(DoctorCheck(
            name=name, ok=not broken,
            detail=f"{path} OK" if not broken else f"{path}: broken command(s): {'; '.join(broken)}",
            fix="" if not broken else "re-run the host installer (parrot claude|codex|google install) or `parrot toolkits` to rewrite the entry"))
        if global_file:
            collisions = [f"{key} -> {other}" for key, entry in servers.items()
                          if (key == "wikitoolkit" or str(key).startswith("parrot-"))
                          and (other := _other_root(entry, root))]
            if collisions:
                checks.append(DoctorCheck(
                    name="host config: google cross-repo collision", ok=False,
                    detail=f"{path} is user-global but has entries baked for another repo: {'; '.join(collisions)}",
                    fix="re-install the Google host with --portable so the user-global entries carry no repo paths"))
    return checks


def _check_toolkits(root: Path) -> list[DoctorCheck]:
    """Installed toolkits (state != NOT_INSTALLED) with unmet requires_dist / requires_env."""
    from parrot.mcp.toolkit_install import ToolkitState, inventory  # verified: toolkit_install.py:32,94

    checks: list[DoctorCheck] = []
    for row in inventory(root):
        if row.state is ToolkitState.NOT_INSTALLED:
            continue
        if not row.dist_available:
            checks.append(DoctorCheck(
                name=f"toolkit {row.name}: packages", ok=False,
                detail=f"requires {', '.join(row.requires_dist)} which is not installed",
                fix=f"parrot self add {row.name}"))
        missing_env = [var for var in row.requires_env if not os.environ.get(var)]
        if missing_env:
            checks.append(DoctorCheck(
                name=f"toolkit {row.name}: env", ok=False,
                detail=(f"missing environment variable(s): {', '.join(missing_env)} "
                        "(navconfig may still supply them from env/.env, which os.environ does not show)"),
                fix=f"set {', '.join(missing_env)} (environment or env/.env); packages: parrot self add {row.name}"))
    return checks


def run_doctor(root: Path, *, scope: DoctorScope = "full") -> list[DoctorCheck]:
    """Run the checks of ``scope`` in spec order; never raises for a broken environment.

    "runtime-only" (C14 bootstrap) touches neither ``root`` nor the network and includes parrot_tools.wiki
    (rev 0.5 C20); "full" adds host configs, toolkits and — iff ``root/sdd`` exists — the C15 SDD readiness checks;
    "sdd" forces the latter.
    """
    checks = [_check_uv(), _check_python(), _check_entrypoints(), _check_path(), _check_tools_wiki()]
    if scope == "runtime-only":
        return checks
    checks.extend(_check_host_configs(root))
    checks.extend(_check_toolkits(root))
    if scope == "sdd" or (root / "sdd").is_dir():
        checks.extend(_check_sdd(root))
    return checks
