# TASK-4334: Q1 residual — `spec_tools` helper replaces the inline `python -c` blocks in shipped /sdd-spec and /sdd-task

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.2, §3 M6 amendment **Q1**, residual listed under §7 risks)
**Status**: done
**Priority**: medium
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: `issue:cac5c029bd88` (ledger, `feature_gap/minor`, promoted by `/sdd-fix` on 2026-10-14 — the issue is closed by evidence only after this task is implemented and validated, never by filing it)

## Context

Spec rev 0.2 decided (Q1) that every helper a shipped SDD command invokes runs as
`parrot sdd run <name>`, so a foreign repository needs no `python` on `PATH`. TASK-4089
rewrites the `python -m scripts.sdd.<name>` invocations mechanically (rule 5a) and the six
`sdd_meta` one-liners by hand (rule 6). What it cannot rewrite — and inventories as a
residual instead — are the **inline Python blocks** in `/sdd-spec` and `/sdd-task` that have
no helper behind them (verified 2026-10-14 on `0b92bda42`):

| Shipped file | Line | Inline block | Needs |
|---|---|---|---|
| `.claude/commands/sdd-spec.md` | 290 | write `$DR/run.json` (model, codex version, probe output) | stdlib `json` |
| `.claude/commands/sdd-spec.md` | 325 | heredoc: render `$DR/brief.md` from `sdd/templates/design_research.prompt.md` | stdlib |
| `.claude/commands/sdd-spec.md` | 362 | stamp `run.json` with `started_at` / `ended_at` / `exit_code` | stdlib `json` |
| `.claude/commands/sdd-spec.md` | 381 | validate `$DR/suggestions.json` against `design_research.schema.json` | `jsonschema` |
| `.claude/commands/sdd-spec.md` | 393 | path containment check against `$REPO_ROOT` | stdlib `os` |
| `.claude/commands/sdd-spec.md` | 542 | `existing_feature_id(Path('.'), '<feature-name>')` | `scripts.sdd.reserve_ids` (function only — the CLI at `:629-633` has no such mode) |
| `.claude/commands/sdd-spec.md` | 666 | stamp `$STAGE/intake.json` (`feat_id`, `phase: committed`, `updated_at`) | stdlib `json` |
| `.claude/commands/sdd-task.md` | 351 | `hashlib.sha256` one-liner offered as the alternative to `sha256sum` | stdlib |

Each has a twin: `.agent/workflows/sdd-spec.md` (`:294, :329, :366, :385, :397, :546, :670`
— byte parity enforced by `tests/sdd_scripts/test_command_twin_parity.py`), `.agent/workflows/sdd-task.md:347`
(parity twin) and `.agents/skills/sdd-task/SKILL.md:117` (codex skill, not parity-checked, same line).

The `sdd_meta` one-liners (`sdd-spec.md:173`, `:590`, `sdd-task.md:55` + twins) are **not**
this task's: TASK-4299 gives `sdd_meta` a CLI and TASK-4089 rule 6 rewrites them.

**Why a helper and not shell**: the blocks need JSON round-trips, a JSON-Schema validator
and `existing_feature_id()`. A single argparse helper, `scripts/sdd/spec_tools.py`, written
today in the monorepo form (`python -m scripts.sdd.spec_tools …`) slots into the existing
machinery without new rules: TASK-4088 (move B3) carries it into `parrot.sdd.scripts`
exactly like `prune_intake`, and TASK-4089's rule 5a turns the invocation into
`parrot sdd run spec_tools …` once `spec_tools` is in its `MOVED` list. Hence the two index
edges added with this task: **TASK-4088 and TASK-4089 depend on TASK-4334**.

`jsonschema` is already a declared core dependency (`packages/ai-parrot/pyproject.toml:91`,
`jsonschema>=4.20`; 4.26.0 installed), so the helper is safe inside the wheel. The two
templates it reads are shipped to foreign repos at the same `sdd/templates/` path
(TASK-4090 manifest row `sdd/sdd_templates/` → `sdd/templates/`, TASK-4090:410).

## Scope

