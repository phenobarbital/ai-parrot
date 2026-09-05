# Bookstore in Codex

Install the PageIndex book library MCP and its research skill with the existing
Codex installer, from the target repository:

```bash
parrot codex install --no-build
```

This installs the usual WikiToolkit integration. When an indexed library is
available in the project, global location, or `PARROT_LIBRARY_DIR`, it also adds:

- A managed `[mcp_servers.bookstore]` table in `.codex/config.toml`.
- The `$bookstore` research skill at `.agents/skills/bookstore/SKILL.md`.

If no library is defined (no resolved location contains `library.db`), Bookstore
is silently skipped. No server is registered and no new skill is installed.
Re-running installation after a library disappears removes its managed MCP
registration; existing skills and user-owned MCP settings are retained.

`--no-build` skips the optional wiki build; without it, the installer builds the
wiki on first use. Neither form indexes books. Use `--path /path/to/repo` to
install from elsewhere, or `--no-bookstore` to skip Bookstore installation
(existing Bookstore settings are retained).

The MCP command uses the Python environment running `parrot`, with the target
repository as its explicit working directory. It works with an installed
ai-parrot package and does not require a checkout-specific script or a
`bookstore` console entry point. Re-run installation after moving the repository
or replacing its Python environment. Existing user-owned Bookstore MCP settings
and differing skills are preserved and reported.

## Start a session

Use an environment with the existing `ai-parrot[bookstore,mcp]` extras installed.
Check your indexed library with `parrot bookstore locations`. An initialized
library containing `library.db` is required for the server to start. If needed,
index a Markdown file with:

```bash
parrot bookstore add notes.md --no-llm
parrot codex install --no-build
```

Restart Codex in the trusted target repository. Use `/mcp` to inspect the live
connection, then ask:

```text
$bookstore Search my library for transaction isolation and cite the relevant sections.
```

Check or remove the integration with:

```bash
parrot codex status --json
parrot codex uninstall
```

Uninstall removes managed wiki and Bookstore integration artifacts. Indexed
books remain, as do foreign MCP tables and edited Bookstore skills.

Codex loads project MCP settings for trusted repositories and discovers skills
under `.agents/skills`. See the official [MCP configuration](https://developers.openai.com/codex/mcp)
and [skill discovery](https://developers.openai.com/codex/skills) documentation.

## Library and model selection

The library is selected from `PARROT_LIBRARY_DIR` or the target Git root's
`.parrot/library`, followed by the global `${PARROT_HOME:-~/.parrot}/library`.
Project books win ID collisions. To share books across worktrees, set an
absolute `PARROT_LIBRARY_DIR` before starting Codex, or use the global library.

The generated MCP configuration forwards `PARROT_LIBRARY_DIR`, `PARROT_HOME`,
`PARROT_BOOKSTORE_LLM`, and `PARROT_BOOKSTORE_LLM_LIGHT`. Optional LLM search
uses `PARROT_BOOKSTORE_LLM="provider:model"`; the lightweight model is an ID
from the same provider. Supply credentials through existing local configuration
or add the provider's environment variable name to `env_vars`. Keep credential
values out of committed TOML. Generated managed settings are refreshed on
reinstall; keep a separately maintained, unmarked Bookstore table if you need
custom MCP settings to persist.

Without an LLM, in-book and cross-book search require `bm25s`. Catalog search,
cards, inventory, tables of contents, and section reads work without it.

## Troubleshooting

- **No library found:** inspect `parrot bookstore locations`, index a book, or
  point `PARROT_LIBRARY_DIR` at an existing indexed library.
- **Missing imports:** install the existing bookstore/MCP extras in the Python
  environment used to run the installer, then rerun installation.
- **No MCP connection:** check project trust and restart Codex. `codex mcp list`
  shows registration; `/mcp` reports the connection inside the session.
- **CLI fallback:** `parrot bookstore search "topic" --catalog-only`, `toc`,
  `show`, and `search --book` locate candidates. `show` returns the catalog
  card, not section content; the CLI has no section-read command.
