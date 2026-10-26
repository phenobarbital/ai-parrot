"""Deploy the packaged SDD flow (``parrot/sdd/_assets/``) into a repository (FEAT-633 M6, rev 0.2).

Conflict rule (C4, receipt-driven — ``sdd/.sdd-installed.json`` records the SHA-256 of every
byte sequence this installer wrote): absent → write + record; matches the receipt → upgrade;
differs from the receipt → edited → skip + warning unless ``force``; not in the receipt →
foreign → skip + warning, never overwritten; unrecorded but byte-identical → adopt as current.
``uninstall`` removes only files whose SHA matches the receipt. Seeds (``sdd/config.json`` and
manifest entries flagged ``"seed": true``) are written once and never touched again.
"""

from __future__ import annotations

import hashlib
import json
import os
import logging
import re
import shlex
import shutil
import subprocess
import sys
from importlib import metadata, resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Sequence

from pydantic import BaseModel

from parrot.launcher import parrot_home, script_path
from parrot.sdd.audit import EXTERNAL_TOOL_RE, missing_tools, scan_paths  # TASK-4070

if TYPE_CHECKING:  # pragma: no cover
    from parrot.sdd.config import SddConfig

logger = logging.getLogger(__name__)

SUPPORTED_HOSTS: tuple[str, ...] = ("claude", "codex", "google")
MANIFEST_SCHEMA_VERSION = 1
RECEIPT_PATH = Path("sdd/.sdd-installed.json")  # C4: committed with sdd/; .parrot/ is gitignored (.gitignore:411)
RECEIPT_SCHEMA_VERSION = 1
GITIGNORE_BEGIN = "# >>> parrot sdd (managed) >>>"
GITIGNORE_END = "# <<< parrot sdd (managed) <<<"
GITIGNORE_BLOCK = (
    f"{GITIGNORE_BEGIN}\n# SDD feature worktrees (parrot sdd run ensure_worktree)\n.claude/worktrees/\n{GITIGNORE_END}"
)
#: rev 0.5 C23 — the shared ledger's union merge (FEAT-694), same marker pair as the .gitignore block.
GITATTRIBUTES_BLOCK = (
    f"{GITIGNORE_BEGIN}\n"
    "# FEAT-694: the shared ledger event log is append-only on every machine; take both sides.\n"
    "sdd/ledger/events.jsonl merge=union\n"
    "sdd/ledger/archive/*.jsonl merge=union\n"
    f"{GITIGNORE_END}"
)
#: rev 0.6 C25 — the guard-hook line as packaged in the Claude ``sdd-coder`` / ``sdd-worker`` agents.
GUARD_HOOK_LINE = "parrot sdd run worktree_environment --hook || exit 2"
_GUARD_HOOK_SUFFIX = " sdd run worktree_environment --hook || exit 2"

FileState = Literal["missing", "current", "outdated", "edited", "foreign"]
#: Plan vocabulary (C5). install: write | upgrade | overwrite | skip-current | skip-edited | skip-foreign |
#: seed | skip-seed | gitignore | gitattributes | ledger-hooks | ledger-seed | config-seed. uninstall: remove |
#: keep-edited | keep-foreign | skip-missing | keep-shared | gitignore-remove | gitattributes-remove |
#: keep-gitattributes | ledger-hooks-remove | keep-ledger-hooks | receipt-remove.   [rev 0.5 C23 / D5]
PlanAction = Literal[
    "write",
    "upgrade",
    "overwrite",
    "skip-current",
    "skip-edited",
    "skip-foreign",
    "seed",
    "skip-seed",
    "gitignore",
    "gitattributes",
    "ledger-hooks",
    "ledger-seed",
    "config-seed",
    "remove",
    "keep-edited",
    "keep-foreign",
    "skip-missing",
    "keep-shared",
    "gitignore-remove",
    "gitattributes-remove",
    "keep-gitattributes",
    "ledger-hooks-remove",
    "keep-ledger-hooks",
    "receipt-remove",
]


class PlannedAction(BaseModel):
    """One step of an install/uninstall plan; ``str()`` is the ``--dry-run`` line."""

    action: PlanAction
    target: str
    note: str = ""

    def __str__(self) -> str:
        return f"plan: {self.action} {self.target}" + (f" ({self.note})" if self.note else "")


HOOK_WIRING_NOTE = (
    "note: .claude/hooks/sdd-worker-format.sh is installed but not registered — add it to "
    ".claude/settings.json (SubagentStop/Stop) if you want post-run formatting"
)
_LEDGER_HOOK_BEGIN = "# >>> parrot-ledger >>>"
_LEDGER_HOOK_EVENTS = ("pre-commit", "post-merge", "post-checkout", "post-rewrite")