- Create `scripts/sdd/spec_tools.py` — `main(argv) -> int`, argparse subparsers,
  `prog="python -m scripts.sdd.spec_tools"` (TASK-4088 rewrites `prog` on the move, as it
  does for the other helpers), seven subcommands:

  | Subcommand | Replaces | Contract |
  |---|---|---|
  | `init-run DR --model M --codex-version V [--probe-file PATH]` | `:290` | writes `DR/run.json` = `{model, codex_cli_version, reasoning_effort: "high", timeout_s: 600, probe_output}`; a missing probe file ⇒ `""`; exit 0 |
  | `render-brief DR [--template sdd/templates/design_research.prompt.md]` | `:325` | reads the six `<name>.txt` files, whole-document `str.replace("{{name}}", value)` in the fixed order, refuses (exit 1, message to stderr) when `{{` remains or an input is missing; writes `DR/brief.md` |
  | `stamp-run DR --started-at S --ended-at E --exit-code N` | `:362` | updates `DR/run.json` in place with the three keys; exit 1 if `run.json` is missing (bash keeps its `[ -f … ]` guard) |
  | `validate-suggestions DR [--schema sdd/templates/design_research.schema.json]` | `:381` | `Draft202012Validator(schema).validate(doc)`; prints `<N> suggestions`; exit 1 on `ValidationError` / missing file / invalid JSON |
  | `check-path PATH [--root .]` | `:393` | exit 0 iff `realpath(PATH)` is `root` or inside it; exit 1 otherwise; prints nothing |
  | `commit-intake INTAKE_JSON --feat-id FEAT-NNN` | `:666` | sets `feat_id`, `phase = "committed"`, `updated_at` (UTC, `isoformat()` ending in `+00:00`); exit 1 if missing/invalid |
  | `existing-feature-id LABEL [--root .]` | `:542` | prints the existing `FEAT-<NNN>` or an empty line; exit 0 in both cases (the bash `$(…)` capture relies on it); delegates to `scripts.sdd.reserve_ids.existing_feature_id` |

- Rewrite the eight blocks (and their twins) to call the helper, preserving every surrounding
  control-flow detail: the `|| SKIP_REASON="…"` fallbacks, the `[ -f "$DR/run.json" ]` guard,
  the `EXISTING=$(…)` capture, the `|| REASON="REJECT — path outside repository: <path>"` branch.
  The sdd-task sha256 line becomes `sha256sum <path>` (Linux) or `shasum -a 256 <path>` (macOS) —
  no helper for a hash.
- Add `test_shipped_commands_have_no_inline_python` to `tests/sdd_scripts/test_command_contracts.py`:
  over the five files above, every `python -c "` / `python - ` occurrence must mention
  `scripts.sdd.sdd_meta` (the TASK-4299/4089 lane); after TASK-4089 lands the allowance is
  exercised zero times and the test still passes.
- Unit tests for every subcommand in `tests/sdd_scripts/test_spec_tools.py` (tmp dirs; reuse
  the `schema` / `sample_suggestions` fixture shapes of `test_design_research_templates.py`).
- Keep `test_command_twin_parity.py` green: identical edits on both sides of each twin.

**NOT in scope**
- The `sdd_meta` one-liners (`sdd-spec.md:173`, `:590`, `sdd-task.md:55` + twins) — TASK-4299 + TASK-4089 rule 6.
- Any `parrot sdd run` spelling, any `parrot.sdd.scripts` path, any edit to TASK-4089's rewrite script — this task writes the monorepo form only.
- A CLI mode in `reserve_ids.py` — the helper imports the function; `reserve_ids.py` is untouched.
- The non-shipped `.codex/` / `_subagent_data/` copies and `scripts/sdd/__init__.py`.
- Spec text; the rev 0.2 §7 risk line is retired by the `/sdd-fix` close, not by this task.

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `scripts/sdd/spec_tools.py` | CREATE | argparse helper, seven subcommands |
| `tests/sdd_scripts/test_spec_tools.py` | CREATE | one test module, every subcommand's happy + failure path |
| `.claude/commands/sdd-spec.md` | MODIFY | blocks at `:290, :325, :362, :381, :393, :542, :666` |
| `.agent/workflows/sdd-spec.md` | MODIFY | same seven blocks (`:294, :329, :366, :385, :397, :546, :670`) — byte-identical edits |
| `.claude/commands/sdd-task.md` | MODIFY | `:351` sha256 alternative |
| `.agent/workflows/sdd-task.md` | MODIFY | `:347` same edit |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | `:117` same edit |
| `tests/sdd_scripts/test_command_contracts.py` | MODIFY | add `test_shipped_commands_have_no_inline_python` |

## Codebase Contract (Anti-Hallucination)

