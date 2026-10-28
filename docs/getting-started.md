# Getting Started with AI-Parrot

AI-Parrot is an async-first Python framework for building AI agents and
chatbots. This guide takes you from a plain operating system to a working
install and a first running agent.

Every command below is explained — what it does, why the step needs it, and
what it changes on your machine — so you can decide whether to run it rather
than pasting it blindly. Commands that need `sudo` or fetch something over the
network additionally state their blast radius and, where one exists, a
non-piped alternative you can inspect before running.

<!-- verify: python-range=>=3.11,<3.14 -->
> **Supported Python**: AI-Parrot requires Python 3.11, 3.12 or 3.13. Python
> 3.14 is not yet supported — the package will refuse to install on it.

---

## 1. Prerequisites

Pick your operating system below. Each block installs Python (if you don't
already have a supported version) and `git`.

### Ubuntu 24.04.4 LTS+

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip git
```

- `apt-get update` refreshes Ubuntu's local package index from its configured
  repositories — it does not install or change anything by itself.
- `apt-get install -y ...` installs Python 3.12 (a supported version), its
  standard-library `venv` module, `pip`, and `git`. **Blast radius**: this
  modifies system-wide packages under `/usr` and requires `sudo`. If you'd
  rather not run it blind, inspect what it would do first with
  `apt-get install -y --dry-run python3.12 python3.12-venv python3-pip git`,
  which prints the plan without changing anything.
- Ubuntu 24.04 ships Python 3.12 in its default repositories, so no extra
  PPA is required for a supported interpreter.

### macOS 14+

```bash
xcode-select --install   # if you don't already have the Xcode CLI tools
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12 git
```

- `xcode-select --install` installs Apple's Command Line Tools (compiler,
  `git`, standard Unix utilities) if you don't already have them — a one-time,
  interactive, GUI-prompted install; skip it if `xcode-select -p` already
  prints a path.
- The `curl | bash` line installs [Homebrew](https://brew.sh), macOS's
  package manager. **Blast radius**: it downloads and executes a remote
  script with your user's privileges (it will prompt for `sudo` itself when
  it needs to create `/opt/homebrew`). A non-piped alternative: download the
  script first (`curl -fsSL -o install.sh <url>`), read it, then run
  `bash install.sh`. Skip this step entirely if you already have Homebrew
  (`brew --version`).
- `brew install python@3.12 git` installs a supported Python and `git` under
  Homebrew's own prefix — it does not touch the system Python.

### Windows 10+

```powershell
winget install Python.Python.3.12
winget install Git.Git
```

- `winget install Python.Python.3.12` installs a supported Python release
  via the Windows Package Manager (already present on Windows 10 2004+ and
  all of Windows 11). It installs to the current user's app data by default —
  no system-wide change.
- `winget install Git.Git` installs Git for Windows the same way.
- Prefer an interactive install instead? Download both installers directly
  from [python.org](https://www.python.org/downloads/) and
  [git-scm.com](https://git-scm.com/download/win) and run them manually — the
  `winget` commands above are a scripted shortcut to the same installers, not
  a different source.

---

## 2. Install the package

Create an isolated virtual environment first, then install AI-Parrot into it.
Using a venv means the install only ever touches files inside the project
directory — nothing system-wide, and `rm -rf .venv` fully undoes it.

**Linux / macOS:**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install ai-parrot
```

