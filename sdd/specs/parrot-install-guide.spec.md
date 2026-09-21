---
type: feature
base_branch: dev
projects: [docs, ai-parrot, ci]
tags: [installation, onboarding, getting-started, wikitoolkit, documentation]
---

# Feature Specification: Public Install & Getting-Started Guide for AI-Parrot

**Feature ID**: FEAT-586
**Date**: 2026-09-21
**Author**: Arturo Martinez
**Status**: draft
**Target version**: 1.0.5

---

## 1. Motivation & Business Requirements

### Problem Statement

A developer who discovers `ai-parrot` on PyPI has no single, public, end-to-end
document that takes them from a *plain* operating system to a working install and
a first running agent.

The knowledge is scattered and partly assumed: the root `README.md` shows
framework snippets but no OS prerequisites, no virtual-environment guidance and no
statement of the supported Python range; `docs/` contains deep subsystem documents
that address readers who already have a working environment. There is no
onboarding or installation entry point in `docs/` at all.

Two first-run failures are **silent and undocumented**:

1. `pip install ai-parrot` alone registers **zero** LLM providers. `SUPPORTED_CLIENTS`
   is populated exclusively from `parrot.clients` entry points, so with no
   `ai-parrot-client-*` satellite installed `LLMFactory.list_providers()` returns
   `{}` and the reader's first model call fails with no obvious cause.
2. `Chatbot.__init__` defaults to `from_database=True`, so the most obvious
   "hello world" reaches for a database the reader has never configured.

Affected: **any external developer** evaluating or adopting the framework on
Ubuntu 24.04.4 LTS+, macOS 14+, or Windows 10+. The cost is evaluation
abandonment — the reader concludes the framework is broken when the real problem
is an undocumented prerequisite.

### Goals

- G1. One public document takes a reader from a plain OS to a running agent.
- G2. Cover Ubuntu 24.04.4 LTS+, macOS 14+, and Windows 10+ explicitly.
- G3. Make provider installation an unmissable, required step with two supported
  paths (API-key and CLI-backed).
- G4. Ship a runnable hello-world that provably executes.
- G5. Every command is explained — what it does, why, and what it changes —
  so a reader can grant informed trust rather than paste blindly.
- G6. Provide automation scripts as a shortcut to the same documented steps.
- G7. Keep the document true over time via automated claim verification.

### Non-Goals (explicitly out of scope)

- The `/sdd-*` workflow, in any form — not documented, not scaffolded.
- Agent-host wiring (`parrot claude|codex|google install`). `wikitoolkit` is
  documented for `build`/`query` standalone only.
- RTK. Its purpose is compressing *coding-agent* tool output, which left with the
  host wiring; the in-framework analogue `ai-parrot[rust]` is covered instead.
- An interactive installer/wizard (`parrot setup`-style) — deferred.
- Any entry in the root `README.md` — deferred.
- Manifest-driven documentation generation — rejected in brainstorm as Option B;
  see `sdd/proposals/parrot-install-guide.brainstorm.md`.

---

## 2. Architectural Design

### Overview

**Option C** from the accepted brainstorm: the guide and scripts are authored by
hand as ordinary prose and ordinary shell, but the document's *factual claims* are
machine-checkable.

Statements that can go stale — the supported Python range, extra names, console-script
names, provider keys, environment-variable names — are annotated in the markdown
with invisible HTML-comment anchors. A pytest harness extracts those anchors and
asserts each against the live source of truth (`pyproject.toml`, `importlib.metadata`
entry points). Prose stays human-written and friendly; only the checkable facts are
pinned, so a drift failure names the exact stale claim.

This was chosen over hand-maintained docs (Option A — cannot satisfy G7) and over
manifest-driven generation (Option B — generated prose is wrong for an audience
that explicitly includes non-expert readers, and it is heavy machinery for a
document that changes a few times a year).

### Component Diagram

