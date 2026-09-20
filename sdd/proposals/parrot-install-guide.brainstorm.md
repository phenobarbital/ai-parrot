---
type: feature
base_branch: dev
projects: [docs, ai-parrot, ci]
tags: [installation, onboarding, getting-started, wikitoolkit, documentation]
---

# Brainstorm: Public Install & Getting-Started Guide for AI-Parrot

**Date**: 2026-09-20
**Author**: Arturo Martinez
**Status**: exploration
**Recommended Option**: C

---

## Problem Statement

A developer who discovers `ai-parrot` on PyPI has no single, public, end-to-end
document that takes them from a *plain* operating system to a working install
and a first running agent.

Today the knowledge is scattered and partly assumed:

- The root `README.md` shows framework snippets but no OS-level prerequisites,
  no virtual-environment guidance, and no statement of the supported Python range.
- `docs/` contains deep subsystem documents (`docs/clients/`, `docs/wiki-claude-code.md`,
  `docs/sdd/`), but they address readers who already have a working environment.
- The single most common first-run failure is **invisible**: `pip install ai-parrot`
  alone registers **zero** LLM providers, so a newcomer's first call fails with an
  empty provider registry and no obvious cause (verified — see Code Context).
- A second silent trap: `Chatbot(...)` defaults to `from_database=True`, so the
  obvious "hello world" tries to reach a database the reader has not configured.

Who is affected: **any external developer** evaluating or adopting the framework,
on Ubuntu 24.04.4 LTS+, macOS 14+, or Windows 10+. The cost of the gap is
evaluation abandonment — the reader concludes the framework is broken when the
real problem is an undocumented two-line prerequisite.

This document is **public**. It must contain no organization-specific policy,
internal branch conventions, ticket keys, or internal tooling decisions.

## Constraints & Requirements

- **Public and vendor-neutral.** No organization-specific content, no internal
  process, no ticket identifiers, no internal reviewer/agent policy.