**Windows (PowerShell):**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install ai-parrot
```

- `python -m venv .venv` creates a self-contained Python environment in a new
  `.venv/` directory — no admin/sudo privileges needed.
- The `activate` step points your shell's `python`/`pip` at that environment
  instead of the system one, for the rest of this session only.
- `pip install --upgrade pip` updates the venv-local `pip` (not the system
  one) so the next command resolves dependencies with a current resolver.
- `pip install ai-parrot` downloads AI-Parrot and its core dependencies from
  PyPI into `.venv/`. This is a real network fetch of third-party code — the
  package is [public on PyPI](https://pypi.org/project/ai-parrot/) if you
  want to inspect it first.

If you prefer [`uv`](https://docs.astral.sh/uv/) (a faster, drop-in
alternative to `pip`/`venv`), the equivalent is:

```bash
uv venv .venv
uv pip install --python .venv/bin/python ai-parrot
```

**A bare install alone is not enough to talk to an LLM** — see the next
section.

### Global install (managed runtime, no project venv)

<!-- verify: cli-verb=self doctor -->
<!-- verify: flag=self doctor:--runtime-only -->
Instead of a per-project venv you can install AI-Parrot once per machine. One command puts `parrot`,
`wikitoolkit` and `bookstore` on your PATH, backed by a managed runtime under `~/.parrot` (or
`$PARROT_HOME`): a pinned `uv`, a uv-managed Python 3.12 and a venv holding `ai-parrot` together with
`ai-parrot-tools` at the same version (`wikitoolkit mcp` needs it). It needs no system Python.

**Linux / macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/install-parrot.sh | bash -s -- --global --with sdd
```