```
docs/getting-started.md ──(claim anchors)──→ test_getting_started_claims.py
        │                                             │
        │                                             ├──→ pyproject.toml  (requires-python, extras, scripts)
        │                                             └──→ entry_points("parrot.clients")  (provider keys)
        │
        ├──(same steps, automated)──→ scripts/install/install-parrot.sh   (Ubuntu/macOS)
        └──(same steps, automated)──→ scripts/install/install-parrot.ps1  (Windows)
                                                      │
                                                      └──→ CI: syntax check + single-OS dry run
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | reads | Source of truth for the Python range, extras, console scripts. Never modified. |
| `parrot.clients.factory.LLMFactory` | reads | `list_providers()` backs the provider-key claims and the "install a provider first" warning. |
| `parrot.clients.detection` | documents | `detect_coding_agent_llm()` is the CLI-backed path the guide explains. |
| `examples/basic_agent.py` | derives from | Verified runnable pattern the hello-world is based on. |
| `docs/` | extends | New entry-point document; no existing page rewritten. |
| CI workflow | modifies | Runs the new tests; single-OS only. |

### Data Models

```python
# Claim extracted from the guide (test-harness-internal, not a public API)
class DocClaim(BaseModel):
    kind: Literal["python-range", "extra", "script", "provider", "envvar"]
    value: str
    line: int          # 1-based line in the source document, for failure messages
    source: Path
```

### New Public Interfaces

None. This feature adds documentation, scripts and tests; it exposes no new
importable Python API and changes no runtime behavior.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Guide + claim convention | no | — | Prose, tone and pedagogy are design decisions; the anchor syntax is fixed here but the writing is not mechanical. |
| M2: Claim-verification harness | yes | Anchor regex, `DocClaim` model, one test per claim kind, failure message must name file:line and the stale value | — |
| M3: POSIX installer | yes | Flag set, step order, detect-and-guide fallback, idempotent venv reuse, no `set -e` bypass | — |
| M4: PowerShell installer | yes | Mirror of M3's flags/steps; `-Agent` not `-Host` (clashes with `$Host`) | — |
| M5: CI wiring | yes | Single-OS job; runs M2 tests + `bash -n` + PowerShell parse + dry run | — |

### Module 1: Guide document and claim-anchor convention
- **Path**: `docs/getting-started.md` (new)
- **Responsibility**: The public step-by-step guide, and the definition of the
  claim-anchor convention every other module consumes.
- **Depends on**: nothing (must land first — M2–M5 consume its convention)
- **Interface Skeleton** *(the convention is the interface)*:
  ```markdown
  <!-- verify: python-range=>=3.11,<3.14 -->
  <!-- verify: extra=jev -->
  <!-- verify: script=wikitoolkit -->
  <!-- verify: provider=claude-code -->
  <!-- verify: envvar=TYPESAFE_API_KEY -->
  ```
  One anchor per line, immediately preceding the prose or fenced block it
  substantiates. Anchors are HTML comments, invisible when rendered.

  Required document structure (sections, in order):
  1. Prerequisites per OS · 2. Install the package · 3. Install a provider
  (API-key **or** CLI-backed) · 4. Hello world · 5. `wikitoolkit build`/`query`
  · 6. Optional extras (`jev`, `rust`) · 7. Verification checklist &
  troubleshooting · 8. Where to go next.

  **Every command block carries an explanation** of what the command does, why
  the step needs it, and what it changes on the machine. Privileged (`sudo`) or
  network-fetching commands additionally state their blast radius and offer a
  non-piped alternative where one exists.

### Module 2: Claim-verification harness
- **Path**: `packages/ai-parrot/tests/docs/test_getting_started_claims.py` (new)
- **Responsibility**: Extract claim anchors from M1 and assert each against live
  package metadata; fail naming the exact stale claim.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/docs/test_getting_started_claims.py  (new)
  GUIDE: Path                      # repo-root-relative path to docs/getting-started.md
  ANCHOR_RE: re.Pattern[str]       # r"<!--\s*verify:\s*(?P<kind>[\w-]+)=(?P<value>.+?)\s*-->"

  def extract_claims(path: Path) -> list[DocClaim]:
      """Parse every `<!-- verify: kind=value -->` anchor, preserving 1-based line numbers."""

  def test_guide_exists() -> None:
      """docs/getting-started.md is present and contains at least one claim anchor."""

  def test_python_range_matches_pyproject() -> None:
      """Every python-range claim equals requires-python in packages/ai-parrot/pyproject.toml."""

  def test_named_extras_exist() -> None:
      """Every extra claim is a key of [project.optional-dependencies]."""

  def test_named_scripts_exist() -> None:
      """Every script claim is a key of [project.scripts]."""

  def test_named_providers_are_registered() -> None:
      """Every provider claim resolves in entry_points(group='parrot.clients')."""

  def test_hello_world_snippet_executes() -> None:
      """The guide's hello-world runs against a stub client — no network, no API key."""
  ```

