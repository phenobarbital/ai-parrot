# TASK-4573: Committable agent assets: .gitignore whitelist, base Jira template, base skill

**Feature**: FEAT-715 — FirefliesInsightsAgent
**Spec**: `sdd/specs/fireflies-insights-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (assets half) and **C14**. `/agents/` is git-ignored wholesale
(`.gitignore:297`, deliberately: *"only NEW agent files are ignored again"*), and
`templates/` at `:274` would catch the template dir too. A plain negation **cannot**
work — git never re-includes a path under an excluded *directory* — so the rule becomes
`/agents/*` plus a narrow whitelist. This exact block was verified in a scratch repo
during `/sdd-brainstorm`: the whitelisted subtrees become trackable, `agents/porygon/**`
stays ignored, and a non-whitelisted file inside this agent's own dir stays ignored.

The task also fixes the **template parameter contract** that TASK-4574 consumes
(spec §8: "its exact parameter set is M7 design work").

**Template parameter contract — binding for TASK-4574.** The template renders the Jira
issue **description** (`jiratoolkit.py:~2723`, "compose the description from a
template"). The toolkit renders with `StrictUndefined` (`jiratoolkit.py:1090-1100`), so
**all ten keys must always be passed**, with `None` / `[]` for absent values:
`meeting_title`, `meeting_date`, `meeting_id`, `action_title`, `owner`, `due_date`,
`evidence`, `decisions` (list), `risks` (list), `wiki_url`.

`parallel: false` — editing `.gitignore` changes repo-wide state outside this task's own
files: it decides what every other task can commit.

---

## Scope

- Replace the single line `/agents/` at `.gitignore:297` with the 7-line block below.
  Do **not** touch `templates/` at `:274` or anything else.
- Create the template and the skill with the exact contents below.
- Create `packages/ai-parrot/tests/bots/test_fireflies_insights_assets.py`: a hermetic copy-the-.gitignore test (AC16) and a StrictUndefined
  render test of the template.
- After the edit, confirm on the real repo that no other agent's files became
  untracked-but-visible: `git status --porcelain --untracked-files=all agents/` must list
  only `agents/fireflies_insights/...` entries.

**NOT in scope**: code that uses the template (TASK-4574); more skills; any other ignore rule.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.gitignore` | MODIFY | `/agents/` → `/agents/*` plus a narrow whitelist for this agent's skills/ and templates/ |
| `agents/fireflies_insights/templates/fireflies/action_item.j2` | CREATE | Base Jira template (`fireflies/action_item`) — Jira wiki markup, renders the issue description |
| `agents/fireflies_insights/skills/meeting-insights/SKILL.md` | CREATE | Base file skill `meeting-insights` |
| `packages/ai-parrot/tests/bots/test_fireflies_insights_assets.py` | CREATE | Hermetic .gitignore whitelist test + template render test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import jinja2   # 3.1.6 in the shared venv (test only)
```

### Existing Signatures to Use
```text
.gitignore:274   templates/            (exact line, grep -cFx = 1)  — DO NOT EDIT
.gitignore:275-280  existing precedent: !packages/<...>/templates/ + /** pairs
.gitignore:297   /agents/              (exact line, grep -cFx = 1)  — the line this task replaces
                 preceded by: # untrack); only NEW agent files are ignored again.
```
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:71   _TEMPLATE_SUFFIX = ".j2"   → template name "fireflies/action_item" resolves to
#           <templates_dir>/fireflies/action_item.j2
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:1090-1100 TemplateEngine(template_dirs=[self.templates_dir], JinjaConfig(autoescape=False, ...)) + StrictUndefined
# skill frontmatter keys in use: name, description, triggers (list, e.g. ["/widget"]), category, version
#   (agents/flex_dashboard/skills/widget/SKILL.md)
```

### Does NOT Exist
- ~~`!agents/fireflies_insights/skills/**` alone being sufficient~~ — tested: it rescues
  nothing while `/agents/` excludes the parent directory.
- ~~`git add -f` as the mechanism~~ — rejected by decision (C14); `porygon` and
  `security_advisor` show it gets forgotten (0 tracked files each).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".gitignore",
      "action": "MODIFY"
    },
    {
      "path": "agents/fireflies_insights/templates/fireflies/action_item.j2",
      "action": "CREATE"
    },
    {
      "path": "agents/fireflies_insights/skills/meeting-insights/SKILL.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_fireflies_insights_assets.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Replace the `/agents/` line — *why*: C14; the only safe form of the exception.
2. Create the template and skill verbatim — *why*: TASK-4574 depends on the exact keys.
3. Write `packages/ai-parrot/tests/bots/test_fireflies_insights_assets.py` — *why*: AC16 must be provable without mutating the real repo.
4. Run the real-repo `git status` check from Scope.

### `.gitignore` (MODIFY)
```gitignore
# occurrences: 1 as an exact line (verified: grep -cFx '/agents/' .gitignore — 6 as a substring!)
# REPLACE the exact line `/agents/` (verified: .gitignore:297) with:
/agents/*
!/agents/fireflies_insights/
/agents/fireflies_insights/*
!/agents/fireflies_insights/skills/
!/agents/fireflies_insights/skills/**
!/agents/fireflies_insights/templates/
!/agents/fireflies_insights/templates/**
```
**Why**: `/agents/*` ignores the children instead of the directory, which is what lets
the later `!` rules re-include one subtree. Keep the comment block above :297 intact.

### `agents/fireflies_insights/templates/fireflies/action_item.j2` (CREATE)
```jinja
h3. Action item: {{ action_title }}

*Meeting:* {{ meeting_title }} ({{ meeting_date }})
*Fireflies ID:* {{ meeting_id }}
{% if owner %}*Owner:* {{ owner }}
{% endif %}{% if due_date %}*Due:* {{ due_date }}
{% endif %}
h4. Evidence from the transcript
{quote}{{ evidence }}{quote}
{% if decisions %}
h4. Decisions taken in the meeting
{% for item in decisions %}* {{ item }}
{% endfor %}{% endif %}{% if risks %}
h4. Risks and blockers raised
{% for item in risks %}* {{ item }}
{% endfor %}{% endif %}{% if wiki_url %}
h4. Meeting notes
[Wiki page|{{ wiki_url }}]
{% endif %}
----
_Created by FirefliesInsightsAgent after confirmation in Telegram._
```

### `agents/fireflies_insights/skills/meeting-insights/SKILL.md` (CREATE)
```markdown
---
name: meeting-insights
description: >
  House style for turning one meeting's transcript and Fireflies summary into
  decisions, risks/blockers and action items. Use when producing or reviewing
  FirefliesInsightsAgent insights.
triggers: ["/meeting-insights"]
category: domain
version: "1.0"
---

# Meeting insights

Turn ONE meeting into three lists. Prefer fewer, sharper items over many vague ones.

## Decisions
- A decision is something the group agreed, not something one person proposed.
- State it as a fact in one line: "Ship the v2 importer on 2026-11-01".

## Risks and blockers
- Something that can delay or break a commitment, raised in the meeting.
- Name what it threatens.

## Action items
- One owner, one outcome. Copy the owner's name exactly as spoken.
- Only give a due date that was actually said; never infer one.
- Every action item quotes its evidence verbatim from the transcript.

## Never
- Invent owners, dates, numbers or decisions.
- Merge two commitments into one action item.
```

### `packages/ai-parrot/tests/bots/test_fireflies_insights_assets.py` (CREATE)
```python
"""FEAT-715 assets: the .gitignore whitelist (AC16) and the base Jira template."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import jinja2
import pytest

REPO = Path(__file__).resolve().parents[4]
TEMPLATE_DIR = REPO / "agents" / "fireflies_insights" / "templates"
PARAMS = {
    "meeting_title": "Weekly sync", "meeting_date": "2026-10-22", "meeting_id": "01KZ",
    "action_title": "Ship the importer", "owner": None, "due_date": None,
    "evidence": "Ana: I will ship it", "decisions": ["Go"], "risks": [], "wiki_url": None,
}


def _ignored(repo: Path, rel: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", rel], check=False).returncode == 0


def test_gitignore_whitelists_only_this_agent(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    shutil.copy(REPO / ".gitignore", tmp_path / ".gitignore")
    for rel in ("agents/fireflies_insights/skills/s/SKILL.md", "agents/fireflies_insights/templates/x.j2",
                "agents/fireflies_insights/secret_runtime.json", "agents/porygon/skills/x.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    assert not _ignored(tmp_path, "agents/fireflies_insights/skills/s/SKILL.md")
    assert not _ignored(tmp_path, "agents/fireflies_insights/templates/x.j2")
    assert _ignored(tmp_path, "agents/fireflies_insights/secret_runtime.json")
    assert _ignored(tmp_path, "agents/porygon/skills/x.md")


def _env() -> jinja2.Environment:
    return jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)), undefined=jinja2.StrictUndefined)


def test_template_renders_with_full_contract() -> None:
    text = _env().get_template("fireflies/action_item.j2").render(**PARAMS)
    assert "Ship the importer" in text and "{quote}Ana: I will ship it{quote}" in text
    assert "*Owner:*" not in text and "Wiki page" not in text


def test_template_fails_when_a_contract_key_is_missing() -> None:
    params = dict(PARAMS)
    params.pop("wiki_url")
    with pytest.raises(jinja2.UndefinedError):
        _env().get_template("fireflies/action_item.j2").render(**params)
```
**Why**: copying `.gitignore` into a throwaway repo proves the rule without creating
files in the real checkout. `parents[4]` is `packages/ai-parrot/tests/bots/<file>` → repo
root (verified: bots → tests → ai-parrot → packages → repo root).

### FILL IN checklist
- [ ] Real-repo `git status --porcelain --untracked-files=all agents/` check from Scope.

---

## Acceptance Criteria

- [ ] **AC16** The hermetic test passes: whitelisted paths not ignored; `porygon` and a
  non-whitelisted file in this agent's dir still ignored.
- [ ] `git status --porcelain --untracked-files=all agents/` lists only `agents/fireflies_insights/` paths.
- [ ] The template renders with the full ten-key contract and fails on a missing key.
- [ ] The three new asset files are committed **without** `git add -f`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/bots/test_fireflies_insights_assets.py -q`

---

## Test Specification

See the `packages/ai-parrot/tests/bots/test_fireflies_insights_assets.py` CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug fireflies-insights-agent --feature-id FEAT-715`).
2. **Read the spec** `sdd/specs/fireflies-insights-agent.spec.md` — §3 (the module this task implements) and §6.
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/fireflies-insights-agent.json`.
4. **Verify the Codebase Contract** before writing code. Anchors were verified at
   `f6a4dbfca`; re-run every `grep -c` in the blueprint and use the fresh count.
   A count of `0` means the anchor moved — stop and report, never invent one.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
   marker; never change a signature, class name or path the blueprint fixes.
7. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   (plus `packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src`
   when the task imports them) — the shared venv is installed against the main
   checkout. Then `ruff check --fix` on every file you touched.
8. **Commit** only the files this task lists (never `git add .` / `-A`):
   `feat(fireflies-insights-agent): TASK-4573 — <title>`.
9. **Close** with `scripts/sdd/close_task.sh TASK-4573 fireflies-insights-agent verified` — never move
   the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
