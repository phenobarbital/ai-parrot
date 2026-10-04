---
id: F018
query_id: Q018
type: grep
intent: How the contracts CLI is registered; mechanism a `parrot manuals` group must use
executed_at: 2026-09-24T23:21:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F018 — Contracts CLI is argparse via `python -m`; `parrot` subcommands use the LazyGroup `_lazy_commands` dict

## Summary
`contracts/cli.py` builds an `argparse.ArgumentParser(prog="python -m parrot_tools.contracts")`. `main(argv, *, factory, stream)` needs an injected service factory; without one it prints a hint and returns 2. `__main__.py` just calls `main()`. The `parrot` console script is `parrot.cli:cli`, a `click.group(cls=LazyGroup)` whose subcommands are listed in the `cli._lazy_commands` dict, which maps each name to a module path. `get_command` imports that module and returns the attribute named `cmd_name.replace("-","_")`. Optional install hints live in `cli._lazy_extras`. `contracts` is not registered there, and ai-parrot-tools declares no `[project.scripts]` or entry points.

## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/cli.py`
  lines: 58-66
  symbol: `build_parser`
  excerpt: |
    def build_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="python -m parrot_tools.contracts",
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/cli.py`
  lines: 175-175
  symbol: `run_command`
  excerpt: |
    async def run_command(args, *, library, service, graph_loader=None, temporal=None,
                          tenant_context=None) -> tuple[int, dict[str, Any]]
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/cli.py`
  lines: 362-391
  symbol: `main`
  excerpt: |
    def main(argv=None, *, factory: Optional[Callable[[argparse.Namespace], dict[str, Any]]] = None,
             stream: Any = None) -> int:
        if factory is None:
            print("No service factory configured. ...", file=out)
            return 2
        services = factory(args)
        code, payload = asyncio.run(run_command(args, **services))
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/__main__.py`
  lines: 1-19
  symbol: `__main__`
  excerpt: |
    from .cli import main
    if __name__ == "__main__":
        sys.exit(main())
- path: `packages/ai-parrot/pyproject.toml`
  lines: 199-206
  symbol: `[project.scripts]`
  excerpt: |
    parrot = "parrot.cli:cli"
    parrot-graphindex = "parrot.knowledge.graphindex.cli:main"
    wikitoolkit = "parrot.knowledge.wiki.entry:main"
    bookstore = "parrot.knowledge.bookstore.cli:main"
- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 71-100
  symbol: `LazyGroup.get_command`
  excerpt: |
    module_path = self._lazy_commands[cmd_name]
    mod = importlib.import_module(module_path)
    ...
    attr_name = cmd_name.replace("-", "_")
    return getattr(mod, attr_name, None) or getattr(mod, cmd_name, None)
- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 103-131
  symbol: `cli`, `cli._lazy_commands`
  excerpt: |
    @click.group(cls=LazyGroup)
    def cli():
    cli._lazy_commands = {
        "setup": "parrot.setup.cli",
        "wiki": "parrot.knowledge.wiki.cli",
        "e2e": "parrot.e2e.cli",   # ships in ai-parrot-server
        "serve": "parrot.integrations.agentd.cli",
- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 135-145
  symbol: `cli._lazy_extras`
  excerpt: |
    _E2E_INSTALL_HINT = "ai-parrot-server: pip install ai-parrot-server"
    cli._lazy_extras = { "serve": _AGENTD_INSTALL_HINT, ..., "e2e": _E2E_INSTALL_HINT }
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/service.py`
  lines: 105-212
  symbol: `ContractsAnswerService`, `ContractsAnswerService.answer`
  excerpt: |
    class ContractsAnswerService:  "One authorization, evidence and audit gate for every answer path."
    async def answer(...)  # L145-212
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/verifier.py`
  lines: 102-206
  symbol: `CitationVerifier`, `CitationVerifier.verify`
  excerpt: |
    class CitationVerifier: "Verify a draft against archived evidence and release an answer."
    def verify(...)  # L114-206
- path: `packages/ai-parrot-tools/src/parrot_tools/contracts/jobs.py`
  lines: 193-824
  symbol: `ingest_delta`, `renewals_report`, `obligations_digest`
  excerpt: |
    193: ingest_delta  — "Ingest changes from one configured source."
    701: renewals_report — "Bucket upcoming renewals into 30/60/90-day windows."
    758: obligations_digest

## Notes
- WRONG in the brainstorm: `parrot contracts …` does not exist.
- To add `parrot manuals`, put `"manuals": "parrot_tools.procedures.cli"` in `_lazy_commands` (core file L109) and have that module expose a click `manuals` group. Since ai-parrot-tools is a separate package, add `_lazy_extras["manuals"] = "ai-parrot-tools: pip install ai-parrot-tools"` so a missing install gives a clear message, as `e2e` and the agentd commands already do. The contracts argparse pattern can't be plugged into the click LazyGroup directly.