def _assets_root() -> Traversable:
    """Packaged asset tree (works from a wheel; never a repo checkout path)."""
    return resources.files("parrot.sdd") / "_assets"


def load_manifest() -> list[dict[str, Any]]:
    """Return the manifest's ``assets`` list.

    Raises:
        RuntimeError: manifest missing or ``schema_version`` unsupported.
    """
    path = _assets_root() / "manifest.json"
    if not path.is_file():
        raise RuntimeError("parrot/sdd/_assets/manifest.json is missing — broken ai-parrot install")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported SDD asset manifest schema_version {data.get('schema_version')!r}")
    return list(data["assets"])


def _validate_hosts(hosts: Sequence[str]) -> tuple[str, ...]:
    """Normalise ``hosts`` (dedupe, keep order) and reject unknown names with ``ValueError``."""
    unknown = sorted(set(hosts) - set(SUPPORTED_HOSTS))
    if unknown or not hosts:
        raise ValueError(f"unknown/empty SDD host(s) {unknown or list(hosts)}; choose from {SUPPORTED_HOSTS}")
    return tuple(dict.fromkeys(hosts))


def _selected(entries: list[dict[str, Any]], hosts: Sequence[str]) -> list[dict[str, Any]]:
    """Assets whose ``hosts`` intersect ``hosts``."""
    wanted = set(hosts)
    return [e for e in entries if wanted & set(e["hosts"])]


def _upsert_marker_block(text: str, block: str, begin: str, end: str) -> str:
    """Own copy of claude_code/installer.py::_upsert_marker_block (keys on BEGIN; repairs a missing END)."""
    block = block.rstrip("\n")
    if begin in text:
        head, _, rest = text.partition(begin)
        tail = rest.partition(end)[2] if end in rest else "\n"
        return f"{head}{block}{tail}"
    if text and not text.endswith("\n"):
        text += "\n"
    separator = "\n" if text else ""
    return f"{text}{separator}{block}\n"


def _remove_marker_block(text: str, begin: str, end: str) -> str:
    """Own copy of claude_code/installer.py::_remove_marker_block."""
    if begin not in text:
        return text
    head, _, rest = text.partition(begin)
    tail = rest.partition(end)[2] if end in rest else ""
    head = head.rstrip(" \t").rstrip("\n")
    if not head and not tail.strip():
        return ""
    return head + ("\n" + tail.lstrip("\n") if tail.strip() else "\n")


def _extract_block(text: str, begin: str, end: str) -> str | None:
    """Return the marker-delimited block (markers included) found in ``text``, or None."""
    if begin not in text:
        return None
    start = text.index(begin)
    stop = text.find(end, start)
    if stop == -1:
        return text[start:]
    return text[start : stop + len(end)]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _empty_receipt() -> dict[str, Any]:
    return {"schema_version": RECEIPT_SCHEMA_VERSION, "version": None, "files": {}, "blocks": {}, "ledger_hooks": []}


def load_receipt(root: Path) -> dict[str, Any]:
    """Return ``<root>/sdd/.sdd-installed.json`` or an empty receipt when absent.

    Shape: ``{"schema_version": 1, "version": "<ai-parrot that wrote it>" | None, "files": {target: sha256},
    "blocks": {".gitattributes": sha256}, "ledger_hooks": [event, ...]}`` — missing ``blocks`` / ``ledger_hooks``
    keys default to ``{}`` / ``[]``. An unreadable or wrong-schema receipt is treated as empty and logged at
    WARNING (never raises).
    """
    path = root / RECEIPT_PATH
    if not path.is_file():
        return _empty_receipt()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("sdd: unreadable receipt %s (%s); treating as empty", path, exc)
        return _empty_receipt()
    if not isinstance(data, dict) or data.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        logger.warning("sdd: receipt %s has an unsupported schema; treating as empty", path)
        return _empty_receipt()
    files = data.get("files")
    blocks = data.get("blocks")
    hooks = data.get("ledger_hooks")
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "version": data.get("version"),
        "files": dict(files) if isinstance(files, dict) else {},
        "blocks": dict(blocks) if isinstance(blocks, dict) else {},
        "ledger_hooks": list(hooks) if isinstance(hooks, list) else [],
    }


def _package_version() -> str:
    try:
        return metadata.version("ai-parrot")
    except metadata.PackageNotFoundError:  # pragma: no cover — running from a bare source tree
        return "0+unknown"


def _save_receipt(root: Path, receipt: dict[str, Any]) -> None:
    """Write the receipt once (sorted keys, indent 2, trailing newline), stamped with the running ai-parrot version."""
    receipt["schema_version"] = RECEIPT_SCHEMA_VERSION
    receipt["version"] = _package_version()
    path = root / RECEIPT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# C25 — guard-hook rendering
# --------------------------------------------------------------------------


