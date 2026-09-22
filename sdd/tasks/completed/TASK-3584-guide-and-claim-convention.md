# TASK-3584: Write docs/getting-started.md and the claim-anchor extractor

**Feature**: FEAT-586 — Public Install & Getting-Started Guide for AI-Parrot
**Spec**: `sdd/specs/parrot-install-guide.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. This task delivers the public getting-started guide
AND the executable form of its claim-anchor convention (the parser + the
guide-existence test). The parser lives here — not in the harness task (M2) —
because the anchor convention and its extractor are the same artifact: the
convention is only real once something reads it. TASK-3585 extends the same test
module with the metadata cross-checks that depend on this parser.

Two silent first-run traps this guide must neutralize (verified, see Codebase
Contract): a bare `pip install ai-parrot` registers zero LLM providers, and
`Chatbot(...)` defaults to `from_database=True`.

---

## Scope

- Create `docs/getting-started.md` covering, in order: per-OS prerequisites
  (Ubuntu 24.04.4 LTS+, macOS 14+, Windows 10+), package install (uv + pip),
  required provider install (API-key **and** CLI-backed paths), a runnable
  hello-world, `wikitoolkit build`/`query`, optional `jev`/`rust`, a
  verification/troubleshooting section, and "where to go next".
- Annotate every stale-able fact with a `<!-- verify: kind=value -->` anchor
  (kinds: `python-range`, `extra`, `script`, `provider`, `envvar`, `dep`).
- Explain every command block: what it does, why the step needs it, what it
  changes; `sudo`/piped commands additionally state blast radius and a
  non-piped alternative (spec AC8).
- Create `packages/ai-parrot/tests/docs/test_getting_started_claims.py` with the
  `DocClaim` model, `ANCHOR_RE`, `extract_claims()`, and the tests
  `test_guide_exists`, `test_extract_claims_parses_all_kinds`,
  `test_extract_claims_ignores_plain_comments`.

**NOT in scope**: the metadata cross-check tests, the hello-world execution test,
the failure-message test (all TASK-3585); the installer scripts (TASK-3586/3587);
CI wiring (TASK-3588); any change to `README.md` or runtime code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/getting-started.md` | CREATE | The public guide, with claim anchors and per-command explanations |
| `packages/ai-parrot/tests/docs/test_getting_started_claims.py` | CREATE | `DocClaim`, `ANCHOR_RE`, `extract_claims()`, guide-existence + extractor tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Standard library only — no new dependency:
import re, tomllib
from pathlib import Path
from pydantic import BaseModel  # pydantic==2.12.5 is a core dep (pyproject.toml:54)
```

### Existing Signatures to Use (documented in the guide's hello-world)
```python
# examples/basic_agent.py — verified runnable pattern, quote VERBATIM in the guide
from parrot.bots.agent import BasicAgent
agent = BasicAgent(name='HelperAgent')
await agent.configure()                 # abstract.py:1500
answer, response = await agent.invoke(question)

# packages/ai-parrot/src/parrot/bots/chatbot.py:33 — the trap the guide must call out
class Chatbot(BaseBot):
    def __init__(self, name="Nav", system_prompt=None, human_prompt=None,
                 from_database=True, ...):   # from_database defaults True (line 54)
