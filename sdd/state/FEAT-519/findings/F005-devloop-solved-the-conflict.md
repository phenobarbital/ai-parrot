---
id: F005
query_id: Q007,Q008,Q020
type: read
intent: Assess devloop/console.py + renderer.py as the in-repo homologation reference
executed_at: 2026-09-02T21:59:00Z
parent_id: F004
depth: 1
---

# F005 — `parrot devloop` ALREADY solved the Live-vs-prompt_toolkit conflict with a pause/resume discipline

## Summary

A sibling command in the same package runs `rich.live.Live` *and*
`prompt_toolkit.prompt_async()` together successfully. `RunView` owns a `Live`
region with `pause()`/`resume()`/`stop()` methods; `DevLoopConsole` calls
`pause()` before every interactive prompt and `resume()` after, under a single
`patch_stdout()`. The module docstring names the rule: "Modal terminal
discipline: one writer at a time (pause/resume Live around prompts)." This means
the constraint recorded in F004 is **not unsolvable** — it is unsolved *in the
agent REPL only*, and the solution already exists ~200 lines away.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/devloop/console.py`
  lines: 1-5
  symbol: module docstring
  excerpt: |
    ``DevLoopConsole`` orchestrates: wizard → dispatch → Rich Live rendering →
    interactive gate resolution → slash commands. Modal terminal discipline:
    one writer at a time (pause/resume Live around prompts).

- path: `packages/ai-parrot/src/parrot/cli/devloop/renderer.py`
  lines: 1-6
  symbol: module docstring
  excerpt: |
    Run renderer — Rich Live envelope painter for ``parrot devloop``.
    Polls ``SessionHost.replay_since(last_seq)`` on a ticker and maps action
    types to Rich renderables in a scrolling Live region.

- path: `packages/ai-parrot/src/parrot/cli/devloop/renderer.py`
  lines: 82-107
  symbol: `RunView.pause` / `RunView.resume` / `RunView.run_live`
  excerpt: |
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    async def run_live(self, stop_event=None) -> None:
        with Live(
            ...
            refresh_per_second=8,
            transient=False,

- path: `packages/ai-parrot/src/parrot/cli/devloop/console.py`
  lines: 903-969
  symbol: `DevLoopConsole._handle_gates`
  excerpt: |
    self._active_view.pause()
    ...
    resolution = await self._session.prompt_async(...)
    ...
    self._active_view.resume()

- path: `packages/ai-parrot/src/parrot/cli/devloop/console.py`
  lines: 816
  symbol: `DevLoopConsole` main loop
  excerpt: |
    with patch_stdout():

- path: `packages/ai-parrot/src/parrot/cli/devloop/__init__.py`
  lines: null
  symbol: devloop package layout
  excerpt: |
    devloop/{__init__.py, bootstrap.py, console.py, intake.py, renderer.py}

## Notes

`RunView` is coupled to dev-loop `SessionHost` envelope semantics
(`replay_since`, `_handle_dispatch_delta`, gate handlers), so it is a *pattern*
to homologate against, not a class the agent REPL can instantiate directly.