**Downloads:** the script above and, from GitHub, the pinned `uv 0.11.28` archive plus its `.sha256` file
(`https://github.com/astral-sh/uv/releases/download/0.11.28/uv-<target>.tar.gz`), then `ai-parrot` and
`ai-parrot-tools` from PyPI. A uv already on your PATH is never used or modified.
**Writes:** `~/.parrot/bin`, `~/.parrot/venv` and `~/.parrot/python`, plus a `# >>> parrot >>>` PATH block
in your shell profile. Existing `~/.parrot` data (wikis, library, skills, brains, `parrot.db`) is never touched.
**Verified by:** the uv archive checksum, then `parrot self doctor --runtime-only`; a failure removes only
what the run created. Before writing anything the script checks the platform, `curl`/`wget`, `sha256sum`,
`git`, 2 GiB of free space under `PARROT_HOME` and that GitHub and PyPI are reachable, and prints a plan first.
**Without piping:** download `install-parrot.sh` and `SHA256SUMS` from
`https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/`, run
`sha256sum -c --ignore-missing SHA256SUMS` (macOS: `shasum -a 256 -c --ignore-missing SHA256SUMS`), read the
script, then run `bash install-parrot.sh --global --with sdd`. Add `--dry-run` to print the plan only.

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/phenobarbital/ai-parrot/main/scripts/install/install-parrot.ps1))) -Global -With sdd"
```

**Downloads:** the script above and, from GitHub, the pinned `uv 0.11.28` zip plus its `.sha256` file, then
`ai-parrot` and `ai-parrot-tools` from PyPI.
**Writes:** `~\.parrot\bin`, `~\.parrot\venv` and `~\.parrot\python`, and adds `~\.parrot\bin` to your
USER PATH (never the Machine PATH); reopen the terminal afterwards.
**Verified by:** the uv checksum (`Get-FileHash`), then `parrot self doctor --runtime-only`; a failure
removes only what the run created.
**Without piping:** `Invoke-WebRequest` both `install-parrot.ps1` and `SHA256SUMS` from the same folder,
compare `(Get-FileHash install-parrot.ps1).Hash` with its line in `SHA256SUMS`, read the script, then run
`powershell -ExecutionPolicy Bypass -File install-parrot.ps1 -Global -With sdd`.

> **Windows status (pending CI verification):** the `-Global` path has not yet run on a Windows runner. CI checks the script's syntax, its `-DryRun` plan and its pre-write gates under `pwsh` on Linux; the install itself, the post-install rollback and the USER PATH restore are covered only by an offline harness that is still marked expected-to-fail. They become verified claims when the install-matrix Windows leg passes.

Reference detail (gate, plan text, launcher order, `--portable`, version skew) is in
[docs/install/global-runtime.md](install/global-runtime.md).

### Manage the runtime: `parrot self`

<!-- verify: cli-verb=self add -->
<!-- verify: flag=self add:--here -->
<!-- verify: cli-verb=self env -->
<!-- verify: cli-verb=self update -->
<!-- verify: cli-verb=self uninstall -->
<!-- verify: flag=self uninstall:--yes -->
- `parrot self add <component>` installs a component's packages into the managed venv; `--here` installs
  into the current project venv instead, and is the only way a dependency enters a project venv.
- `parrot self env` prints the venv the launcher resolves, the rule that picked it and the versions.
- `parrot self doctor` diagnoses the runtime, host configs and toolkit requirements.
- `parrot self update` upgrades `ai-parrot` in the managed venv (`--version` pins one).
- `parrot self uninstall` removes only `bin/`, `venv/` and `python/` (`--yes` skips the prompt).

---

## 3. Install a provider (REQUIRED)

<!-- verify: extra=anthropic -->
<!-- verify: extra=openai -->
<!-- verify: extra=google -->
<!-- verify: provider=anthropic -->
<!-- verify: provider=openai -->
<!-- verify: provider=google -->
> **`pip install ai-parrot` alone registers ZERO LLM providers.** Every
> concrete provider client ships as its own `ai-parrot-client-<provider>`
> satellite package, discovered via Python entry points. Until you install at
> least one, `LLMFactory.list_providers()` returns `{}` and any agent you
> create will fail with an "unsupported LLM" error the first time it tries to
> call a model — with no earlier warning. Installing a provider is not
> optional; it is step 3 of getting a working agent, not a later refinement.

There are two supported ways to add a provider:

### Option A — API-key providers

Install the extra for the vendor whose API key you have, then set the key as
an environment variable.

```bash
pip install "ai-parrot[anthropic]"    # Anthropic (Claude models)
# or:
pip install "ai-parrot[openai]"       # OpenAI
# or:
pip install "ai-parrot[google]"       # Google Gemini
```

- Each command installs one `ai-parrot-client-<provider>` satellite package
  and its SDK from PyPI — a normal, scoped dependency install, not a system
  change.
- Set the matching API key as an environment variable before running any
  code that uses it, e.g. (Linux/macOS) `export ANTHROPIC_API_KEY=sk-...` or
  (PowerShell) `$env:ANTHROPIC_API_KEY = "sk-..."`. Never commit a key to a
  file in your repository.

### Option B — CLI-backed providers

If you already run the **Claude Code** or **Codex** coding-agent CLI on this
machine, AI-Parrot can reuse that CLI's own authentication instead of a
separate API key.

<!-- verify: extra=claude-agent -->
<!-- verify: provider=claude-code -->
<!-- verify: dep=ai-parrot-client-anthropic:claude-agent-sdk>=0.1.68 -->
```bash
pip install "ai-parrot[claude-agent]"
```

<!-- verify: extra=codex-agent -->
<!-- verify: provider=codex-code -->
<!-- verify: dep=ai-parrot-client-openai:openai-codex>=0.1.0 -->
```bash
pip install "ai-parrot[codex-agent]"
```

- These extras install `ai-parrot-client-anthropic` /
  `ai-parrot-client-openai` with the SDK that talks to an already-running
  `claude` / `codex` CLI session — they do **not** install the CLI binaries
  themselves (see the installer scripts below for that).
- **Authentication is delegated to the CLI.** `ClaudeAgentClient` picks up
  `ANTHROPIC_API_KEY` from the environment when set, otherwise it relies on
  whatever auth flow you already completed via `claude auth`. The same idea
  applies to Codex and its own CLI auth.
- **Caveat**: AI-Parrot's `detect_coding_agent_llm()` helper only checks
  whether the `claude`/`codex` binary is on your `PATH` (`shutil.which`) — it
  does **not** check whether you're actually logged in. A CLI binary that is
  installed but logged out will pass detection and then fail the first time
  it actually tries to call the model. If a call fails right after a clean
  detection, check your CLI's own auth status first (`claude auth status` /
  the Codex equivalent).
- You can install one, several, or none of the CLI-backed options
  independently of the API-key options above — pick whichever paths match
  what you already have.

You can install any combination of the extras above; `LLMFactory` discovers
whatever is present.

**One asymmetry to know**: Gemini has **no** CLI-backed provider path in
AI-Parrot. It is reachable only via the `google` (API key) extra above, or
`google-compat` (OpenAI-compatible wire format over the same Gemini API key)
— never through a coding-agent CLI.

---

## 4. Hello world

With a provider installed and its key/auth in place, this runs a minimal
agent end to end. It is adapted from `examples/basic_agent.py` in the
repository, with one deliberate change: it passes `llm="anthropic"` (swap in
whichever provider extra you installed) and `from_database=False` explicitly.

<!-- verify: dep=ai-parrot-client-anthropic:claude-agent-sdk>=0.1.68 -->
```python
import asyncio
from parrot.bots.agent import BasicAgent