### Module 3: POSIX installer script
- **Path**: `scripts/install/install-parrot.sh` (new)
- **Responsibility**: Automate M1's steps on Ubuntu 24.04.4 LTS+ and macOS 14+.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```bash
  # scripts/install/install-parrot.sh  (new)
  # --provider <k>[,<k>...]  one or more of: anthropic|openai|google|claude-code|codex-code
  # --extras <list>          extra ai-parrot extras (comma-separated)
  # --venv <dir>             virtualenv dir (default: .venv)
  # --python <bin>           interpreter (default: python3)
  # --with-wiki              run `wikitoolkit build` after install
  # --install-cli            npm-install the claude/codex CLI for a CLI-backed provider
  # --system-deps            install OS packages via sudo apt-get / brew (opt-in)
  # --dry-run                print every command without executing it
  # -h|--help
  # Contract: idempotent (reuses an existing venv, never deletes one);
  #           refuses Python outside >=3.11,<3.14; every sudo/network command
  #           is echoed with its purpose before running.
  ```

### Module 4: PowerShell installer script
- **Path**: `scripts/install/install-parrot.ps1` (new)
- **Responsibility**: Windows 10+ equivalent of Module 3.
- **Depends on**: Module 1 (mirrors Module 3's flag set)
- **Interface Skeleton**:
  ```powershell
  # scripts/install/install-parrot.ps1  (new)
  param(
    [string]$Provider = 'anthropic',   # comma-separated; -Agent naming avoided: $Host is reserved
    [string]$Extras = '',
    [string]$Venv = '.venv',
    [string]$Python = 'python',
    [switch]$WithWiki,
    [switch]$InstallCli,
    [switch]$SystemDeps,
    [switch]$DryRun,
    [switch]$Help
  )
  # Same contract as Module 3.
  ```

### Module 5: CI wiring
- **Path**: `.github/workflows/` (modifies the existing CI workflow)
- **Responsibility**: Run M2's tests, syntax-check both scripts, and execute one
  `--dry-run` install. Single OS (ubuntu-latest) — no OS matrix.
- **Depends on**: Modules 2, 3, 4
- **Interface Skeleton**:
  ```yaml
  # .github/workflows/ci.yml  (modifies existing)
  - run: pytest packages/ai-parrot/tests/docs/ -v
  - run: bash -n scripts/install/install-parrot.sh
  - run: pwsh -NoProfile -Command "[Parser]::ParseFile('scripts/install/install-parrot.ps1',[ref]$null,[ref]$e)"
  - run: bash scripts/install/install-parrot.sh --dry-run --provider anthropic
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_extract_claims_parses_all_kinds` | M2 | Anchor regex parses each of the five kinds with line numbers |
| `test_extract_claims_ignores_plain_comments` | M2 | Non-`verify:` HTML comments are not treated as claims |
| `test_guide_exists` | M2 | Guide present and carries ≥1 anchor |
| `test_python_range_matches_pyproject` | M2 | python-range claims equal `requires-python` |
| `test_named_extras_exist` | M2 | Every extra claim is a real optional-dependency key |
| `test_named_scripts_exist` | M2 | Every script claim is a real `[project.scripts]` key |
| `test_named_providers_are_registered` | M2 | Every provider claim resolves in `parrot.clients` entry points |
| `test_failure_message_names_file_and_line` | M2 | A stale claim fails naming `file:line` and the offending value |

### Integration Tests
| Test | Description |
|---|---|
| `test_hello_world_snippet_executes` | The guide's hello-world runs against a stub client — no network, no key |
| `test_posix_script_syntax` | `bash -n` on the POSIX installer |
| `test_powershell_script_syntax` | PowerShell parser on the `.ps1` (skipped when `pwsh` absent) |
| `test_posix_script_dry_run` | `--dry-run` prints the full plan and touches nothing |
| `test_script_rejects_unsupported_python` | Script exits non-zero on 3.10 / 3.14 |

### Test Data / Fixtures
```python
@pytest.fixture
def guide_path() -> Path:
    """Repo-root-relative path to docs/getting-started.md."""

@pytest.fixture
def stub_provider(monkeypatch) -> None:
    """Register a fake `parrot.clients` provider so the hello-world runs offline."""