```

### Key facts to anchor (verified in this repo)
- `requires-python = ">=3.11,<3.14"` — `packages/ai-parrot/pyproject.toml:18` → `<!-- verify: python-range=>=3.11,<3.14 -->`
- console scripts `parrot`, `parrot-graphindex`, `wikitoolkit`, `bookstore` — pyproject.toml:199-206 → `<!-- verify: script=wikitoolkit -->`
- extras `jev`, `rust`, `anthropic`, `openai`, `google` — pyproject.toml `[project.optional-dependencies]` → `<!-- verify: extra=jev -->`
- provider keys `claude-code`, `codex-code`, `google` — `parrot.clients` entry points → `<!-- verify: provider=claude-code -->`
- `TYPESAFE_API_KEY` — docs/clients/jev.md:15-16 → `<!-- verify: envvar=TYPESAFE_API_KEY -->`
- SDK floors `ai-parrot-client-anthropic:claude-agent-sdk>=0.1.68`, `ai-parrot-client-openai:openai-codex>=0.1.0` → `<!-- verify: dep=... -->`

### Does NOT Exist
- ~~a Gemini/`agy` CLI provider~~ — Gemini is only `google` / `google-compat` (spec AC5)
- ~~`parrot sdd install`, `parrot cloud install`, `ai-parrot[rtk]`~~ — see spec §6
- ~~automatic provider registration on bare install~~ — never happens

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "docs/getting-started.md", "action": "CREATE" },
    { "path": "packages/ai-parrot/tests/docs/test_getting_started_claims.py", "action": "CREATE" }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Public, vendor-neutral: no organization-specific content (spec AC14).
- No `/sdd-*`, no agent-host wiring, no RTK (spec AC15).
- Anchors are HTML comments — invisible when rendered — placed immediately
  before the prose/fence they substantiate.
- Match the register of the existing `docs/` pages.

### References in Codebase
- `docs/wiki-claude-code.md` — tone and structure of a `docs/` page
- `docs/clients/jev.md` — Jev install and `TYPESAFE_API_KEY`
- `examples/basic_agent.py` — the hello-world source of truth

---

## Implementation Blueprint

### Steps (in order)
1. Author `docs/getting-started.md` section by section — *why*: the guide is the
   product; every other task consumes it.
2. As you write each stale-able fact, add its `<!-- verify: kind=value -->`
   anchor — *why*: TASK-3585 asserts these against live metadata.
3. Write the extractor + `DocClaim` + the three extractor/existence tests —
   *why*: the convention must be executable, and this task must be independently
   verifiable before the cross-checks land.

### `packages/ai-parrot/tests/docs/test_getting_started_claims.py` (CREATE)
```python
"""Claim-anchor extraction for docs/getting-started.md (FEAT-586, TASK-3584).

The metadata cross-checks that consume these claims are added by TASK-3585.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

# repo root = five parents up from this file (packages/ai-parrot/tests/docs/<file>)
REPO_ROOT = Path(__file__).resolve().parents[4]
GUIDE = REPO_ROOT / "docs" / "getting-started.md"

ANCHOR_RE = re.compile(r"<!--\s*verify:\s*(?P<kind>[\w-]+)=(?P<value>.+?)\s*-->")


class DocClaim(BaseModel):
    """One `<!-- verify: kind=value -->` anchor extracted from the guide."""

    kind: Literal["python-range", "extra", "script", "provider", "envvar", "dep"]
    value: str
    line: int          # 1-based line in the source document
    source: Path


def extract_claims(path: Path) -> list[DocClaim]:
    """Parse every verify-anchor in `path`, preserving 1-based line numbers.

    Non-`verify:` HTML comments are ignored. Unknown kinds raise via DocClaim
    validation — an anchor typo must fail loudly, not be skipped.
    """
    claims: list[DocClaim] = []
    for i, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for m in ANCHOR_RE.finditer(text):
            claims.append(DocClaim(kind=m["kind"], value=m["value"], line=i, source=path))
    return claims


def test_guide_exists() -> None:
    """The guide is present and carries at least one verify-anchor."""
    assert GUIDE.is_file(), f"missing guide: {GUIDE}"
    assert extract_claims(GUIDE), "guide has no <!-- verify: ... --> anchors"


def test_extract_claims_parses_all_kinds() -> None:
    """The regex parses each of the six kinds with correct line numbers."""
    # FILL IN: build a tmp_path fixture doc containing one anchor of every kind
    #          (python-range, extra, script, provider, envvar, dep) and assert
    #          extract_claims returns 6 DocClaims with the expected lines —
    #          bounded by AC11.
    raise NotImplementedError


def test_extract_claims_ignores_plain_comments() -> None:
    """A plain `<!-- note -->` HTML comment yields no claim."""
    # FILL IN: assert extract_claims over a doc with only non-verify comments == []
    #          — bounded by AC11.
    raise NotImplementedError
```
**Why this shape**: `REPO_ROOT` uses `parents[4]` because the file sits at
`packages/ai-parrot/tests/docs/`; verify that depth at implementation time
(`# FILL IN` if the test dir moves). `DocClaim.kind` includes `dep` per spec AC18.
The extractor is pure and offline so both this task and TASK-3585 can rely on it.

### `docs/getting-started.md` (CREATE)
```markdown
# Getting Started with AI-Parrot

<!-- verify: python-range=>=3.11,<3.14 -->
> AI-Parrot needs Python 3.11–3.13 (3.14 is not yet supported).

## 1. Prerequisites
<!-- FILL IN: per-OS blocks (Ubuntu apt / macOS brew / Windows winget). Every
     command gets a one-line "what & why"; each sudo/piped command states blast
     radius + a non-piped alternative — bounded by AC8. -->

## 3. Install a provider (REQUIRED)
<!-- verify: extra=anthropic -->
<!-- verify: provider=claude-code -->
> A bare install registers ZERO providers. Install one of two ways: an API-key
> provider extra, or a CLI-backed provider if you already run that CLI.
<!-- FILL IN: both paths; state Gemini has no CLI-backed provider (AC5); note
     detect_coding_agent_llm only checks `which`, so a logged-out binary passes
     detection and fails at call time (AC6) — bounded by AC3-AC6. -->

## 4. Hello world
<!-- FILL IN: quote examples/basic_agent.py VERBATIM; call out the
     Chatbot from_database=True trap and why the agent path avoids it — AC7. -->
```
**Why this shape**: anchors shown are the minimum TASK-3585 will assert; add one
per stale-able fact as you write. The bodies are `FILL IN` because the prose is a
design act (spec §3 M1 is *not* delegation-eligible), but the section order,
anchor kinds, and the two trap call-outs are fixed by the spec and must not drift.

### FILL IN checklist
- [ ] guide §1 — three per-OS prerequisite blocks with per-command explanations; bounded by AC1, AC8
- [ ] guide §3 — both provider paths, Gemini asymmetry, CLI auth caveat; bounded by AC3-AC6
- [ ] guide §4 — verbatim hello-world + `from_database` trap; bounded by AC7
- [ ] guide §5-§8 — wikitoolkit build/query, optional jev/rust, verification, next steps; bounded by AC1
- [ ] `test_extract_claims_parses_all_kinds` body; bounded by AC11
- [ ] `test_extract_claims_ignores_plain_comments` body; bounded by AC11
- [ ] confirm `parents[4]` resolves to repo root from the test's location

---

## Acceptance Criteria

- [ ] `docs/getting-started.md` exists with the eight sections in order (spec AC1)
- [ ] Supported Python range stated and anchored (spec AC2)
- [ ] Provider install presented as required, both paths, Gemini asymmetry, CLI auth caveat (spec AC3-AC6)
- [ ] Hello-world present and avoids the `from_database=True` trap (spec AC7)
- [ ] Every command block explained; sudo/piped commands note blast radius + alternative (spec AC8)
- [ ] No org-specific content; no `/sdd-*`, host-wiring, or RTK mention (spec AC14, AC15)
- [ ] `ruff check` and `black --check` pass on the new test module (spec AC16)
- [ ] Extractor + existence tests pass

## Validation Commands
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_guide_exists -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_extract_claims_parses_all_kinds -q`
- `pytest packages/ai-parrot/tests/docs/test_getting_started_claims.py::test_extract_claims_ignores_plain_comments -q`

---

## Test Specification
```python
# packages/ai-parrot/tests/docs/test_getting_started_claims.py
def test_guide_exists() -> None:
    """Guide present + at least one verify-anchor."""

def test_extract_claims_parses_all_kinds() -> None:
    """One anchor of every kind is parsed with correct line numbers."""

def test_extract_claims_ignores_plain_comments() -> None:
    """Plain HTML comments produce no claims."""
```

---

## Agent Instructions
1. Read the spec (§3 M1, §6) for full context.
2. Verify the Codebase Contract before writing — re-confirm pyproject line
   numbers, `Chatbot.from_database` default, and `examples/basic_agent.py`.
3. Update index status → in-progress.
4. Implement from the blueprint; complete every `# FILL IN`.
5. Run the Validation Commands.
6. Move this file to `sdd/tasks/completed/`, set index → done, fill the note.

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-21
**Notes**: Created `docs/getting-started.md` (all 8 sections, anchors for
python-range/extra/script/provider/envvar/dep) and
`packages/ai-parrot/tests/docs/test_getting_started_claims.py`
(`DocClaim`, `ANCHOR_RE`, `extract_claims()`, `test_guide_exists`,
`test_extract_claims_parses_all_kinds`, `test_extract_claims_ignores_plain_comments`).
All 3 validation tests pass. `black --check` clean; `ruff` is not installed
in the shared `.venv` in this environment (dev extra not synced) so
`ruff check` could not be run — flagged for the human/code review.
**Deviations from spec**: During TASK-3585 prep work I empirically verified
(direct execution) two pre-existing, out-of-scope bugs that affect the
guide's hello-world section (§4), neither of which this task's file list
permits fixing:
  1. `BasicAgent.__init__` (`packages/ai-parrot/src/parrot/bots/agent.py`,
     ~line 113) unconditionally does `from ..clients.google import
     GoogleGenAIClient` regardless of the `llm=` argument passed — so
     `BasicAgent(...)` raises `ImportError` whenever `ai-parrot-client-google`
     (or its own `google-genai` dependency) isn't importable, even when the
     caller only wants e.g. `llm="anthropic"`.
  2. `examples/basic_agent.py`'s literal `answer, response =
     await agent.invoke(question)` raises `ValueError: too many values to
     unpack` against the current `BaseBot.invoke()`, which returns a single
     `AIMessage`, not a 2-tuple.
  Neither `parrot/bots/agent.py` nor `examples/basic_agent.py` is in this
  task's (or any FEAT-586 task's) Files to Create/Modify list, and AC17
  forbids runtime code changes, so both are left untouched. The guide's §4
  snippet instead documents the corrected pattern (`response =
  await agent.invoke(...)` then reads `.output`) with an explicit `llm=`
  and `from_database=False`, and both findings are reported for code review
  / ledger filing rather than fixed here.