async def get_agent(question: str):
    # from_database=False is deliberate: Chatbot (which BasicAgent extends)
    # defaults to from_database=True, which tries to load the bot's
    # configuration from a Postgres database you likely haven't set up yet.
    # For a first run, skip that and configure the agent manually instead.
    agent = BasicAgent(name="HelperAgent", llm="anthropic", from_database=False)
    await agent.configure()
    response = await agent.invoke(question)
    return response.output, response

if __name__ == "__main__":
    answer, response = asyncio.run(get_agent("What is the capital of France?"))
    print(answer)
```

Run it with `python hello_world.py` (after activating your venv). It makes
one real network call to whichever provider you chose in step 3 — expect a
one-line answer.

Two things this snippet deliberately avoids:

1. **The `from_database=True` trap.** `Chatbot.__init__` (the base class
   `BasicAgent` extends) defaults `from_database=True`, which — with no
   explicit argument — tries to load the bot's configuration from a Postgres
   database on `configure()`. That's the right choice once you're persisting
   named bots, but it is the wrong default for a first run with nothing set
   up. Passing `from_database=False` configures the agent purely from the
   constructor arguments instead.
2. **The zero-providers trap from step 3.** `llm="anthropic"` is explicit
   here, not left to the default, precisely because a bare install has no
   default provider to fall back to.

---

## 5. Building and querying the codebase knowledge graph

`wikitoolkit` ships as a console script with the base package — no extra
install needed for `build`/`query` themselves (some optional per-language
scanners are covered in the next section).

<!-- verify: script=wikitoolkit -->
```bash
wikitoolkit build
```

- Scans the current repository deterministically — no LLM calls, no
  embeddings, no network access — and writes a local SQLite knowledge-graph
  index under `.parrot/wiki/`. Safe to re-run; it incrementally re-indexes
  only changed files.

```bash
wikitoolkit query "where is the ingest pipeline implemented?"
```

- Runs a token-budgeted, ranked lexical search over that local index and
  prints matching page stubs — again, fully offline once `build` has run.

### Use the SDD flow in your repo

<!-- verify: cli-verb=sdd install -->
<!-- verify: flag=sdd install:--host -->
<!-- verify: flag=sdd install:--dry-run -->
<!-- verify: flag=sdd install:--force -->
<!-- verify: cli-verb=sdd status -->
<!-- verify: cli-verb=sdd run -->
<!-- verify: cli-verb=self doctor -->
<!-- verify: flag=self doctor:--sdd -->
With the global runtime installed, any git repository (Python or not) can adopt the Spec-Driven Development
flow:

```bash
parrot sdd install --host claude --dry-run   # preview: write / skip / upgrade per file; changes nothing
parrot sdd install --host claude             # deploy commands, skills, helpers and seeds
parrot self doctor --sdd                     # origin, base branch, ledger, worktrees ignore, gh, jq, host CLIs
parrot sdd status                            # missing | current | outdated | edited | foreign
```

- The install writes the host's `/sdd-*` commands, the seeds `sdd/config.json`, `sdd/CONVENTIONS.md` and
  `sdd/tasks/.id_ledger.json`, a `.claude/worktrees/` ignore block, a marked `.gitattributes` block
  (`merge=union` for the ledger log) and the four `parrot-ledger` git hooks. What it wrote is recorded in
  `sdd/.sdd-installed.json`; commit it. `/sdd-insight` is not installed.
- Edit `sdd/config.json`: `base_branch`, `hotfix_base`, `issue_tracker`, `test_command`, ... When
  `test_command` is set, the shipped test steps run it once from the repo root instead of the selection/report
  steps (`cache_test_contract` in `/sdd-task`, `select_tests` / `test_report` in `/sdd-done`), and a run with no
  tests shows "not run". When it is null the ai-parrot selection path applies, and `parrot sdd install` warns.
- Fill in the `sdd/CONVENTIONS.md` seed (`## Repository layout`, `## Project areas`); it is created once and
  never overwritten.