def _under(path: Path, base: Path) -> bool:
    """True when ``path`` is ``base`` or lives below it (lexically)."""
    return path == base or base in path.parents


def guard_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]:
    """Return the guard-hook command to render and its form (rev 0.6 C25).

    ``bare`` when ``portable`` is set or when ``parrot`` on PATH resolves under ``parrot_home()`` (the managed
    launcher shims may be symlinks into ``~/.parrot/venv``, so both the path as found and its resolution are
    compared); otherwise ``baked``: the absolute path of this interpreter's venv ``parrot`` script.
    """
    if portable:
        return GUARD_HOOK_LINE, "bare"
    found = shutil.which("parrot")
    if found:
        home = parrot_home()
        found_path = Path(found)
        homes = {home, home.resolve()}
        candidates = {found_path, found_path.resolve()}
        if any(_under(c, h) for c in candidates for h in homes):
            return GUARD_HOOK_LINE, "bare"
    baked = shlex.quote(script_path(Path(sys.prefix), "parrot").as_posix())
    return baked + _GUARD_HOOK_SUFFIX, "baked"


def _rendered_payload(entry: dict[str, Any], hook: str) -> bytes:
    """Packaged bytes of ``entry`` with the guard-hook line replaced by ``hook`` (YAML single-quote escaped)."""
    payload = (_assets_root() / entry["source"]).read_bytes()
    marker = GUARD_HOOK_LINE.encode("utf-8")
    if marker not in payload or hook == GUARD_HOOK_LINE:
        return payload
    return payload.replace(marker, hook.replace("'", "''").encode("utf-8"))


def classify_entry(
    root: Path, entry: dict[str, Any], receipt: dict[str, Any], hook: str = GUARD_HOOK_LINE
) -> FileState:
    """C4 state of one manifest target.

    missing → not on disk; foreign → on disk, not in the receipt, not byte-identical to the
    packaged copy; edited → on disk, in the receipt, SHA differs from the record; current → SHA
    equals the record (or unrecorded but byte-identical to the packaged copy — adopted) AND equals
    the packaged copy; outdated → SHA equals the record but the packaged copy changed. The packaged copy
    is the one rendered with ``hook`` (C25).
    """
    target = root / entry["target"]
    if not target.is_file():
        return "missing"
    on_disk = _sha256(target.read_bytes())
    packaged = _sha256(_rendered_payload(entry, hook))
    recorded = receipt["files"].get(entry["target"])
    if recorded is None:
        return "current" if on_disk == packaged else "foreign"
    if on_disk != recorded:
        return "edited"
    return "current" if on_disk == packaged else "outdated"


def plan_install(
    root: Path, hosts: Sequence[str], *, force: bool = False, hook: str = GUARD_HOOK_LINE
) -> list[PlannedAction]:
    """Pure: the ordered plan for ``install`` (assets, seeds, gitignore, ledger, config). No I/O writes."""
    receipt = load_receipt(root)
    plan: list[PlannedAction] = []
    for entry in _selected(load_manifest(), _validate_hosts(hosts)):
        target = entry["target"]
        if entry.get("seed", False):
            plan.append(PlannedAction(action="skip-seed" if (root / target).exists() else "seed", target=target))
            continue
        state = classify_entry(root, entry, receipt, hook)
        if state == "missing":
            plan.append(PlannedAction(action="write", target=target))
        elif state == "current":
            plan.append(PlannedAction(action="skip-current", target=target))
        elif state == "outdated":
            plan.append(PlannedAction(action="upgrade", target=target))
        elif state == "edited":
            if force:
                plan.append(PlannedAction(action="overwrite", target=target, note="--force"))
            else:
                plan.append(
                    PlannedAction(action="skip-edited", target=target, note="edited since parrot wrote it; use --force")
                )
        else:
            plan.append(
                PlannedAction(action="skip-foreign", target=target, note="not written by parrot sdd; never overwritten")
            )
    plan.append(PlannedAction(action="gitignore", target=".gitignore"))
    plan.append(PlannedAction(action="gitattributes", target=".gitattributes"))  # rev 0.5 C23, any host
    plan.append(PlannedAction(action="ledger-hooks", target=".git/hooks"))  # rev 0.5 C23, any host
    if not (root / "sdd/tasks/.id_ledger.json").exists():
        plan.append(PlannedAction(action="ledger-seed", target="sdd/tasks/.id_ledger.json"))
    if not (root / "sdd/config.json").exists():
        plan.append(PlannedAction(action="config-seed", target="sdd/config.json"))
    return plan


def _host_installed(root: Path, host: str, entries: list[dict[str, Any]], receipt: dict[str, Any]) -> bool:
    """True when ``host`` has at least one host-specific (single-host) target recorded and present."""
    return any(
        e["hosts"] == [host] and e["target"] in receipt["files"] and (root / e["target"]).is_file() for e in entries
    )


