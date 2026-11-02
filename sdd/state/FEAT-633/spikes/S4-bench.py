"""S4 re-measure (FEAT-633 R6): launcher overhead incl. the project-venv trust gate (POSIX only).

Usage (run with the venv's own python, which plays the "managed" venv through a symlinked PARROT_HOME):
    <venv>/bin/python S4-bench.py <scratch-dir> <worktree> [runs=30]
"""
import json, os, shutil, statistics, subprocess, sys, time
from pathlib import Path

S = Path(sys.argv[1]); WT = Path(sys.argv[2]); RUNS = int(sys.argv[3]) if len(sys.argv) > 3 else 30
MAIN_VENV = Path(sys.prefix)
PY = str(MAIN_VENV / "bin" / "python3")
SRC = str(WT / "packages/ai-parrot/src")

def mkrepo(p: Path, venv: bool) -> Path:
    if p.exists(): shutil.rmtree(p)
    p.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(p)], check=True)
    if venv:
        b = p / ".venv" / "bin"; b.mkdir(parents=True)
        shutil.copy(MAIN_VENV / "pyvenv.cfg", p / ".venv" / "pyvenv.cfg")
        for name, fn in (("wikitoolkit", "main_wikitoolkit"), ("parrot", "main_parrot")):
            f = b / name
            f.write_text(f"#!{PY}\nimport os, sys\nif os.environ.get('BENCH_VERIFY'): sys.stderr.write('REEXEC ' + sys.argv[0] + '\\n')\n"
                         f"from parrot.launcher import {fn}\nsys.exit({fn}())\n")
            f.chmod(0o755)
    return p

proj = mkrepo(S / "proj", True)
bare = mkrepo(S / "bare", False)
home = S / "home"; home.mkdir(exist_ok=True)
if not (home / "venv").exists(): (home / "venv").symlink_to(MAIN_VENV)
nohome = S / "nohome"; nohome.mkdir(exist_ok=True)

base = {k: v for k, v in os.environ.items() if k not in {
    "PARROT_PROJECT", "CLAUDE_PROJECT_DIR", "VIRTUAL_ENV", "PARROT_VENV", "PARROT_HOME", "PARROT_LAUNCHER_RESOLVED", "PYTHONPATH"}}
base["PYTHONPATH"] = SRC
payload = json.dumps({"session_id": "r6", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                      "tool_input": {"command": "ls"}, "cwd": str(proj)}).encode()

W = "import sys; sys.argv=['wikitoolkit','claude-hook']; from parrot.launcher import main_wikitoolkit; sys.exit(main_wikitoolkit())"
OLD = "import sys; sys.argv=['wikitoolkit','claude-hook']; from parrot.knowledge.wiki.entry import main; main()"
P = "import sys; sys.argv=['parrot','sdd','run','worktree_environment','--hook']; from parrot.launcher import main_parrot; sys.exit(main_parrot())"
sdd_payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(proj)}).encode()

cases = [
    ("python -c pass (floor)", ["-c", "pass"], nohome, proj, payload),
    ("claude-hook via old entry (non-managed)", ["-c", OLD], nohome, proj, payload),
    ("claude-hook via launcher, non-managed", ["-c", W], nohome, proj, payload),
    ("claude-hook via launcher, managed, no project venv", ["-c", W], home, bare, payload),
    ("claude-hook via launcher, managed -> project re-exec", ["-c", W], home, proj, payload),
    ("sdd hook baseline: python -m worktree_environment --hook", ["-m", "parrot.sdd.scripts.worktree_environment", "--hook"], nohome, proj, sdd_payload),
    ("sdd hook via launcher, non-managed", ["-c", P], nohome, proj, sdd_payload),
    ("sdd hook via launcher, managed -> project re-exec", ["-c", P], home, proj, sdd_payload),
]

def run(args, ph, cwd, data, extra=None):
    env = dict(base, PARROT_HOME=str(ph), **(extra or {}))
    t = time.perf_counter()
    r = subprocess.run([PY, *args], input=data, cwd=cwd, env=env, capture_output=True)
    return (time.perf_counter() - t) * 1000, r

# verify each case's path before timing
for name, args, ph, cwd, data in cases:
    _, r = run(args, ph, cwd, data, {"BENCH_VERIFY": "1"})
    print(f"# verify {name}: rc={r.returncode} reexec={'REEXEC' in r.stderr.decode()} stderr={r.stderr.decode().strip()[:160]!r}")

rows = []
for name, args, ph, cwd, data in cases:
    for _ in range(3): run(args, ph, cwd, data)
    xs = sorted(run(args, ph, cwd, data)[0] for _ in range(RUNS))
    rows.append((name, statistics.median(xs), xs[int(0.95 * (len(xs) - 1))]))

sys.path.insert(0, SRC)
from parrot import launcher
N = 200
t = time.perf_counter()
for _ in range(N): assert launcher._project_venv_trusted(proj / ".venv", "wikitoolkit")
gate = (time.perf_counter() - t) * 1000 / N
t = time.perf_counter()
for _ in range(N): launcher.resolve_venv("wikitoolkit", argv=[], env={"PARROT_HOME": str(home)}, cwd=proj)
resolve = (time.perf_counter() - t) * 1000 / N

print(f"\nruns={RUNS} python={sys.version.split()[0]} git={subprocess.run(['git','--version'],capture_output=True,text=True).stdout.strip()}")
print("| Case | Median (ms) | p95 (ms) |\n|---|---|---|")
for n, m, p in rows: print(f"| {n} | {m:.1f} | {p:.1f} |")
print(f"| trust gate `_project_venv_trusted` (in-process, {N} calls) | {gate:.2f} per call | — |")
print(f"| `resolve_venv` managed->project incl. gate (in-process, {N} calls) | {resolve:.2f} per call | — |")