- **Three operating systems**: Ubuntu 24.04.4 LTS or newer, macOS 14+ ("Golden
  Gate" era or newer), Windows 10 or newer.
- **Python `>=3.11,<3.14`** — enforced by `requires-python`; 3.14 is not supported.
- **At least one LLM provider must be installed and configured**, otherwise the
  framework cannot make a single model call.
- **`wikitoolkit` limited to `build` / `query`** — standalone use only. No
  coding-agent host wiring (`parrot claude|codex|google install`) in scope.
- **A runnable hello-world** must be included and must actually execute.
- **Automation scripts** are the shortcut to the documented steps: may use
  `sudo` for system packages and `uv` for Python; conservative by default, with
  detect-and-guide fallbacks and manual steps for less technical readers.
- **Tests must keep the document true.** A failing test means the documented
  process (or the script) is revised.
- **Separate document.** No root-`README.md` entry and no interactive installer
  in this iteration.
- Out of scope: the `/sdd-*` workflow, coding-agent CLIs, agent-host wiring.

---

## Options Explored

### Option A: Hand-written guide + standalone scripts, script-only tests

Author the guide as ordinary prose in `docs/`, write the two installer scripts
independently, and test only the scripts (syntax check plus a dry run). The
document's factual claims — supported Python range, extras names, console-script
names, the hello-world snippet — are maintained by hand.

✅ **Pros:**
- Fastest to produce; prose stays natural and friendly for non-expert readers.
- No new build machinery, no generator to learn or maintain.
- Scripts remain plain, readable, and independently useful.

❌ **Cons:**
- **The document rots silently.** Nothing detects it when an extra is renamed,
  the Python ceiling moves, or a console script is dropped.
- The two artifacts (prose and scripts) drift from each other over time.
- Directly fails the "tests must keep the installation true" requirement — the
  tests would cover the script but not the *claims the reader follows*.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pytest` | Test runner | Already a `dev` extra |
| `bash -n` / PowerShell parser | Syntax validation | No new dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/pyproject.toml` — authoritative extras and console scripts
- `examples/basic_agent.py` — verified runnable agent pattern

---

### Option B: Manifest-driven generation (single source of truth)

Define the install procedure once in a machine-readable manifest (YAML/TOML):
OS prerequisites, package specs, extras, environment variables, verification
commands. Generate **both** the documentation sections and the two installer
scripts from that manifest at build time. Tests validate the manifest against
the real package metadata.

✅ **Pros:**
- Strongest possible consistency: docs and scripts cannot disagree, because
  they are two renderings of one source.
- Adding a new OS or provider is a manifest edit, not three parallel edits.
- The manifest itself becomes testable, typed data.

❌ **Cons:**
- **Generated prose reads like generated prose.** This document's audience
  explicitly includes "not that technical" readers who need narrative
  explanation, caveats, and reassurance — exactly what a renderer flattens.
- Substantial new machinery (schema, renderer, templates, build step) for a
  document that changes a few times a year.
- The generator becomes a second thing to maintain and debug.
- Over-fits the problem: the real risk is a handful of factual claims drifting,
  not the whole document structure.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `PyYAML` | Manifest parsing | Already a core dependency |
| `jinja2` | Template rendering | Present in the `agents` extra |
| `pydantic` | Manifest schema validation | Already core (v2) |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/pyproject.toml` — the metadata the manifest must track
- `scripts/docgen.py` — existing documentation-generation precedent

---

### Option C: Hand-written guide + scripts, with a claim-verification harness

Author the guide and scripts by hand (as in Option A), but make the document's
**factual claims machine-checkable**. Tag the claims that can go stale —
supported Python range, extras names, console-script names, environment-variable
names, the hello-world snippet — and add a test harness that extracts them from
the markdown and asserts each against live package metadata and the real CLI.
Add a dry-run of the installer script inside a temporary git repository.

The prose stays human-written and friendly; only the *checkable facts* are
pinned. The document becomes its own test fixture.

✅ **Pros:**
- Directly satisfies "tests must keep the installation true": the test fails on
  the exact claim that drifted, naming it.
- Preserves narrative, human-authored prose for non-expert readers.
- Incremental — the harness can start with three or four claim types and grow.
- No generator layer; the document remains directly editable by anyone.
- The hello-world can be executed as a real test (with a stub provider), so the
  headline example provably runs.

❌ **Cons:**
- Requires a small, bespoke extraction convention (tagged fenced blocks or a
  claims table) that contributors must learn.
- Claim extraction is only as good as its tagging; untagged prose can still rot.
- Slightly more upfront work than Option A.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pytest` | Test runner | Already in the `dev` extra |
| `tomllib` | Read `pyproject.toml` metadata | Python 3.11+ stdlib — no dependency |
| `importlib.metadata` | Verify console scripts / entry points | stdlib |
| `python-frontmatter` | Parse doc frontmatter if used | Already a core dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/pyproject.toml` — `requires-python`, `[project.scripts]`,
  `[project.optional-dependencies]`: the source of truth every claim is checked against
- `packages/ai-parrot/src/parrot/clients/factory.py` — `LLMFactory.list_providers()`
  for asserting the "install a provider first" claim
- `examples/basic_agent.py` — the verified hello-world pattern to document
- `packages/ai-parrot-tools/tests/tool_optimizations/` — existing precedent for
  contract-style tests over documentation artifacts

---

## Recommendation

**Option C** is recommended because:

The requirement that decides this is "tests should validate that this
installation process will keep true; if the test fails the installation script
should be revised." Option A cannot satisfy it — it tests the script but not the
claims the reader actually follows, which is where the breakage happens. Option B
satisfies it but pays for consistency with generated prose, and the stated
audience includes non-expert readers who need narrative and caveats. A renderer
is the wrong tool for a document whose value is partly its tone.

Option C buys the guarantee where it matters and nowhere else. The failure mode
we are defending against is narrow and enumerable: an extra gets renamed, the
Python ceiling moves, a console script disappears, the hello-world API changes.
Those are a handful of discrete facts, so pin exactly those and leave the prose
free. The test then fails naming the specific stale claim rather than a diffed
blob.

What we are trading off, honestly: contributors must learn a tagging convention,
and any claim left untagged can still rot unnoticed. That is acceptable because
the harness degrades gracefully — an untagged document is merely no worse than
Option A — and because coverage can grow incrementally without redesign. We are
also accepting more upfront effort than Option A for a document that will be
read far more often than it is written.

---

## Feature Description

### User-Facing Behavior

A developer lands on a single public document in `docs/` and can go from a clean
machine to a working agent without leaving it. The document is ordered so each
section is verifiable before moving on:

1. **Prerequisites** per OS — Python 3.11–3.13, git, and the platform's package
   manager (`apt`, Homebrew, `winget`), each with a copy-pasteable block.
2. **Install the package** into an isolated environment, via `uv` (recommended)
   or stdlib `venv` + `pip`, with the four console scripts it provides.
3. **Install and configure at least one LLM provider** — presented as a required
   step, not an optional one, with the explicit warning that a bare install
   registers no providers. Per-provider extra and environment variable.
4. **Hello world** — a runnable agent, copy-pasteable, that answers one question.
5. **`wikitoolkit build` / `query`** — the offline codebase knowledge graph, used
   standalone.
6. **Optional: typed outputs with Jev**, and **optional: `ai-parrot[rust]`** for
   compression acceleration.
7. **Verification checklist** and a troubleshooting table keyed to the two known
   silent traps.
8. **Where to go next** — pointers into the existing deep `docs/` pages.

Two scripts under `scripts/` are the shortcut: a POSIX shell script for
Ubuntu/macOS and a PowerShell script for Windows. They perform the same steps,
are safe to re-run, print what they intend to do, and fall back to printing
manual instructions whenever an automated step is unavailable.

### Internal Behavior

The guide is authored directly as markdown. A subset of its statements are
written in a tagged, extractable form. A test module reads the document, pulls
out those tagged claims, and asserts each against the live source of truth:

- the supported Python range against `requires-python`;
- every named extra against `[project.optional-dependencies]`;
- every named console script against `[project.scripts]`;
- the hello-world snippet by executing it against a stub provider so no network
  or API key is needed;
- the installer scripts by syntax-checking them and running them in
  detect-only mode inside a temporary git repository.

The scripts themselves stay declarative: detect the platform, verify
prerequisites, create or reuse a virtual environment, install the package plus
the chosen provider extra, run the verification commands, and report. Anything
requiring interactive authentication is detected and explained, never automated.

### Edge Cases & Error Handling

- **Unsupported Python** (3.10 or 3.14+) — detected before any install; the
  script stops with the supported range and how to obtain it.
- **No provider installed** — the guide states this up front; the verification
  step surfaces an empty provider registry as a named, expected condition.
- **Missing API key** — verification distinguishes "provider package missing"
  from "provider installed but key unset"; these have different fixes.
- **`from_database=True` default** — the hello-world uses the non-database path
  explicitly, and the trap is called out so readers adapting the snippet do not
  reintroduce it.
- **No `sudo` / restricted machine** — the script degrades to printing the exact
  commands for an administrator instead of failing.
- **Windows without WSL** — supported for install and hello-world; any step that
  genuinely needs a POSIX shell is marked and given a manual alternative.
- **Re-running the script** — idempotent: an existing virtual environment is
  reused, never recreated or deleted.

---

## Capabilities

### New Capabilities
- `install-guide`: a public, OS-specific installation and getting-started document.
- `install-automation`: POSIX and PowerShell scripts automating the documented steps.
- `install-claim-verification`: a test harness asserting the guide's factual
  claims against live package metadata.

### Modified Capabilities
- None. No existing spec's requirements change; this adds documentation,
  scripts, and tests without altering runtime behavior.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `docs/` | extends | New public guide; no existing page rewritten |
| `scripts/` | extends | Two new installer scripts |
| `packages/ai-parrot/tests/` | extends | New claim-verification test module |
| `packages/ai-parrot/pyproject.toml` | depends on | Read-only: source of truth for claims; not modified |
| `examples/basic_agent.py` | depends on | Hello-world is derived from this verified pattern |
| CI workflow | modifies | Must run the new tests; optional OS matrix |
| Root `README.md` | none | Explicitly out of scope this iteration |

---

## Code Context

### User-Provided Code

No code snippets were provided by the user during discovery. Requirements were
supplied as prose across three rounds of questions and answers.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/bots/chatbot.py:33
class Chatbot(BaseBot):
    def __init__(
        self,
        name: str = "Nav",                                  # line 51
        system_prompt: str = None,                          # line 52
        human_prompt: str = None,                           # line 53
        from_database: bool = True,                         # line 54  <-- TRAP: defaults to True
        tools: List[Union[str, AbstractTool]] = None,       # line 55
        **kwargs,
    ): ...

# From packages/ai-parrot/src/parrot/clients/factory.py:257
class LLMFactory:
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:   # line 174
        """Parse 'provider:model' or 'provider'."""
    @staticmethod
    def create(
        llm: str,
        model_args: Optional[Dict[str, Any]] = None,
        tool_manager: Optional[Any] = None,
        **kwargs,
    ) -> AbstractClient: ...                                        # line 257

# From packages/ai-parrot/src/parrot/tools/decorators.py:59
def tool(
    _func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    auto_register: bool = False,
    requires_confirmation: bool = False,
    ...
): ...

# From packages/ai-parrot/src/parrot/bots/abstract.py
async def configure(self, app=None) -> None: ...   # line 1500
async def ask(self, ...): ...                      # line 4533
```

#### Verified Imports

```python
# Confirmed to resolve (packages/ai-parrot/src/parrot/bots/__init__.py:1-7):
from parrot.bots import AbstractBot, Agent, BaseBot, BasicAgent, BasicBot, Chatbot
from parrot.bots.agent import BasicAgent          # used by examples/basic_agent.py
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.tools import tool
```

#### Verified runnable pattern

```python
# Source: examples/basic_agent.py (verbatim, verified present)
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

#### Key Attributes & Constants

- `requires-python = ">=3.11,<3.14"` — packages/ai-parrot/pyproject.toml:18
- `[project.scripts]` — pyproject.toml:199-206: `parrot`, `parrot-graphindex`,
  `wikitoolkit`, `bookstore`
- Provider extras (pyproject.toml:547-674): `anthropic`, `openai`, `google`,
  `groq`, `grok`, `zai`, `nvidia`, `moonshot`, `openrouter`, `local`, `vllm`,
  `meta`, `hf`, `gemma4`, `bedrock-native`, `jev`, and the aggregate `llms`
- `rustworkx`, `networkx`, `pathspec`, `aiosqlite`, `orjson` are **core**
  dependencies (pyproject.toml:192-196), so `wikitoolkit build` works on a bare
  install (FEAT-471)
- `SUPPORTED_CLIENTS` is a lazily-populated registry filled **only** from
  `parrot.clients` entry points; with zero satellites installed,
  `LLMFactory.list_providers() == {}` (factory.py module docstring, lines 1-30)
- `jev` extra → `ai-parrot-client-jev`; requires `TYPESAFE_API_KEY` (docs/clients/jev.md:15-16)
- `rust` extra → `parrot_codec`, with a pure-Python fallback (pyproject.toml:860-862)

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot sdd install`~~ — no such command. The `parrot` CLI groups are
  exactly: `setup`, `conf`, `install`, `wiki`, `bookstore`, `mcp`, `mcp-local`,
  `toolkits`, `autonomous`, `agent`, `claude`, `codex`, `google`, `gemini`,
  `generate-keys`, `devloop`, plus the agentd commands
  (packages/ai-parrot/src/parrot/cli/__init__.py:109-133).
- ~~`parrot cloud install`~~ — not a command; the real one is `parrot claude install`
  (out of scope here, listed only to prevent a misremembered name).
- ~~A `getting-started` or `installation` page under `docs/`~~ — verified absent;
  `docs/` has no onboarding or install entry point today.
- ~~`ai-parrot[rtk]`~~ — no such extra. RTK is an external binary, unrelated to
  packaging; the in-framework analogue is the `rust` extra.
- ~~`ai-parrot[claude-code]` / `[codex]` / `[gemini-cli]`~~ — no extras install
  coding-agent CLIs; those are external tools (now out of scope).
- ~~Automatic provider registration on bare install~~ — does NOT happen; at least
  one `ai-parrot-client-*` satellite must be installed.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Three naturally separable tracks — (1) the
  guide prose, (2) the two installer scripts, (3) the claim-verification test
  harness. Tracks 2 and 3 both depend on the tagging convention that track 1
  establishes, so track 1 must land its structure first; after that, 2 and 3 are
  genuinely independent.
- **Cross-feature independence**: High. The feature adds new files under `docs/`,
  `scripts/`, and a new test module. It modifies no runtime code and reads
  `pyproject.toml` without editing it. The only shared touchpoint is the CI
  workflow. No conflict with in-flight specs is expected.
- **Recommended isolation**: `per-spec`
- **Rationale**: The feature is small, the tracks share one authoring convention,
  and the sequencing dependency (convention before consumers) is easier to honor
  sequentially in a single worktree than to coordinate across several. The
  parallelism that does exist is not worth the coordination overhead.

---

## Open Questions

- [x] Is the coding-agent host wiring in scope? — *Owner: Arturo Martinez*: No.
  Removed. `wikitoolkit` is documented for `build`/`query` standalone only.
- [x] Does "use ai-parrot" include framework usage? — *Owner: Arturo Martinez*:
  Yes — a basic hello-world is in scope.
- [x] Should the SDD workflow be documented or scaffolded? — *Owner: Arturo Martinez*:
  No. SDD is entirely out of scope for this document.
- [ ] **Should RTK be dropped?** Its purpose is compressing *coding-agent* tool
  output, and coding agents are now out of scope. Proposed: drop RTK; cover the
  in-framework `ai-parrot[rust]` compression instead. — *Owner: Arturo Martinez*
- [ ] **Is `npm` still required?** It was needed only to install the coding-agent
  CLIs. With those removed, no documented step appears to need Node.js. Proposed:
  drop `npm`, keep `sudo` for system packages and `uv` for Python. — *Owner: Arturo Martinez*
- [ ] Which provider should the hello-world default to? It determines the extra
  and API key a first-time reader must obtain. Proposed: show one provider
  concretely and table the rest. — *Owner: Arturo Martinez*
- [ ] Should CI run the installer scripts on a real ubuntu/macOS/Windows runner
  matrix, or is a single-OS dry run plus syntax checks sufficient for v1?
  Cost/benefit tradeoff. — *Owner: Arturo Martinez*
- [ ] Exact document path and filename under `docs/` (e.g.
  `docs/getting-started.md` vs `docs/install/README.md`). — *Owner: Arturo Martinez*