def _post_commit_has_wiki_block(root: Path) -> bool:
    """True when the post-commit hook carries the ``parrot-wiki`` block (the Claude/wiki integration is present)."""
    from parrot.knowledge.wiki.claude_code import assets as claude_assets
    from parrot.knowledge.wiki.claude_code.installer import _git_hook_path

    path = _git_hook_path(root, "post-commit")
    return path is not None and path.exists() and claude_assets.GIT_HOOK_BEGIN in path.read_text(encoding="utf-8")


def _any_ledger_hook_block(root: Path) -> bool:
    """True when any of the four ledger hooks carries a ``parrot-ledger`` block."""
    from parrot.knowledge.wiki.claude_code.installer import _git_hook_path

    for event in _LEDGER_HOOK_EVENTS:
        path = _git_hook_path(root, event)
        if path is not None and path.exists() and _LEDGER_HOOK_BEGIN in path.read_text(encoding="utf-8"):
            return True
    return False


def plan_uninstall(root: Path, hosts: Sequence[str]) -> list[PlannedAction]:
    """Pure: ``remove`` only targets whose on-disk SHA matches the receipt; keep edited/foreign; keep shared
    assets another installed host still needs; seeds and state are never planned for removal."""
    selected_hosts = _validate_hosts(hosts)
    receipt = load_receipt(root)
    entries = load_manifest()
    remaining_hosts = [
        h for h in SUPPORTED_HOSTS if h not in selected_hosts and _host_installed(root, h, entries, receipt)
    ]
    plan: list[PlannedAction] = []
    removed: set[str] = set()
    for entry in _selected(entries, selected_hosts):
        if entry.get("seed", False):
            continue
        target = entry["target"]
        state = classify_entry(root, entry, receipt)
        recorded = target in receipt["files"]
        if state == "missing":
            plan.append(PlannedAction(action="skip-missing", target=target))
            if recorded:
                removed.add(target)  # deleted by hand: nothing left to remove, so it must not pin the receipt/hooks
        elif state == "edited":
            plan.append(PlannedAction(action="keep-edited", target=target, note="edited since parrot wrote it"))
        elif state == "foreign" or not recorded:
            plan.append(PlannedAction(action="keep-foreign", target=target, note="not recorded in the receipt"))
        elif set(entry["hosts"]) & set(remaining_hosts):
            plan.append(PlannedAction(action="keep-shared", target=target, note="still needed by another host"))
        else:
            plan.append(PlannedAction(action="remove", target=target))
            removed.add(target)
    if set(receipt["files"]) - removed:
        return plan  # recorded files remain: the shared blocks, hooks and receipt stay
    gitignore = root / ".gitignore"
    if gitignore.is_file() and GITIGNORE_BEGIN in gitignore.read_text(encoding="utf-8"):
        plan.append(PlannedAction(action="gitignore-remove", target=".gitignore"))
    recorded_block = receipt["blocks"].get(".gitattributes")
    attributes = root / ".gitattributes"
    if recorded_block is not None and attributes.is_file():
        block = _extract_block(attributes.read_text(encoding="utf-8"), GITIGNORE_BEGIN, GITIGNORE_END)
        if block is not None:
            if _sha256(block.encode("utf-8")) == recorded_block:
                plan.append(PlannedAction(action="gitattributes-remove", target=".gitattributes"))
            else:
                plan.append(
                    PlannedAction(
                        action="keep-gitattributes", target=".gitattributes", note="block edited since install"
                    )
                )
    if receipt["ledger_hooks"]:
        if _post_commit_has_wiki_block(root):
            plan.append(
                PlannedAction(action="keep-ledger-hooks", target=".git/hooks", note="shared with parrot claude install")
            )
        else:
            plan.append(PlannedAction(action="ledger-hooks-remove", target=".git/hooks"))
    elif _any_ledger_hook_block(root):
        plan.append(PlannedAction(action="keep-ledger-hooks", target=".git/hooks", note="not installed by parrot sdd"))
    if (root / RECEIPT_PATH).exists():
        plan.append(PlannedAction(action="receipt-remove", target=RECEIPT_PATH.as_posix()))
    return plan