```

---

## 5. Acceptance Criteria

- [ ] AC1. `docs/getting-started.md` exists and covers, in order: per-OS
      prerequisites (Ubuntu 24.04.4 LTS+, macOS 14+, Windows 10+), package
      install, provider install, hello-world, `wikitoolkit build`/`query`,
      optional extras, verification/troubleshooting, next steps.
- [ ] AC2. The guide states the supported Python range and it matches
      `requires-python` (`>=3.11,<3.14`), asserted by a test.
- [ ] AC3. The guide presents provider installation as **required**, explicitly
      warning that a bare install registers zero providers.
- [ ] AC4. Both provider paths are documented: API-key (`anthropic`/`openai`/
      `google`) and CLI-backed (`claude-code`/`codex-code`), with one, several or
      none of the CLI-backed options installable independently.
- [ ] AC5. The guide states that Gemini has **no** CLI-backed provider and is
      reachable only via `google` / `google-compat`.
- [ ] AC6. The CLI-backed section documents that auth is delegated to the CLI
      (`ANTHROPIC_API_KEY` or a completed `claude auth`), and that
      `detect_coding_agent_llm()` only checks `which` — so a logged-out binary
      passes detection and fails at call time.
- [ ] AC7. The hello-world is runnable and avoids the `from_database=True` trap;
      `test_hello_world_snippet_executes` passes offline.
- [ ] AC8. **Every command block is accompanied by an explanation** of what it
      does, why the step needs it, and what it changes. Every `sudo` or
      network-fetching command additionally states its blast radius and offers a
      non-piped alternative where one exists.
- [ ] AC9. `scripts/install/install-parrot.sh` and `install-parrot.ps1` exist,
      expose the documented flags, are idempotent, and support `--dry-run`.
- [ ] AC10. The scripts refuse a Python outside `>=3.11,<3.14` before installing.
- [ ] AC11. All claim-verification tests pass (`pytest packages/ai-parrot/tests/docs/ -v`).
- [ ] AC12. A deliberately stale claim makes the suite fail with a message naming
      the file, line and offending value.
- [ ] AC13. CI runs the doc tests, both syntax checks and one dry run, on a
      single OS.
- [ ] AC14. The document contains no organization-specific content: no internal
      branch policy, ticket keys, reviewer policy, or internal tooling decisions.
- [ ] AC15. No mention of the `/sdd-*` workflow, agent-host wiring, or RTK.
- [ ] AC16. `ruff check` and `black --check` pass on all new Python.
- [ ] AC17. No changes to `README.md` and no runtime code changes.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.bots import AbstractBot, Agent, BaseBot, BasicAgent, BasicBot, Chatbot  # verified: packages/ai-parrot/src/parrot/bots/__init__.py:1-7
from parrot.bots.agent import BasicAgent          # verified: used by examples/basic_agent.py
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS  # verified: packages/ai-parrot/src/parrot/clients/factory.py
from parrot.clients.detection import detect_coding_agent_llm      # verified: packages/ai-parrot/src/parrot/clients/detection.py
from parrot.tools import tool                     # verified: packages/ai-parrot/src/parrot/tools/decorators.py:59
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/chatbot.py
class Chatbot(BaseBot):                                    # line 33
    def __init__(
        self,
        name: str = "Nav",                                 # line 51
        system_prompt: str = None,                         # line 52
        human_prompt: str = None,                          # line 53
        from_database: bool = True,                        # line 54  <-- TRAP
        tools: List[Union[str, AbstractTool]] = None,      # line 55
        **kwargs,
    ): ...

# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: ...     # line 174
    @staticmethod
    def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
               tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient: ...  # line 257

# packages/ai-parrot/src/parrot/clients/detection.py  (whole file verified)
_CLAUDE_CODE_SPEC = "claude-code:claude-haiku-4-5-20251001"
_CODEX_CODE_SPEC = "codex-code:gpt-5.1-codex"
def detect_coding_agent_llm() -> Optional[str]:
    """Claude Code first, then Codex; None if neither. Only
    LLMFactory.list_providers() + shutil.which() — never imports a provider
    SDK, never spawns a subprocess, never makes a network call."""

# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py
class ClaudeAgentClient(AbstractClient):                   # line 265
    client_type: str = "claude_agent"                      # line 281
    provider_keys: tuple[str, ...] = ("claude-agent", "claude-code")   # line 285
    _default_model: str = "claude-sonnet-4-6"              # line 288
    _lightweight_model: str = "claude-haiku-4-5-20251001"  # line 289
    # Docstring, lines 272-274: "Authentication is delegated to the CLI: it picks
    # up ANTHROPIC_API_KEY from the environment when set, otherwise it relies on
    # whatever auth flow the user has previously completed via `claude auth`."

# packages/ai-parrot-client-openai/src/parrot/clients/openai/codex_agent.py
class OpenAICodexClient(AbstractClient):                   # line 71
    default_model = "gpt-5.1-codex"                        # line 81
    provider_keys: tuple[str, ...] = ("codex-agent", "openai-codex", "codex-code")  # line 85
    # Uses the optional `openai-codex` SDK when installed; falls back to a
    # verified `codex exec` backend reusing existing Codex CLI credentials.
```