All anchors verified 2026-10-14 on `dev` @ `0b92bda42`.

### Verified Imports

```python
from scripts.sdd.reserve_ids import existing_feature_id   # scripts/sdd/reserve_ids.py:420
from jsonschema import Draft202012Validator, ValidationError  # jsonschema 4.26.0 installed; core dep pyproject.toml:91 "jsonschema>=4.20"
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
```

### Existing Signatures

```python
# scripts/sdd/reserve_ids.py
def existing_feature_id(root: Path, label: str) -> tuple[str, str] | None:   # :420 — (feature_id, spec_path) or None
def main(argv: list[str] | None = None) -> int:                              # :610 — flags only: --kind --count --base-branch --label --max-retries (:629-633)

# sdd/templates/design_research.prompt.md — six placeholders, braces included in the body only (header comment spells them WITHOUT braces, on purpose: a whole-document replace must not corrupt it — TASK-3099):
#   {{problem_statement}} {{constraints_and_goals}} {{recommended_option_or_scope}} {{code_context_paths}} {{open_questions}} {{question}}
# sdd/templates/design_research.schema.json — JSON Schema draft 2020-12 (tests/sdd_scripts/test_design_research_templates.py:58)

# tests/sdd_scripts/test_design_research_templates.py
_REPO_ROOT = Path(__file__).resolve().parents[2]   # :12
_TPL / _SCHEMA / _PROMPT / _PLACEHOLDERS           # :13-21 — reuse the same constants, do not duplicate the placeholder set
@pytest.fixture schema() / sample_suggestions()    # :24-56 — copy the sample shape (summary + suggestions[id,kind,title,rationale,affected_paths,risk,confidence])

# tests/sdd_scripts/test_command_twin_parity.py
_TWINNED = ("sdd-spec", "sdd-task")                # :22 — command ↔ .agent/workflows twin, byte parity after frontmatter strip + one substitution (:28-35)

# tests/sdd_scripts/test_command_contracts.py
_REPO_ROOT = Path(__file__).resolve().parents[2]   # :19 — existing tests read `.claude/commands/*.md` via this root
```

### Shipped-markdown anchors (occurrence count per file — all `1`, both twins)

```
.claude/commands/sdd-spec.md (= .agent/workflows/sdd-spec.md + 4 lines of frontmatter)
  :293  PROBE_OUTPUT="$(cat "$DR/probe.txt" 2>/dev/null || echo "")"       ← init-run block follows (:294-304)
  :325  python - "$DR" <<'PY' || SKIP_REASON="brief rendering failed"       ← render-brief heredoc (:325-341, ends with PY)
  :361  if [ -f "$DR/run.json" ]; then                                      ← stamp-run block inside (:362-369)
  :385  jsonschema.Draft202012Validator(s).validate(d)                      ← validate-suggestions block (:381-387)
  :396  root = os.path.realpath('$REPO_ROOT')                                ← check-path block (:393-398)
  :544  from scripts.sdd.reserve_ids import existing_feature_id              ← existing-feature-id block (:542-546)
  :665  # Set feat_id and phase: committed in intake.json BEFORE staging     ← commit-intake block (:666-673)
.claude/commands/sdd-task.md:351 / .agent/workflows/sdd-task.md:347 / .agents/skills/sdd-task/SKILL.md:117
        `python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <path>`.
```

### Does NOT Exist (create here, or never)

- `scripts/sdd/spec_tools.py`, `scripts/sdd/design_research.py` — create the former only.
- `parrot.sdd.*` of any kind on `dev` — the package root is TASK-4070/4085's; do not import it, do not create it.
- A `--existing` / `existing` mode in `reserve_ids.main` — never add one; import the function instead.
- A `sdd_meta` CLI (`parse` / `taxonomy` / `resolve-flow`) — TASK-4299; leave its one-liners alone.
- `parrot sdd run` — TASK-4091 (CLI) + TASK-4089 (rewrite); this task never writes that spelling.
- `datetime.utcnow()` in new code — deprecated; use `datetime.now(timezone.utc).isoformat()` (yields the same `+00:00` suffix the old block appended by hand).

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/spec_tools.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_spec_tools.py", "action": "CREATE"},
    {"path": ".claude/commands/sdd-spec.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-spec.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-task.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-task.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-task/SKILL.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_command_contracts.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/reserve_ids.py#existing_feature_id"
  ]
}
```

## Implementation Notes

- **Edit both twins with the same patch.** The parity test strips the frontmatter and applies
  one known substitution; anything else that differs fails it. Apply each hunk to
  `.claude/commands/sdd-spec.md` and then the identical hunk to `.agent/workflows/sdd-spec.md`
  (line numbers +4). Same for the `sdd-task` pair.
- **Preserve the shell contract around each block.** Exit codes drive `SKIP_REASON` and
  `REASON`; `EXISTING=$(…)` must capture an empty string (not an error) when no id exists.
  Every helper failure goes to **stderr** so `$(…)` captures stay clean.
- **`render-brief` is the TASK-3099 corruption trap**: whole-document `str.replace` on the
  `{{name}}` form only; the final check is `"{{" not in rendered` exactly as today.
- **`check-path` prints nothing** — the bash `||` branch is the only consumer.
- **Keep the heredoc style out**: the new markdown invocations are single lines
  (`python -m scripts.sdd.spec_tools <sub> …`) so TASK-4089's rule 5a regex
  (`\bpython3?[ \t]+-m[ \t]+scripts\.sdd\.(N)\b`) matches each one.
- **Line budget**: the helper is one file; keep each handler ≤ 15 lines, no shared state.

## Implementation Blueprint

### `scripts/sdd/spec_tools.py` (CREATE)

```python
"""Helpers behind /sdd-spec's design-research and intake sub-flows (FEAT-633 Q1 residual).

Replaces the inline ``python -c`` blocks of the shipped commands so a foreign repository
needs no interpreter on PATH: TASK-4088 moves this module into ``parrot.sdd.scripts`` and
TASK-4089 rewrites the invocations to ``parrot sdd run spec_tools …``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from scripts.sdd.reserve_ids import existing_feature_id

BRIEF_INPUTS = ("problem_statement", "constraints_and_goals", "recommended_option_or_scope",
                "code_context_paths", "open_questions", "question")
DEFAULT_PROMPT = Path("sdd/templates/design_research.prompt.md")
DEFAULT_SCHEMA = Path("sdd/templates/design_research.schema.json")


def _fail(msg: str) -> int:
    print(f"spec_tools: {msg}", file=sys.stderr)
    return 1


def cmd_init_run(a: argparse.Namespace) -> int:
    probe = Path(a.probe_file).read_text(encoding="utf-8") if a.probe_file and Path(a.probe_file).is_file() else ""
    payload = {"model": a.model, "codex_cli_version": a.codex_version, "reasoning_effort": "high",
               "timeout_s": 600, "probe_output": probe}
    (Path(a.dir) / "run.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


def cmd_render_brief(a: argparse.Namespace) -> int:
    # FILL IN: read a.template; for each BRIEF_INPUTS name read <dir>/<name>.txt (.strip()) —
    # missing file ⇒ _fail(...); str.replace("{{" + name + "}}", value) in BRIEF_INPUTS order;
    # "{{" in rendered ⇒ _fail("unfilled placeholder remains"); write <dir>/brief.md — bounded by AC-2
    ...


def cmd_stamp_run(a: argparse.Namespace) -> int:
    # FILL IN: load <dir>/run.json (missing ⇒ _fail), set started_at/ended_at/exit_code=int, dump indent=2 — AC-3
    ...


def cmd_validate_suggestions(a: argparse.Namespace) -> int:
    # FILL IN: load schema + <dir>/suggestions.json; Draft202012Validator(schema).validate(doc);
    # print(f"{len(doc['suggestions'])} suggestions"); except (ValidationError, OSError, ValueError, KeyError) ⇒ _fail — AC-4
    ...


def cmd_check_path(a: argparse.Namespace) -> int:
    p, root = os.path.realpath(a.path), os.path.realpath(a.root)
    return 0 if p == root or p.startswith(root + os.sep) else 1


def cmd_commit_intake(a: argparse.Namespace) -> int:
    # FILL IN: load a.intake_json (missing/invalid ⇒ _fail); d["feat_id"]=a.feat_id; d["phase"]="committed";
    # d["updated_at"]=datetime.now(timezone.utc).isoformat(); dump indent=2 — AC-5
    ...


def cmd_existing_feature_id(a: argparse.Namespace) -> int:
    found = existing_feature_id(Path(a.root), a.label)
    print(found[0] if found else "")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m scripts.sdd.spec_tools", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    # FILL IN: one add_parser per subcommand with the exact flags of the Scope table; set_defaults(func=cmd_*)
    ...
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why**: one module, seven thin handlers, no shared state — so TASK-4088 moves it with a
`git mv` + `prog` rewrite like the others, and TASK-4089's regex sees plain
`python -m scripts.sdd.spec_tools` tokens.

### `.claude/commands/sdd-spec.md` and `.agent/workflows/sdd-spec.md` (MODIFY — same hunks on both)

```bash
# 1. init-run — REPLACE the `python -c "` … `" "$MODEL" "$CODEX_VERSION" "$PROBE_OUTPUT" "$DR/run.json"` block
#    that follows the anchor `PROBE_OUTPUT="$(cat "$DR/probe.txt" 2>/dev/null || echo "")"` (occurrences: 1) with:
  python -m scripts.sdd.spec_tools init-run "$DR" --model "$MODEL" --codex-version "$CODEX_VERSION" --probe-file "$DR/probe.txt"
#    then DELETE the now-unused `PROBE_OUTPUT=…` line (the helper reads the file itself).

# 2. render-brief — REPLACE the whole heredoc from `python - "$DR" <<'PY' || SKIP_REASON="brief rendering failed"`
#    (occurrences: 1) through its closing `PY` line with:
  python -m scripts.sdd.spec_tools render-brief "$DR" || SKIP_REASON="brief rendering failed"

# 3. stamp-run — inside `if [ -f "$DR/run.json" ]; then` (occurrences: 1) REPLACE the `python -c "` block with:
    python -m scripts.sdd.spec_tools stamp-run "$DR" --started-at "$STARTED_AT" --ended-at "$ENDED_AT" --exit-code "$rc"

# 4. validate-suggestions — REPLACE the block containing `jsonschema.Draft202012Validator(s).validate(d)` (occurrences: 1) with:
  python -m scripts.sdd.spec_tools validate-suggestions "$DR" || SKIP_REASON="suggestions.json failed schema validation"

# 5. check-path — REPLACE the block containing `root = os.path.realpath('$REPO_ROOT')` (occurrences: 1) with:
   python -m scripts.sdd.spec_tools check-path "<path>" --root "$REPO_ROOT" \
     || REASON="REJECT — path outside repository: <path>"

# 6. existing-feature-id — REPLACE the `EXISTING=$(python -c "` block containing
#    `from scripts.sdd.reserve_ids import existing_feature_id` (occurrences: 1) with:
     EXISTING=$(python -m scripts.sdd.spec_tools existing-feature-id "<feature-name>")

# 7. commit-intake — below `# Set feat_id and phase: committed in intake.json BEFORE staging` (occurrences: 1)
#    REPLACE the `python -c "` block with:
  python -m scripts.sdd.spec_tools commit-intake "$STAGE/intake.json" --feat-id "$FEAT_ID"
```
**Why**: every replacement keeps the exit-code consumer that already exists in the shell
(`|| SKIP_REASON`, `|| REASON`, `$(…)`), so the command's documented behaviour is unchanged
while no interpreter is spawned by the markdown itself. Keep the indentation of each
original line — the twins must stay byte-identical after the frontmatter.

### `sdd-task` twins (MODIFY — `.claude/commands/sdd-task.md:351`, `.agent/workflows/sdd-task.md:347`, `.agents/skills/sdd-task/SKILL.md:117`)

```markdown
# REPLACE (occurrences: 1 per file — anchor `import hashlib,sys`):
  `python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <path>`.
# WITH:
  `shasum -a 256 <path>` on macOS (both print the hash first; take the first field).
```
**Why**: the preceding line already offers `sha256sum <path>`; the portable alternative is
the BSD tool, not an interpreter. The bootstrap preflight (rev 0.2 C14b) already requires
one of the two.

### `tests/sdd_scripts/test_command_contracts.py` (MODIFY — append)

```python
# AFTER — append at end of file (verified: last test is test_no_legacy_naming_template_remains, :78)
_SHIPPED_WITH_INLINE_PYTHON_BAN = (
    ".claude/commands/sdd-spec.md", ".agent/workflows/sdd-spec.md",
    ".claude/commands/sdd-task.md", ".agent/workflows/sdd-task.md", ".agents/skills/sdd-task/SKILL.md",
)
_INLINE_PY = re.compile(r'python3?\s+(?:-c\s+"|-\s+(?:"\$\w+"\s+)?<<)')


@pytest.mark.parametrize("rel", _SHIPPED_WITH_INLINE_PYTHON_BAN)
def test_shipped_commands_have_no_inline_python(rel: str) -> None:
    """FEAT-633 Q1: a shipped command never embeds Python — only the sdd_meta one-liners
    remain, and TASK-4089 rule 6 retires those (then this allowance is exercised zero times)."""
    lines = (_REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
    offenders = []
    for i, line in enumerate(lines):
        if _INLINE_PY.search(line):
            window = "\n".join(lines[i : i + 4])
            # FILL IN: allow iff "scripts.sdd.sdd_meta" in window; else offenders.append(f"{rel}:{i + 1}") — AC-6
            ...
    assert not offenders, offenders
```
**Why**: the ban is what keeps the residual from coming back after TASK-4089 — a future
edit that re-introduces `python -c` fails this test on `dev`, before any packaging step.

### Steps (in order)

1. Write `scripts/sdd/spec_tools.py` from the block; complete the five `FILL IN` handlers and
   `build_parser` — flags exactly as the Scope table (they are the public contract the markdown
   relies on).
2. Write `tests/sdd_scripts/test_spec_tools.py`; run it green **before** touching markdown.
3. Apply hunks 1–7 to `.claude/commands/sdd-spec.md`, then the identical hunks to
   `.agent/workflows/sdd-spec.md`; run `test_command_twin_parity.py`.
4. Apply the sha256 edit to the three `sdd-task` files; run the parity test again.
5. Append the contract test; run `test_command_contracts.py` — it must pass with exactly the
   three `sdd_meta` allowances exercised (`sdd-spec.md:173` and `:590` per twin, `sdd-task.md:55` per twin).
6. `ruff check --fix` on the two new Python files; run the Validation Commands.

### FILL IN checklist

- [ ] `cmd_render_brief`, `cmd_stamp_run`, `cmd_validate_suggestions`, `cmd_commit_intake` bodies
- [ ] `build_parser` subparsers + flags
- [ ] `test_spec_tools.py` bodies (see Test Specification)
- [ ] allowance branch in `test_shipped_commands_have_no_inline_python`

## Acceptance Criteria

- [ ] **AC-1** `python -m scripts.sdd.spec_tools --help` lists the seven subcommands; `init-run` writes the exact five-key `run.json` of the old block (probe file missing ⇒ `""`).
- [ ] **AC-2** `render-brief` reproduces today's heredoc byte-for-byte on a fixture `$DR` (six inputs, real template) and exits 1 with a stderr message when a placeholder stays unfilled or an input is missing; the template's un-braced header comment is untouched.
- [ ] **AC-3** `stamp-run` adds `started_at` / `ended_at` / `exit_code` (int) to an existing `run.json`; exits 1 when it is absent.
- [ ] **AC-4** `validate-suggestions` prints `<N> suggestions` for the `sample_suggestions` shape and exits 1 for an unknown `kind` (same case `test_unknown_kind_rejected` covers).
- [ ] **AC-5** `check-path` exits 0 for root and descendants and 1 for `..`-escapes and symlinks out of root; `commit-intake` writes `feat_id`, `phase: committed`, `updated_at` ending in `+00:00`; `existing-feature-id` prints the id for a slug that owns one and an empty line otherwise, exit 0 both ways.
- [ ] **AC-6** No `python -c` / `python -` heredoc remains in the five shipped files except the `sdd_meta` one-liners; `test_shipped_commands_have_no_inline_python` encodes exactly that; `grep -c 'python -c' .claude/commands/sdd-spec.md` is `3` (:173, the prose at :189, :590) and `1` for `sdd-task.md`.
- [ ] **AC-7** `test_command_twin_parity.py` passes; every new markdown invocation is a single line of the form `python -m scripts.sdd.spec_tools <sub> …` (TASK-4089 rule 5a shape).
- [ ] **AC-8** `reserve_ids.py`, `sdd_meta.py`, `sdd/templates/*` and `scripts/sdd/__init__.py` are byte-unchanged.

## Validation Commands

- `pytest tests/sdd_scripts/test_spec_tools.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_design_research_templates.py -q`

## Test Specification

### `tests/sdd_scripts/test_spec_tools.py` (CREATE)

- `test_init_run_writes_expected_keys` / `test_init_run_missing_probe_is_empty_string`
- `test_render_brief_matches_legacy_heredoc` — render with the real template through a copy of the
  old inline code (kept inside the test as the oracle) and through the helper; assert equality.
- `test_render_brief_refuses_unfilled_placeholder` / `test_render_brief_refuses_missing_input` (exit 1, stderr, no `brief.md`).
- `test_stamp_run_updates_in_place` / `test_stamp_run_missing_run_json_exits_1`.
- `test_validate_suggestions_ok` (uses the `sample_suggestions` shape; stdout `2 suggestions`) / `test_validate_suggestions_rejects_unknown_kind`.
- `test_check_path_inside_and_outside` (parametrized: root, child, `../x`, symlink pointing outside via `tmp_path`).
- `test_commit_intake_stamps_fields` (`updated_at` ends with `+00:00`) / `test_commit_intake_missing_exits_1`.
- `test_existing_feature_id_found_and_empty` — monkeypatch `scripts.sdd.spec_tools.existing_feature_id`
  to return `("FEAT-633", "sdd/specs/x.spec.md")` then `None`; assert stdout `FEAT-633\n` then `\n`, exit 0 both.
- All invocations go through `main([...])` with `capsys`; no subprocess.

### `tests/sdd_scripts/test_command_contracts.py` (MODIFY)

- `test_shipped_commands_have_no_inline_python[<5 files>]` as in the blueprint.

## Agent Instructions

- Touch only the eight files listed. Do not edit `scripts/sdd/reserve_ids.py` (the only
  thing you need from it is the import).
- Both twins get the same hunk, in the same order; the parity test is the gate — run it
  after every markdown step, not just at the end.
- Do not "improve" the markdown around the blocks (indentation, comments, the `⚠️` strings):
  TASK-4089 relies on this text; keep the diff to the replaced blocks.
- If the real `design_research.prompt.md` renders differently through the helper than through
  the old heredoc (AC-2 oracle), the helper is wrong — never adjust the template.
- Write the Completion Note with the `grep -c 'python -c'` numbers per file after your change.

## Completion Note

**Completed**: 2026-10-15 — implementing commit `d14e9339b` on `feat-FEAT-633-parrot-installer`
(base `f64c563b1`), verification `verified`.

- **Helper**: `scripts/sdd/spec_tools.py` (195 lines, seven subcommands; `jsonschema` + stdlib +
  `scripts.sdd.reserve_ids.existing_feature_id`). `reserve_ids.py`, `sdd_meta.py`,
  `sdd/templates/*`, `scripts/sdd/__init__.py` untouched (AC-8).
- **`python -c` counts after the change (AC-6)**: `.claude/commands/sdd-spec.md` = 3
  (`:173` resolve_flow, `:189` prose, `:590` parse_taxonomy), `.agent/workflows/sdd-spec.md` = 3,
  `.claude/commands/sdd-task.md` = 1 (`:55` parse), `.agent/workflows/sdd-task.md` = 1,
  `.agents/skills/sdd-task/SKILL.md` = 0. All remaining ones import `scripts.sdd.sdd_meta` —
  the three allowances `test_shipped_commands_have_no_inline_python` still exercises (per twin).
- **Validation**: `test_spec_tools.py` (17), `test_command_contracts.py`, `test_command_twin_parity.py`,
  `test_design_research_templates.py` → 48 passed; full `tests/sdd_scripts` → 433 passed; `ruff` + `black` clean.
  AC-2 oracle: the helper's `brief.md` equals the retired heredoc's output on the real template.
- **Behavioural note**: `init-run` reads `$DR/probe.txt` itself, so the `PROBE_OUTPUT=` shell
  variable was removed (no other reference existed). `commit-intake` uses
  `datetime.now(timezone.utc).isoformat()` — same `+00:00` shape as the old `utcnow()+'+00:00'`.
- **Cross-task reminders (already written into the tasks on `dev` @ `f64c563b1`)**: TASK-4088 moves
  `spec_tools.py` (20th module; rewrite `prog` and the `reserve_ids` import); TASK-4089 has
  `spec_tools` in `MOVED` (20 names) and its residual bullet marked RETIRED; TASK-4091's wheel-only
  test needs a `Scenario` per `spec_tools` subcommand.
- **Ledger**: closes `issue:cac5c029bd88` (two-key: task completed + `.claude/commands/sdd-spec.md` in the diff).