def _apply_asset(
    root: Path, entry: dict[str, Any], action: PlannedAction, receipt: dict[str, Any], hook: str = GUARD_HOOK_LINE
) -> str:
    """Execute one asset action; updates ``receipt["files"]`` in place; returns the action-log line."""
    target = root / entry["target"]
    if action.action in {"skip-current", "skip-seed"}:
        if action.action == "skip-current":
            receipt["files"][entry["target"]] = _sha256(target.read_bytes())  # adoption of unrecorded identical files
        return f"{entry['target']} — up to date"
    if action.action in {"skip-edited", "skip-foreign"}:
        logger.warning("sdd install: %s %s; skipped", entry["target"], action.note)
        return f"warning: {entry['target']} — {action.note}"
    # The repository is untrusted input: a symlinked target or parent directory (e.g. `.claude/agents -> /etc/x`)
    # would make the write land outside the repo. Refuse unless the fully resolved path stays under the root.
    if target.is_symlink() or not _under(Path(os.path.realpath(target)), Path(os.path.realpath(root))):
        logger.warning("sdd install: %s resolves outside the repository (symlink); skipped", entry["target"])
        return f"warning: {entry['target']} — resolves outside the repository (symlink); skipped"
    payload = _rendered_payload(entry, hook)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    if target.suffix == ".sh":
        target.chmod(0o755)  # wheels do not reliably preserve the exec bit
    if action.action != "seed":
        receipt["files"][entry["target"]] = _sha256(payload)
    verb = {
        "write": "installed",
        "upgrade": "upgraded",
        "overwrite": "overwritten (--force)",
        "seed": "seeded (team-owned; never overwritten)",
    }
    return f"{entry['target']} — {verb[action.action]}"


def _seed_config(root: Path) -> str:
    """C6: write ``sdd/config.json`` from ``default_sdd_config()`` iff absent (TASK-4299; lazy import)."""
    from parrot.sdd.config import CONFIG_PATH, default_sdd_config  # TASK-4299

    path = root / CONFIG_PATH
    if path.exists():
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_sdd_config().model_dump_json(indent=2) + "\n", encoding="utf-8")
    return (
        f"{CONFIG_PATH} — seeded; edit base_branch/hotfix_base/issue_tracker/test_command for this repo and commit it"
    )


def _install_gitignore(root: Path) -> str:
    """Upsert the managed ``.claude/worktrees/`` block into ``<root>/.gitignore``."""
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _upsert_marker_block(text, GITIGNORE_BLOCK, GITIGNORE_BEGIN, GITIGNORE_END)
    if updated == text:
        return ".gitignore — .claude/worktrees/ block up to date"
    path.write_text(updated, encoding="utf-8")
    return ".gitignore — managed .claude/worktrees/ block written"


def _install_gitattributes(root: Path, receipt: dict[str, Any]) -> str:
    """rev 0.5 C23: upsert ``GITATTRIBUTES_BLOCK`` into ``<root>/.gitattributes`` and record it in the receipt."""
    path = root / ".gitattributes"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _upsert_marker_block(text, GITATTRIBUTES_BLOCK, GITIGNORE_BEGIN, GITIGNORE_END)
    receipt.setdefault("blocks", {})[".gitattributes"] = _sha256(GITATTRIBUTES_BLOCK.encode("utf-8"))
    if updated == text:
        return ".gitattributes — ledger merge=union block up to date"
    path.write_text(updated, encoding="utf-8")
    return ".gitattributes — managed ledger merge=union block written"


def _install_ledger_hooks_step(root: Path, receipt: dict[str, Any]) -> list[str]:
    """rev 0.5 C23: the four FEAT-694 ledger hooks through the claude installer's own function (lazy import).

    Records in ``receipt["ledger_hooks"]`` the events whose ``parrot-ledger`` block did not exist before this
    call (PR #1746 review): uninstall removes the hooks only when this integration created them and the
    Claude/wiki integration (``parrot claude install``, which installs the same blocks) is not present.
    """
    from parrot.knowledge.wiki.claude_code import assets as claude_assets
    from parrot.knowledge.wiki.claude_code.installer import _git_hook_path, _install_ledger_hooks  # C23

    def has_block(event: str) -> bool:
        path = _git_hook_path(root, event)
        return (
            path is not None and path.exists() and claude_assets.LEDGER_HOOK_BEGIN in path.read_text(encoding="utf-8")
        )

    before = {event for event in claude_assets.LEDGER_HOOK_EVENTS if has_block(event)}
    actions = _install_ledger_hooks(root)
    created = {event for event in claude_assets.LEDGER_HOOK_EVENTS if event not in before and has_block(event)}
    receipt["ledger_hooks"] = sorted(set(receipt.get("ledger_hooks", [])) | created)
    return actions


def _test_command_warning(config: "SddConfig") -> str | None:
    """rev 0.5 C21: one ``warning:`` line when ``sdd/config.json`` ``test_command`` is null, else None.

    ``config`` is the one ``install_sdd_integration`` validated before any write (PR #1746 review).
    """
    if config.test_command is not None:
        return None
    return (
        "warning: sdd/config.json test_command is null — set it to the command that runs this repo's tests; "
        "the shipped test steps run it once from the repo root (C21)"
    )