### Verified runnable pattern
```python
# Source: examples/basic_agent.py (verbatim)
import asyncio
from parrot.bots.agent import BasicAgent

async def get_agent(question):
    agent = BasicAgent(name='HelperAgent',)
    await agent.configure()
    answer, response = await agent.invoke(question)
    return answer, response

if __name__ == '__main__':
    answer, response = asyncio.run(get_agent("What is the capital of France?"))
    print(answer)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| claim harness | `requires-python` | `tomllib` read | `packages/ai-parrot/pyproject.toml:18` |
| claim harness | `[project.scripts]` | `tomllib` read | `packages/ai-parrot/pyproject.toml:199-206` |
| claim harness | provider keys | `entry_points(group="parrot.clients")` | 37 keys, resolved at runtime |
| guide §3 | `detect_coding_agent_llm()` | documented behavior | `parrot/clients/detection.py` |
| guide §4 | `BasicAgent.configure()/.invoke()` | documented usage | `examples/basic_agent.py` |

### Key Constants
- `requires-python = ">=3.11,<3.14"` — pyproject.toml:18
- `[project.scripts]` — pyproject.toml:199-206: `parrot`, `parrot-graphindex`, `wikitoolkit`, `bookstore`
- `rustworkx`, `networkx`, `pathspec`, `aiosqlite`, `orjson` are **core** deps
  (pyproject.toml:192-196) — `wikitoolkit build` works on a bare install (FEAT-471)
- `jev` extra → `ai-parrot-client-jev`, needs `TYPESAFE_API_KEY` (docs/clients/jev.md:15-16)
- `rust` extra → `parrot_codec`, pure-Python fallback (pyproject.toml:860-862)
- `claude-agent` extra → `ai-parrot-client-anthropic`, which depends on
  `claude-agent-sdk>=0.1.68` (that satellite's pyproject.toml:18)
- `codex-agent` extra → `ai-parrot-client-openai[bridge]` (pyproject.toml:579-584)

### Does NOT Exist (Anti-Hallucination)
- ~~A Gemini/Antigravity (`agy`) CLI provider~~ — the complete 37-key
  `parrot.clients` entry-point set has no `agy`, `antigravity` or `gemini-cli`.
  Gemini is reachable only as `google` or `google-compat`.
- ~~`parrot sdd install`~~ — no such command. `parrot` groups are exactly:
  `setup`, `conf`, `install`, `wiki`, `bookstore`, `mcp`, `mcp-local`, `toolkits`,
  `autonomous`, `agent`, `claude`, `codex`, `google`, `gemini`, `generate-keys`,
  `devloop`, plus agentd commands (`parrot/cli/__init__.py:109-133`).
- ~~`parrot cloud install`~~ — not a command; the real one is `parrot claude install`
  (out of scope here; listed to prevent a misremembered name).
- ~~`ai-parrot[rtk]`~~ — no such extra. RTK is an external binary; the
  in-framework analogue is the `rust` extra.
- ~~A `getting-started` or `installation` page under `docs/`~~ — verified absent
  before this feature.
- ~~Automatic provider registration on bare install~~ — does NOT happen.
- ~~`-Host` as a PowerShell parameter name~~ — collides with the automatic
  `$Host` variable; use `-Provider`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Google-style docstrings and strict type hints on all new Python.
- `black` (line-length 120) formats; `ruff check` is the lint gate.
- Tests use `pytest`; the doc tests must run offline with no API key.
- Scripts: POSIX `sh`-compatible `bash`, `set -euo pipefail`, no `sudo` unless
  `--system-deps` is passed, every privileged command echoed before execution.
- Markdown: keep prose in the register of the existing `docs/` pages.

### Known Risks / Gotchas
- **Untagged prose still rots.** The harness only checks anchored claims.
  Mitigation: anchor every version/name/key at authoring time; AC12 proves the
  mechanism bites.
- **Logged-out CLI passes detection.** `detect_coding_agent_llm()` checks only
  `shutil.which`, so a present-but-unauthenticated `claude`/`codex` is detected
  and then fails at call time. Mitigation: AC6 documents it, and the verification
  step makes a real call rather than trusting detection.
- **`pwsh` is often absent** on Linux CI. Mitigation: the PowerShell syntax test
  skips cleanly when `pwsh` is not on PATH.
- **`sudo`/`brew`/`apt` cannot run in CI.** Mitigation: CI exercises `--dry-run`
  only; `--system-deps` is never executed in CI.
- **Provider entry points depend on what is installed.** `list_providers()`
  reflects the local venv. Mitigation: the provider-claim test asserts against
  the *declared* extras when the satellite is absent, and against entry points
  when present.
- **Doc path collision.** `docs/getting-started.md` must not shadow an existing
  page — verified absent.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pytest` | `>=8.0` | Test runner — already in the `dev` extra |
