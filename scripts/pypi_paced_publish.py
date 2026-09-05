#!/usr/bin/env python
"""Paced first-publish of NEW PyPI distributions, one at a time, on a timer.

PyPI allows an account to create at most **4 new projects per 24 hours**
(https://github.com/pypi/support/issues/10572). Uploading a new file to a
project that already exists does NOT count. This script therefore:

1. (prelude, immediately) uploads any files whose project already exists —
   e.g. the sdists of satellites whose wheel went up before the 429 hit;
2. waits ``--start-after`` (default 24h from the first run);
3. uploads the pending *new* projects ONE per ``--interval`` (default
   6h15m — 6h keeps 4/day, the 15 min margin keeps the 4th-previous upload
   clearly outside a rolling 24h window), in the order given.

Every upload runs ``twine upload --skip-existing`` (credentials from
``~/.pypirc``), so a re-run is always safe. Progress and the computed
schedule live in a JSON state file; killing and restarting the script
resumes at the same schedule. A 429 does not advance the queue — the
script backs off ``--backoff`` (default 1h) and retries the same package.

Usage::

    source .venv/bin/activate
    python scripts/pypi_paced_publish.py --dry-run          # print the plan
    systemd-inhibit --what=sleep:idle --why="PyPI paced publish" \\
        python scripts/pypi_paced_publish.py                 # run for real

Run it inside tmux/nohup so a closed terminal does not kill it, and under
``systemd-inhibit`` (or disable suspend) so the box does not sleep through
a slot — missed slots are simply run as soon as the script wakes.
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST = REPO_ROOT / "dist"
STATE_FILE = REPO_ROOT / "artifacts" / "logs" / "pypi_paced_publish.state.json"
LOG_FILE = REPO_ROOT / "artifacts" / "logs" / "pypi_paced_publish.log"

VERSION = "0.2.0"

# Projects whose wheel already exists on PyPI (created 2026-09-05 before the
# 429). Only their sdist is missing — free to upload, no new project created.
PRELUDE_GLOBS: list[str] = [
    f"ai_parrot_client_amazon-{VERSION}.tar.gz",
    f"ai_parrot_client_anthropic-{VERSION}.tar.gz",
    f"ai_parrot_client_gemma4-{VERSION}.tar.gz",
    f"ai_parrot_client_google-{VERSION}.tar.gz",
]

# NEW projects, in publish order. `local` precedes `vllm` because
# ai-parrot-client-vllm depends on ai-parrot-client-local.
NEW_PROJECTS: list[tuple[str, str]] = [
    # (PyPI project name, dist/ glob)
    ("ai-parrot-client-openai", f"ai_parrot_client_openai-{VERSION}*"),
    ("ai-parrot-client-nvidia", f"ai_parrot_client_nvidia-{VERSION}*"),
    ("ai-parrot-client-grok", f"ai_parrot_client_grok-{VERSION}*"),
    ("ai-parrot-client-meta", f"ai_parrot_client_meta-{VERSION}*"),
    ("ai-parrot-client-local", f"ai_parrot_client_local-{VERSION}*"),
    ("ai-parrot-client-groq", f"ai_parrot_client_groq-{VERSION}*"),
    ("ai-parrot-client-hf", f"ai_parrot_client_hf-{VERSION}*"),
    ("ai-parrot-client-moonshot", f"ai_parrot_client_moonshot-{VERSION}*"),
    ("ai-parrot-client-vllm", f"ai_parrot_client_vllm-{VERSION}*"),
    ("ai-parrot-client-openrouter", f"ai_parrot_client_openrouter-{VERSION}*"),
    ("ai-parrot-client-zai", f"ai_parrot_client_zai-{VERSION}*"),
    ("ai-parrot-openlit-bridge", f"ai_parrot_openlit_bridge-{VERSION}*"),
]

_DURATION = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")

log = logging.getLogger("pypi_paced_publish")


def parse_duration(text: str) -> timedelta:
    """Parse ``1d``, ``24h``, ``6h15m``, ``90s`` … into a timedelta."""
    match = _DURATION.fullmatch(text.strip())
    if not match or not any(match.groups()):
        raise argparse.ArgumentTypeError(f"bad duration {text!r} (e.g. 24h, 6h15m)")
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


@dataclass
class State:
    """Persisted progress; the schedule is fixed on the first real run."""

    schedule: dict[str, str] = field(default_factory=dict)  # project -> ISO time
    done: list[str] = field(default_factory=list)
    prelude_done: bool = False

    @classmethod
    def load(cls, path: Path) -> "State":
        if path.exists():
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def twine_cmd() -> list[str]:
    """Prefer an installed twine, else run it through uvx."""
    if shutil.which("twine"):
        return ["twine"]
    if shutil.which("uvx"):
        return ["uvx", "twine"]
    sys.exit("error: neither `twine` nor `uvx` found on PATH")


def project_exists(name: str, version: str = VERSION) -> bool:
    """True if ``name`` has a release ``version`` on PyPI."""
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        log.warning("PyPI %s -> HTTP %s (treating as missing)", name, exc.code)
        return False
    except urllib.error.URLError as exc:
        log.warning("PyPI %s unreachable: %s (treating as missing)", name, exc)
        return False


def upload(files: list[Path], dry_run: bool) -> str:
    """Run ``twine upload --skip-existing``; return ``ok`` | ``429`` | ``error``."""
    cmd = [*twine_cmd(), "upload", "--skip-existing", "--non-interactive",
           *(str(f) for f in files)]
    log.info("%s%s", "[dry-run] " if dry_run else "", " ".join(cmd))
    if dry_run:
        return "ok"
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    output = (proc.stdout + proc.stderr).strip()
    for line in output.splitlines():
        log.info("  twine: %s", line)
    if proc.returncode == 0:
        return "ok"
    if "429" in output or "Too Many Requests" in output:
        return "429"
    return "error"


def resolve(pattern: str) -> list[Path]:
    """Expand a dist/ glob; exit loudly if nothing matches."""
    files = sorted(Path(p) for p in glob.glob(str(DIST / pattern)))
    if not files:
        sys.exit(f"error: no files match dist/{pattern} — run `make build-clients`")
    return files


def sleep_until(when: datetime, dry_run: bool) -> None:
    """Block until ``when`` (UTC), logging the wait; no-op in dry-run."""
    remaining = (when - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        return
    log.info("sleeping %s until %s", timedelta(seconds=int(remaining)),
             when.astimezone().strftime("%a %Y-%m-%d %H:%M %Z"))
    if dry_run:
        return
    # Sleep in slices so Ctrl-C is responsive and clock jumps (suspend) are
    # re-evaluated instead of overshooting.
    while (remaining := (when - datetime.now(timezone.utc)).total_seconds()) > 0:
        time.sleep(min(remaining, 300))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start-after", type=parse_duration, default="24h",
                        help="delay before the FIRST new project (default 24h)")
    parser.add_argument("--interval", type=parse_duration, default="6h15m",
                        help="gap between new projects (default 6h15m)")
    parser.add_argument("--backoff", type=parse_duration, default="1h",
                        help="wait after a 429 before retrying (default 1h)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan, upload nothing, sleep nothing")
    parser.add_argument("--reset", action="store_true",
                        help="discard the saved schedule/progress first")
    args = parser.parse_args()
    if isinstance(args.start_after, str):
        args.start_after = parse_duration(args.start_after)
    if isinstance(args.interval, str):
        args.interval = parse_duration(args.interval)
    if isinstance(args.backoff, str):
        args.backoff = parse_duration(args.backoff)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  *([] if args.dry_run else [logging.FileHandler(LOG_FILE)])],
    )

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
    state = State.load(STATE_FILE)

    # --- prelude: files for projects that already exist (not rate-limited)
    if not state.prelude_done:
        files = [f for pat in PRELUDE_GLOBS for f in resolve(pat)]
        log.info("prelude: %d sdist(s) for already-existing projects", len(files))
        if upload(files, args.dry_run) == "ok":
            state.prelude_done = True
            if not args.dry_run:
                state.save(STATE_FILE)
        else:
            log.error("prelude upload failed — fix and re-run (nothing else was touched)")
            return 1

    # --- fixed schedule, computed once
    if not state.schedule:
        first = datetime.now(timezone.utc) + args.start_after
        pending = [name for name, _ in NEW_PROJECTS if not project_exists(name)]
        state.schedule = {
            name: (first + i * args.interval).isoformat()
            for i, name in enumerate(pending)
        }
        if not args.dry_run:
            state.save(STATE_FILE)
    log.info("plan (%d new projects, one per %s):", len(state.schedule), args.interval)
    for name, iso in state.schedule.items():
        mark = "done" if name in state.done else "    "
        log.info("  %s  %-28s %s", mark, name,
                 datetime.fromisoformat(iso).astimezone().strftime("%a %d %H:%M"))
    if args.dry_run:
        return 0

    # --- paced creation of new projects
    by_name = dict(NEW_PROJECTS)
    for name, iso in state.schedule.items():
        if name in state.done:
            continue
        if project_exists(name):
            log.info("%s already on PyPI — marking done", name)
            state.done.append(name)
            state.save(STATE_FILE)
            continue
        sleep_until(datetime.fromisoformat(iso), dry_run=False)
        files = resolve(by_name[name])
        while True:
            result = upload(files, dry_run=False)
            if result == "ok" and project_exists(name):
                log.info("%s published", name)
                state.done.append(name)
                state.save(STATE_FILE)
                break
            if result == "429":
                log.warning("429 on %s — backing off %s", name, args.backoff)
            else:
                log.error("upload of %s failed (%s) — retrying in %s",
                          name, result, args.backoff)
            sleep_until(datetime.now(timezone.utc) + args.backoff, dry_run=False)

    log.info("all %d new projects published — safe to tag/push and create the "
             "GitHub Release", len(state.schedule))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted — progress saved; re-run to resume", file=sys.stderr)
        sys.exit(130)