def _seed_id_ledger(root: Path) -> str | None:
    """Create ``sdd/tasks/.id_ledger.json`` iff absent (reserve_ids reads it from git and raises when missing)."""
    from parrot.sdd.scripts.id_ledger import LEDGER_PATH, bootstrap_ledger, save_ledger  # TASK-4085

    path = root / LEDGER_PATH
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    save_ledger(path, bootstrap_ledger(root / "sdd/tasks/index", root / "sdd/specs"))
    return (
        f"{LEDGER_PATH} — seeded; warning: commit and push it to your base branch before "
        "`parrot sdd run reserve_ids` (it reads the ledger from git)"
    )


def _audit(root: Path, installed: list[Path]) -> list[str]:
    """codex S9: warn about tooling the installed assets need but this machine lacks."""
    try:
        findings = scan_paths(installed)
        warnings: list[str] = []
        for tool in missing_tools(findings):
            origin = next(
                (
                    f
                    for f in findings
                    if f.kind == "external-tool"
                    and any(m.group("tool") == tool for m in EXTERNAL_TOOL_RE.finditer(f.snippet))
                ),
                None,
            )
            where = ""
            if origin is not None:
                try:
                    shown = Path(origin.path).relative_to(root).as_posix()
                except ValueError:
                    shown = origin.path
                where = f" (needed by {shown}:{origin.line})"
            warnings.append(f"warning: {tool} not found{where}")
        return warnings
    except Exception as exc:  # never fail the install over an advisory scan
        logger.warning("sdd install: tooling audit failed: %s", exc)
        return []


def _main_checkout_venv(root: Path) -> Path | None:
    """``<main checkout>/.venv`` derived from ``git rev-parse --git-common-dir`` (None outside git)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    common = Path(out)
    if not common.is_absolute():
        common = root / common
    return common.resolve().parent / ".venv"


def _baked_venv_warning(root: Path) -> str | None:
    """C25: warn when the baked venv is neither ``<root>/.venv`` nor the main checkout's ``.venv``."""
    prefix = Path(sys.prefix).resolve()
    candidates = [(root / ".venv").resolve()]
    main = _main_checkout_venv(root)
    if main is not None:
        candidates.append(main.resolve())
    if prefix in candidates:
        return None
    return (
        f"warning: guard hook points at the venv {prefix}, which is not this repository's .venv; "
        "install ai-parrot there or the global launcher (then use --portable)"
    )


def install_sdd_integration(
    root: Path,
    hosts: Sequence[str] = ("claude",),
    *,
    force: bool = False,
    dry_run: bool = False,
    portable: bool = False,
) -> list[str]:
    """Deploy packaged SDD assets for ``hosts`` into ``root``; never overwrites foreign content.

    Args:
        root: Target repository root (need not be a Python project).
        hosts: Any of ``SUPPORTED_HOSTS``; shared assets (templates, WORKFLOW.md) install for every host.
        force: Overwrite manifest targets the receipt says we wrote but the team edited since.
            Never touches foreign (unrecorded) files or seeds.
        dry_run: Return the plan (``plan: <action> <target>`` lines) and write NOTHING — no asset,
            seed, gitignore, ledger, config, receipt, or directory.
        portable: Write the bare guard-hook command (needs the global launcher on PATH) instead of
            baking the installing venv's ``parrot`` when the launcher is not on PATH (C25).

    Returns:
        Human-readable action log; skipped conflicts and audit findings start with ``warning:``;
        dry-run lines start with ``plan:``.

    Raises:
        ValueError: unknown host; ``SddConfigError`` (a ``ValueError``) for a malformed existing
            ``sdd/config.json``, raised before anything is written.
        RuntimeError: packaged manifest missing/unsupported.
    """
    # PR #1746 review (C21): validate an existing sdd/config.json BEFORE planning or writing anything — a
    # malformed file raises SddConfigError (a ValueError; the CLI turns it into exit 1) and the target repo
    # is left untouched, in --dry-run too. Absent → defaults (no error).
    from parrot.sdd.config import load_sdd_config  # TASK-4299

    config = load_sdd_config(root)
    hook, form = guard_hook_command(portable=portable)
    plan = plan_install(root, hosts, force=force, hook=hook)
    if dry_run:
        return [str(step) for step in plan]
    receipt = load_receipt(root)
    by_target = {e["target"]: e for e in load_manifest()}
    actions: list[str] = []
    for step in plan:
        if step.target in by_target:
            actions.append(_apply_asset(root, by_target[step.target], step, receipt, hook))
        elif step.action == "gitignore":
            actions.append(_install_gitignore(root))
        elif step.action == "gitattributes":
            actions.append(_install_gitattributes(root, receipt))
        elif step.action == "ledger-hooks":
            actions.extend(_install_ledger_hooks_step(root, receipt))
        elif step.action == "ledger-seed":
            actions.append(_seed_id_ledger(root) or "")
        elif step.action == "config-seed":
            actions.append(_seed_config(root))
    _save_receipt(root, receipt)
    actions.append(f"{RECEIPT_PATH} — written; commit it with the installed files (it drives upgrades and uninstall)")
    actions.append(_test_command_warning(config) or "")
    if "claude" in hosts:
        actions.append(HOOK_WIRING_NOTE)
        if form == "baked":
            actions.append(
                f"note: guard hook baked to {hook.split(_GUARD_HOOK_SUFFIX)[0]}; re-run after rebuilding the venv, "
                "or install the global launcher and use --portable"
            )
            actions.append(_baked_venv_warning(root) or "")
    installed = [root / t for t in receipt["files"] if (root / t).is_file()]
    actions.extend(_audit(root, installed))
    return [a for a in actions if a]