| `tomllib` | stdlib (3.11+) | Read `pyproject.toml` — no new dependency |
| `importlib.metadata` | stdlib | Resolve `parrot.clients` entry points |

No new runtime dependency is introduced.

---

## 8. Open Questions

- [x] Is agent-host wiring in scope? — *Resolved in brainstorm*: No. `wikitoolkit`
      is documented for `build`/`query` standalone only. (§1 Non-Goals)
- [x] Does "use ai-parrot" include framework usage? — *Resolved in brainstorm*:
      Yes, a basic hello-world. (§3 M1 step 4, AC7)
- [x] Should the SDD workflow be documented or scaffolded? — *Resolved in brainstorm*:
      No, entirely out of scope. (§1 Non-Goals, AC15)
- [x] Should RTK be dropped? — *Resolved in brainstorm*: Yes; `ai-parrot[rust]`
      covered instead. (§1 Non-Goals, §6 Key Constants)
- [x] Is npm still required? — *Resolved in brainstorm*: Only conditionally, for
      the CLI-backed provider path. (§3 M3 `--install-cli`, AC4)
- [x] Which provider should the hello-world default to? — *Resolved in brainstorm*:
      Offer a choice; one, several or none of the CLI-backed options. (AC4)
- [x] Should CI run a real OS matrix? — *Resolved in brainstorm*: No, single-OS
      dry run. (§3 M5, AC13)
- [x] Exact document path? — *Resolved in brainstorm*: `docs/getting-started.md`. (§3 M1)
- [x] Does `ClaudeAgentClient` need an authenticated CLI session, and what is the
      failure mode? — *Resolved during §4 research*: Auth is delegated to the CLI
      — it uses `ANTHROPIC_API_KEY` when set, otherwise a previously completed
      `claude auth` flow (claude_agent.py:272-274). Because
      `detect_coding_agent_llm()` only calls `shutil.which`, a logged-out binary
      **is** detected and fails at call time. Captured as AC6 and a §7 risk.
- [ ] Should the guide pin a concrete `claude`/`codex` CLI minimum version? The
      clients depend on `claude-agent-sdk>=0.1.68`, but no minimum *CLI* version
      is asserted anywhere in the tree. Decide during implementation; if no
      floor can be verified, state none rather than invent one. — *Owner: Arturo Martinez*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted brainstorm.
> Model: `n/a` · Status: **skipped (codex CLI not found on PATH)**
> · Transcript: none

No external reviewer was available, so no suggestions were produced or triaged.
Per project policy the pass is optional and never blocking, and `agy` must not be
substituted as a reviewer.

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for this spec
  (`.claude/worktrees/feat-FEAT-586-parrot-install-guide`). The `sdd-coder`
  engine gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (the harness parses the anchor convention M1 defines)
  - M3 → M1 (the script automates M1's documented steps)
  - M4 → M1 (mirrors M3's flag set, which derives from M1)
  - M5 → M2, M3, M4 (CI runs all three)
  - M3 and M4 have no edge between them and are expected to run concurrently;
    M2 is likewise concurrent with M3/M4 once M1 lands.
- **Shared files**: none between M1–M4. M5 is the only module touching
  `.github/workflows/`, so no serialization is required.
- **Exclusive resources**: none. No lockfile, migration or extension rebuild.
- **Cross-feature dependencies**: none. This feature adds new files and reads
  `pyproject.toml` without modifying it.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-21 | Arturo Martinez | Initial draft from accepted brainstorm (Option C) |