- Then open your assistant and run your first `/sdd-spec` ... command. Helpers run as
  `parrot sdd run <name>` (for example `parrot sdd run reserve_ids --help`).
- Re-running `parrot sdd install` upgrades files you have not touched and keeps the ones you edited
  (`--force` overwrites edited files; foreign files are never touched).

More: [docs/install/global-runtime.md](install/global-runtime.md).

---

## 6. Optional extras

Two extras worth knowing about beyond the provider ones in step 3:

<!-- verify: extra=jev -->
<!-- verify: envvar=TYPESAFE_API_KEY -->
```bash
pip install "ai-parrot[jev]"
```

- Installs the client for [TypeSafe AI's Jev](https://typesafe.ai) System
  One model — typed, calibrated decisions (routing/ranking/verification)
  instead of free text. Requires a `TYPESAFE_API_KEY` environment variable.
  See `docs/clients/jev.md` for the full client reference.

<!-- verify: extra=rust -->
```bash
pip install "ai-parrot[rust]"
```

- Installs `parrot_codec`, an optional Rust-accelerated columnar codec used
  to compress large tool results. Pre-built wheels are published for common
  platforms; without this extra, AI-Parrot transparently falls back to a
  pure-Python implementation, so this is a performance optimization, not a
  functional requirement.

---

## 7. Verification checklist & troubleshooting

Confirm each of these before moving on:

- [ ] `python -c "import parrot; print(parrot.__name__)"` succeeds inside your
      activated venv.
- [ ] `python -c "from parrot.clients.factory import LLMFactory; print(LLMFactory.list_providers())"`
      prints a **non-empty** dict. An empty `{}` means no provider satellite
      is installed yet — go back to step 3.
- [ ] `wikitoolkit --help` runs without error.
- [ ] The hello-world snippet in step 4 prints an answer instead of raising.

**Common failures:**

| Symptom | Likely cause | Fix |
|---|---|---|
| `ValueError: Unsupported LLM: '<provider>'` | That provider's satellite isn't installed | `pip install "ai-parrot[<provider>]"` (step 3) |
| Agent construction or a call raises an auth/401 error | API key not set, or CLI not logged in | Re-check the environment variable, or run `claude auth` / the Codex login flow |
| A CLI-backed provider "works" during detection but the call itself fails | `detect_coding_agent_llm()` only checks the binary is on `PATH`, not that you're logged in | Check the CLI's own auth status directly |
| `pip install ai-parrot` fails outright | Unsupported Python version | Confirm `python --version` is 3.11, 3.12, or 3.13 |

---

## 8. Where to go next

- `docs/wiki-claude-code.md` — wiring `wikitoolkit` into Claude Code as
  coding-assistant infrastructure.
- `docs/clients/jev.md` — the Jev typed-decision client in depth.
- The repository's `.agent/CONTEXT.md` — architectural overview of AI-Parrot's
  core abstractions (`AbstractClient`, `AbstractBot`/`Chatbot`/`Agent`,
  `AbstractTool`) if you're going to build beyond the hello-world above.