def _prune_empty_parents(root: Path, path: Path) -> None:
    """Remove now-empty directories above ``path`` up to (never including) ``root``."""
    parent = path.parent
    while parent != root and root in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def uninstall_sdd_integration(root: Path, hosts: Sequence[str] = ("claude",), *, dry_run: bool = False) -> list[str]:
    """Remove SDD assets for ``hosts`` whose on-disk SHA matches the receipt (edited/foreign files are kept and reported).

    The ``.gitignore`` block, the recorded ``.gitattributes`` block (C23) and the receipt are removed only
    when no recorded file remains; the ledger hooks are removed only when ``receipt["ledger_hooks"]`` says this
    integration created them and no ``parrot-wiki`` post-commit block shows the Claude integration shares them;
    ``sdd/tasks/.id_ledger.json``, ``sdd/config.json`` and seeds are never removed (state / team-owned).
    ``dry_run`` returns the plan and writes nothing.
    """
    plan = plan_uninstall(root, hosts)
    if dry_run:
        return [str(step) for step in plan]
    receipt = load_receipt(root)
    actions: list[str] = []
    drop_receipt = False
    for step in plan:
        if step.action == "remove":
            target = root / step.target
            target.unlink(missing_ok=True)
            _prune_empty_parents(root, target)
            receipt["files"].pop(step.target, None)
            actions.append(f"{step.target} — removed")
        elif step.action in {"keep-edited", "keep-foreign"}:
            actions.append(f"warning: {step.target} — kept ({step.note})")
        elif step.action == "keep-shared":
            actions.append(f"{step.target} — kept ({step.note})")
        elif step.action == "skip-missing":
            receipt["files"].pop(step.target, None)  # forget the recorded-but-deleted asset
            continue
        elif step.action == "gitignore-remove":
            path = root / ".gitignore"
            text = path.read_text(encoding="utf-8")
            path.write_text(_remove_marker_block(text, GITIGNORE_BEGIN, GITIGNORE_END), encoding="utf-8")
            actions.append(".gitignore — managed block removed")
        elif step.action == "gitattributes-remove":
            path = root / ".gitattributes"
            text = path.read_text(encoding="utf-8")
            path.write_text(_remove_marker_block(text, GITIGNORE_BEGIN, GITIGNORE_END), encoding="utf-8")
            receipt["blocks"].pop(".gitattributes", None)
            actions.append(".gitattributes — managed block removed")
        elif step.action == "keep-gitattributes":
            actions.append(f"warning: .gitattributes — block kept ({step.note})")
        elif step.action == "ledger-hooks-remove":
            from parrot.knowledge.wiki.claude_code.installer import _uninstall_ledger_hooks

            actions.extend(_uninstall_ledger_hooks(root))
            receipt["ledger_hooks"] = []
        elif step.action == "keep-ledger-hooks":
            actions.append(f"git ledger hooks — kept (keep-ledger-hooks: {step.note})")
        elif step.action == "receipt-remove":
            drop_receipt = True
    if drop_receipt:
        (root / RECEIPT_PATH).unlink(missing_ok=True)
        _prune_empty_parents(root, root / RECEIPT_PATH)
        actions.append(f"{RECEIPT_PATH} — removed")
    elif (root / RECEIPT_PATH).exists():
        _save_receipt(root, receipt)
    return actions


# --------------------------------------------------------------------------
# status (C4 / C15 / C25)
# --------------------------------------------------------------------------

_YAML_COMMAND_RE = re.compile(r"^\s*command:\s*(?P<value>.*?)\s*$")


def _yaml_scalar(value: str) -> str:
    """Decode a single-quoted / double-quoted / plain YAML scalar of the one-line shape the agents use."""
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"')
    return value


def _classify_hook_command(command: str) -> tuple[Literal["bare", "baked", "other"], bool]:
    """Return ``(form, resolvable)`` for one guard-hook command (C25)."""
    if command == GUARD_HOOK_LINE:
        return "bare", shutil.which("parrot") is not None
    if command.endswith(_GUARD_HOOK_SUFFIX):
        try:
            tokens = shlex.split(command[: -len(_GUARD_HOOK_SUFFIX)])
        except ValueError:
            return "other", False
        if len(tokens) == 1 and Path(tokens[0]).is_absolute() and Path(tokens[0]).name in {"parrot", "parrot.exe"}:
            return "baked", Path(tokens[0]).exists()
    return "other", False


def _guard_hook_report(root: Path) -> dict[str, Any]:
    """C25: read the ``command:`` of every ``.claude/agents/*.md`` whose frontmatter names ``worktree_environment``."""
    targets: list[str] = []
    commands: list[str] = []
    agents = root / ".claude" / "agents"
    for path in sorted(agents.glob("*.md")) if agents.is_dir() else []:
        try:
            parts = path.read_text(encoding="utf-8").split("---", 2)
        except (OSError, UnicodeDecodeError):
            continue
        if len(parts) < 3 or "worktree_environment" not in parts[1]:
            continue
        for line in parts[1].splitlines():
            match = _YAML_COMMAND_RE.match(line)
            if match and "worktree_environment" in match.group("value"):
                targets.append(path.relative_to(root).as_posix())
                commands.append(_yaml_scalar(match.group("value")))
                break
    if not commands:
        return {"form": None, "command": None, "targets": [], "resolvable": True}
    verdicts = [_classify_hook_command(c) for c in commands]
    forms = [v[0] for v in verdicts]
    form = "other" if "other" in forms else forms[0]
    return {
        "form": form,
        "command": commands[0],
        "targets": targets,
        "resolvable": all(v[1] for v in verdicts),
    }


def _ledger_hooks_present(root: Path) -> bool:
    """True when all four ledger hooks carry the ``parrot-ledger`` block (False when the wiki package is absent)."""
    try:
        from parrot.knowledge.wiki.claude_code.installer import _git_hook_path
    except ImportError:  # pragma: no cover
        return False
    for event in _LEDGER_HOOK_EVENTS:
        path = _git_hook_path(root, event)
        if path is None or not path.exists() or _LEDGER_HOOK_BEGIN not in path.read_text(encoding="utf-8"):
            return False
    return True


def sdd_status(root: Path) -> dict[str, Any]:
    """Per-host install state (C4/C15/C25):

    ``{"hosts": {h: {"current": [...], "outdated": [...], "edited": [...], "foreign": [...], "missing": [...]}},
    "seeds": {"<target>": "seed-present" | "missing"}, "config": bool, "gitignore": bool, "id_ledger": bool,
    "gitattributes": bool, "ledger_hooks": bool,  # [rev 0.5 D5]
    "guard_hook": {"form": "bare" | "baked" | "other" | None, "command": str | None, "targets": [str],
    "resolvable": bool},  # [rev 0.6 C25]
    "receipt_version": str | None}`` (targets are repo-relative strings). Import-cheap: ``parrot self
    doctor`` (TASK-4080) imports this lazily and treats ``outdated``/``edited`` as "not current". Guard-hook
    assets are compared against the rendering matching the form already on disk, so a bare or baked install
    reports ``current`` until the mode is changed by a re-install.
    """
    receipt = load_receipt(root)
    entries = load_manifest()
    guard = _guard_hook_report(root)
    hook = guard["command"] if guard["form"] in {"bare", "baked"} else guard_hook_command(portable=False)[0]
    hosts: dict[str, dict[str, list[str]]] = {}
    for host in SUPPORTED_HOSTS:
        states: dict[str, list[str]] = {"current": [], "outdated": [], "edited": [], "foreign": [], "missing": []}
        for entry in entries:
            if host in entry["hosts"] and not entry.get("seed", False):
                states[classify_entry(root, entry, receipt, hook)].append(entry["target"])
        hosts[host] = states
    seeds = {
        e["target"]: "seed-present" if (root / e["target"]).exists() else "missing"
        for e in entries
        if e.get("seed", False)
    }
    gitignore = root / ".gitignore"
    attributes = root / ".gitattributes"
    return {
        "hosts": hosts,
        "seeds": seeds,
        "config": (root / "sdd/config.json").is_file(),
        "gitignore": gitignore.is_file() and GITIGNORE_BEGIN in gitignore.read_text(encoding="utf-8"),
        "id_ledger": (root / "sdd/tasks/.id_ledger.json").is_file(),
        "gitattributes": attributes.is_file() and GITIGNORE_BEGIN in attributes.read_text(encoding="utf-8"),
        "ledger_hooks": _ledger_hooks_present(root),
        "guard_hook": guard,
        "receipt_version": receipt.get("version"),
    }
