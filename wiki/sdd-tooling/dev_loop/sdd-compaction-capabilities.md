# SDD compaction capability record

**Task**: TASK-3555 (FEAT-584, M0 spike) — `sdd/specs/sdd-execution-optimization.spec.md` §R6/M0/Q1.
**Author**: Claude (sdd-coder, native/sonnet), TASK-3555 attempt.
**Date**: 2026-09-21.
**Worktree HEAD at time of spike**: `ecc9605c6f72a73a1810f6243e39e2d11db79089` (branch
`feat-FEAT-584-sdd-execution-optimization--TASK-3555-a1-d4a1d075d068474fa254201190e68fa8`).
**Spec baseline referenced by the task**: dev commit `31f4c47afc72748a387ef8a8e55d0588894668e7`
(exists in the repository's object database; not an ancestor of this worktree's HEAD, so it is
cited only as the task's declared reference point, not verified as this branch's parent).

**Role and access boundary (read this before the rest of the document).** This spike was executed
by a coder subagent with `Read`/`Write`/`Edit`/`Bash` tools and no interactive Claude Code REPL of
its own. `$.session.compact()`, `$.agent.spawn()` and every other `$`-prefixed primitive quoted
below are internal to the Claude Code engine's plugin-hook sandbox: they are invoked automatically
by the engine when a registered hook module's `on(event, handler)` callback fires (`turn.complete`,
`session.compact`, …), never through a Bash command, an MCP tool, or a slash command typed by an
agent's own assistant-text output. No tool available to this role can register a hook module or
otherwise reach that `$` object. Consequently the **live, host-driven "does `$.session.compact()`
actually compact this specific loop" experiments for both the main conversation and a subagent are
blocked from this role** — not skipped by choice. Every verdict below says explicitly whether it
rests on (a) static verification of installed source/type files (real, byte-identical, hashed), (b)
a live invocation of the plugin's own compaction **library** function against a synthetic transcript
(real network call to the TypeSafe Jev backend, but bypassing the Claude Code engine entirely), or
(c) is unproven because it requires host access this role does not have. No verdict in this document
is inferred from documentation prose alone when the type declarations or a live call contradict or
fail to confirm it.

## Version and source evidence

| Item | Value | Source |
|---|---|---|
| Host (`claude` CLI) | `2.1.278 (Claude Code)` | `claude --version`, run from this worktree |
| Plugin cache version (directory / marketplace) | `0.3.0` | `~/.claude/plugins/cache/fast-jev-compaction/fast-jev-compaction/0.3.0/`, `.claude-plugin/marketplace.json` |
| Plugin `package.json` version | `0.2.0` | `~/.claude/plugins/cache/fast-jev-compaction/fast-jev-compaction/0.3.0/package.json` |
| Node | `v24.18.0` | `node --version` |
| `tsx` (used to run the library live) | `v4.23.13` | `node_modules/.bin/tsx --version` |

**Discrepancy found and recorded, not resolved by this task**: the installed plugin's own
`package.json` declares version `0.2.0` while the marketplace manifest and the cache directory name
both say `0.3.0`. This is the upstream plugin's own inconsistency (a stale `package.json` version
field), not something introduced here; it means "plugin_version" below is reported as `0.3.0`
(marketplace/cache — what Claude Code actually resolves and installs) with this caveat attached.

SHA-256 of every file this record cites, so a later run can confirm nothing moved under it:

| File | SHA-256 |
|---|---|
| `hooks/fast-jev.ts` | `94355ed9b4ba55d739fc24644d215969584f32f79b92a9aebcf4e7691f8d3cbe` |
| `types/claude-code.d.ts` | `1de8b590ce51c31acfd8e8c2229cc3221d16b5d07518075a690f51c2b069447d` |
| `src/compact.ts` | `6dcfe27bc00c1ba9065135a61a128bde0da41b9d300dbfd286de3cd6ce8b745b` |
| `src/client.ts` | `c324203676c7256abfd828110ab5181e2bb702c5b0acfb25f9930f1f529a1fff` |
| `src/types.ts` | `dbb401b0f9b09af3a8ec4bb331f2c7141dfa70dc38c3dbfd501183d44930973f` |
| `.claude-plugin/plugin.json` | `a104a866f35027aad2bdb98b02d875b6ddabac837f5d2f08af42488a9aff48e2` |
| `package.json` | `aaf7f9fbe78debc4c9acf94ed67d6e1fb92983bf5cb6aaa1c2d23c2a09d2ffb1` |

All paths are under `~/.claude/plugins/cache/fast-jev-compaction/fast-jev-compaction/0.3.0/`
(outside this repository; nothing under that directory was modified by this task).

`compaction_status()` (`packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/compaction.py:317`)
was run, unmodified, against two real roots instead of a synthetic temp dir, to see actual installed
state rather than trust the plugin cache's mere presence as a capability signal (§ "Contrato externo
observado" already warns against exactly that inference):

| Root | `compaction_plugin` | `compaction_function_hooks` | `compaction_api_key` |
|---|---|---|---|
| Main checkout (`/home/jesuslara/proyectos/ai-parrot`) | `true` | `true` | `true` |
| This worktree (`.claude/worktrees/feat-FEAT-584-.../TASK-3555-a1-...`) | `false` | `false` | `true` (from `TYPESAFE_API_KEY` env, not from a file) |

The worktree result is itself evidence, not a gap in this spike: `.claude/settings.json` is
git-ignored (per-checkout local state, confirmed via `git ls-files` returning nothing for that path
in this worktree and `git log` showing it was never tracked here), so a worktree created fresh from
`origin/dev` never inherits the main checkout's plugin wiring. Any M5 driver that assumes
"`compaction_status` true in the primary checkout" implies "true in every worktree" would be wrong;
it must call `compaction_status(worktree_root)` per worktree, exactly as the existing function
signature already allows — this is a real, previously-undocumented interaction between the FEAT-584
worktree-per-feature model and the R6 installation model.

## Main conversation experiment

**Attempted**: locating a call path, tool, or hook registration surface reachable from this coder
role that could invoke `$.session.compact()` against the main loop's own transcript. **Result:
none exists.** Verified by:

- Reading `hooks/fast-jev.ts:263-307` (hashed above): the only code that calls
  `$.session.compact()` is the plugin's own `on('turn.complete', ...)` handler, which the engine
  invokes directly; nothing in the plugin's public surface (`src/index.ts` re-exports only the pure
  library — `compact`, `resolveOptions`, `JevClient`, types) exposes a callable outside a registered
  hook module.
- `grep -rn "session\.compact\|PhaseBoundaryDriver\|phase_boundary" packages/` in this worktree
  returned no matches — confirming the spec's own "Does NOT Exist" section (no Python-side caller of
  this API exists yet to reuse or invoke).
- No MCP tool in this session's tool list, and no `claude` CLI subcommand (`claude --help` scope),
  exposes a "run one host turn and call `/compact`" primitive that isn't literally
  `claude -p /compact`, which the task explicitly forbids the worker from using.

**Verdict for "does `$.session.compact()` compact the main conversation": UNTESTED (host access
blocked from this role)**, not unsupported — the type contract (below) says it should work and
nothing observed contradicts that; it is simply not exercisable from here.

**What was tested instead, live**: the plugin's own compaction **library** (`src/compact.ts`,
`src/client.ts` — the same code `hooks/fast-jev.ts` calls after the engine hands it the messages),
run directly under `tsx` against a synthetic 10-message transcript with real tool calls/results and
a genuine, network-verified call to the TypeSafe Jev backend using the already-configured
`TYPESAFE_API_KEY` (value never printed or written to any file by this task; confirmed present via
`compaction_status()` above, not by echoing it).

Command (verbatim, run from the plugin's own installed directory so its relative imports resolve;
nothing under that directory was written):

```
cd ~/.claude/plugins/cache/fast-jev-compaction/fast-jev-compaction/0.3.0
node_modules/.bin/tsx <script importing src/compact.js + src/client.js by absolute path>
```

Result (`ok: true`, real HTTP round-trip to the Jev backend, `761 ms`):

```json
{
  "ok": true,
  "elapsed_ms": 761,
  "reduction_ratio": 0.13658686310620013,
  "stats": {
    "messagesBefore": 10, "messagesAfter": 9,
    "charsBefore": 3258, "charsAfter": 2813,
    "calls": 3, "kept": 0, "resultsDropped": 0, "callsDropped": 1, "pinned": 2,
    "stateTokens": 557, "stateStage": "full", "requests": 1, "ms": 761
  },
  "decisions": [
    { "id": "t1", "tool": "Bash", "keepCall": 0.15, "keepResult": 0.1, "action": "drop_call", "reason": "call_dropped" },
    { "id": "t2", "tool": "Read", "keepCall": 1, "keepResult": 1, "action": "keep", "reason": "pinned" },
    { "id": "t3", "tool": "Read", "keepCall": 1, "keepResult": 1, "action": "keep", "reason": "pinned" }
  ]
}
```

This is a real receipt of the Jev backend answering (model scored the oldest, non-pinned `Bash`
call as safe to drop at `keepCall=0.15`, kept the two pinned `Read` calls verbatim as designed), but
it is evidence for "the Jev backend is reachable and the scoring algorithm runs", not for "the Claude
Code host correctly wires `session.compact` to it for the main loop" — that half remains untested
per the paragraph above. It does, incidentally, reproduce the R6 fallback condition for free: this
transcript's `13.66%` reduction is below the plugin's own default `minReductionRatio` (`0.25`), so
`hooks/fast-jev.ts:271-277` would have logged `fallback to built-in summary (below 25% minimum: ...)`
and returned `next(event)` had this run through the real hook instead of the bare library — see
"Failure, fallback and interruption receipts" below for why this matters as a real, code-verified
branch rather than a hypothesis.

## Native subagent experiment

**Attempted**: the same reachability check as above, specifically for whether a subagent/fork loop's
compaction can be targeted. **Result: no live test was possible for the same reason** — this role
has no hook-registration surface, and additionally this coder is itself very plausibly running as a
subagent of some orchestrating session, which if anything sharpens the point: even from *inside* a
subagent's own execution, there is no tool-level path to its own `$.session.compact()`.

**Static evidence gathered instead** (`types/claude-code.d.ts`, hashed above):

- `SessionCompactArgs` (line 7186) — what a plugin's outbound `$.session.compact(args)` call
  accepts — is `{ instructions?: string }` only. **No `agentId` or other addressing field exists on
  the outbound call.** This directly confirms the spec's Codebase Contract claim
  ("SessionCompactArgs observado solo acepta instructions").
- `SessionCompactInput` (line 7225), the **inbound** event a `session.compact` hook receives, does
  carry `agentId?: string` (line 7238): "The id of the loop compacting, for a subagent's or a
  fork's own transcript; absent for the main conversation." So core *does* track which loop is
  being compacted and stamps that identity onto the event a hook observes — read access to context
  identity exists.
- The same doc block adds: "`$.session.messages()` is the main conversation whatever this [agentId]
  names." That is the one piece of type-level text that could be read as "the plugin's own `$`
  object always reflects the main loop, regardless of which loop's `session.compact` event is being
  handled" — which, if true, would mean a `turn.complete` handler invoked for a *subagent's* turn and
  calling `$.session.compact()` from inside that callback might still compact the **main** loop, not
  the subagent. The type declarations do not state this either way for the `compact()` *call itself*
  (only for the unrelated `.messages()` read accessor), so this is flagged as a genuine, unresolved
  ambiguity in the documented contract, not resolved by inference.
- `turn.complete`'s own doc (line 3358, line 8742-8744) confirms the hook fires for subagent turns
  too ("Every hook sees a subagent's turn, so a hook that spawns sees its children's turns too and
  bounds itself"), which means `hooks/fast-jev.ts`'s installed `on('turn.complete', ...)` handler
  (the one that calls `$.session.compact()` automatically at 60% usage) **does** run once per
  subagent turn as well as once per main turn — it is not main-loop-only code. Whether its
  parameterless `$.session.compact()` call, made from within a subagent turn's callback, ends up
  compacting that subagent's transcript or the main one is exactly the ambiguity above.

**Verdict: `unsupported_context` (pending runtime proof)** — per R6's own contracted default for
this exact situation ("No asumir direccionamiento; solo habilitar si la prueba del runtime demuestra
que actúa sobre ese loop. En caso contrario, `unsupported_context`"). This spike did not obtain that
runtime proof, could not obtain it from this role, and explicitly does not claim the capability.

## Between-turn boundary and resumption

Static, from `types/claude-code.d.ts` (hashed above), not live-tested (same access boundary as
above):

- `$.session.compact()` doc (line 2344-2354): "the event `session.compact` with `trigger` `plugin`,
  the same call `/compact` makes, **between turns**. It runs through every hook but the calling one,
  then core: a summary and the kept messages in the transcript's place. Resolves `{ skip }` when a
  hook vetoed it; **rejects while a turn runs**." This directly confirms R6's stated sequencing
  constraint ("Nunca dentro de una llamada de tool activa ni mientras se espera trabajo vivo") is
  also the host's own enforced contract, not just an SDD policy choice — calling it mid-turn is a
  rejected promise, not merely discouraged.
- `hooks/fast-jev.ts:261,293-306` guards re-entrancy with a local `compacting` boolean around its own
  `turn.complete` handler, so the installed hook does not double-request compaction from within its
  own callback; this is the plugin's own concurrency guard, independent of and in addition to
  whatever SDD-level "no more than one attempt per checkpoint_id+context_id" bookkeeping R6 requires
  at the M5 layer.
- **Resumption mechanism**: there is no separate "resume" call. `SessionCompacted.messages` (line
  7198-7219) *is* the new transcript, put in the live transcript's place; the very next turn simply
  reads that mutated transcript. No checkpoint object, receipt token, or resume handle is returned by
  the host beyond the optional `tokensBefore`/`tokensAfter` counts. **Consequence for M5**: the
  "reanudación" the driver needs to hand to a reviewer is not something the host will ever supply —
  it has nothing to resume, because it already replaced the transcript in place before the next turn
  starts. The reviewer-continuity mechanism R6/M5 needs must be built entirely at the SDD layer
  (the existing `ReviewCheckpoint`/manifest machinery from R4/R5), using the host's compaction only
  as an optional, best-effort context-size reduction that happens to have occurred before that
  checkpoint was read — never as something the SDD flow waits on a host "resume" event for, because
  no such event exists in the reviewed surface.

## Failure, fallback and interruption receipts

| Case | Evidence | Status |
|---|---|---|
| Jev fails (network/auth error, bad response) | `hooks/fast-jev.ts:283-289` — `catch` block always calls `notify(...)` then `return next(event)` (host's own built-in summary) | **Proven from source**; not exercised live (would require deliberately breaking the API key, which risks leaving the shared credential in a bad state — out of scope for this task) |
| Jev succeeds but reduction `< minReductionRatio` (0.25 default) | `hooks/fast-jev.ts:271-277` | **Proven from source AND reproduced live** — the synthetic-transcript run above landed at `13.66%`, under the 25% floor, which is exactly this branch's trigger condition |
| Runtime busy / mid-turn compact attempt | `$.session.compact()` doc: "rejects while a turn runs" | **Proven from source only** — a live reproduction would require racing a real host turn, not reachable from this role |
| Timeout / interruption of an in-flight compaction | No distinct timeout/interruption type or event was found anywhere in `types/claude-code.d.ts` for `session.compact` specifically (only the generic promise-rejects-or-resolves contract above) | **Not proven, not found** — R6's "timeout" case at the SDD layer must be implemented as a bounded `await` around the host promise by whatever eventually drives it, since the host contract itself defines no timeout semantics of its own |

No credentials, secrets, or SDK source were copied into this repository or into this document beyond
the file hashes and version strings above; the `TYPESAFE_API_KEY` value itself is never included.

## Capability matrix

| host_version | plugin_version | context_kind | can_target_context | between_turns | resume_mechanism | receipt_fields | evidence_refs | verdict |
|---|---|---|---|---|---|---|---|---|
| Claude Code 2.1.278 | fast-jev-compaction 0.3.0 (cache/marketplace; `package.json` stale at 0.2.0) | main conversation | not proven (no addressing needed — implicit default target of the plugin's own `$.session.compact()`) | yes, by host contract (`rejects while a turn runs`) | none — host replaces transcript in place, no resume handle; SDD-level continuity must use R4/R5 `ReviewCheckpoint` | `stats.{messagesBefore,messagesAfter,charsBefore,charsAfter,calls,kept,resultsDropped,callsDropped,pinned,stateTokens,stateStage,requests,ms}` from the library; host adds only `tokensBefore?/tokensAfter?` | `hooks/fast-jev.ts:263-307`, `types/claude-code.d.ts:2344-2354`, live library run (this doc, § Main conversation experiment) | **untested (host access blocked from this role)** — contract supports it, nothing observed contradicts it, no live host receipt obtained |
| Claude Code 2.1.278 | fast-jev-compaction 0.3.0 | subagent / fork | **unsupported by outbound signature** (`SessionCompactArgs` = `{instructions?}` only, no `agentId`); whether an implicit "current loop" scoping exists is undetermined | plugin's `turn.complete` handler does fire once per subagent turn too (`e.agentId` present) | same as main — no host resume API found | same shape as main, if it worked at all | `types/claude-code.d.ts:7186-7192,7225-7239,8742-8745` | **unsupported_context (pending runtime proof)** — R6's own contracted default; no runtime proof exists |
| Claude Code 2.1.278 | fast-jev-compaction 0.3.0 | Jev backend only (library, bypassing the host) | n/a (not a host call) | n/a | n/a | `CompactResult.stats` (see above) | live run, this doc | **proven** — real, network-verified call; used here only to validate the fallback-on-low-reduction branch, not host wiring |
| any other host (Codex/Antigravity/etc.) | n/a | any | no adapter installed or verifiable from this repo's tooling | n/a | n/a | n/a | spec §"Contrato externo observado", R6 table | **unsupported_host** (unchanged from spec's existing default; not re-tested here, no such host was available in this task) |

## Proposed specification amendment

For the spec author to apply (this task does not edit `sdd/specs/sdd-execution-optimization.spec.md`
itself, per its own instruction that the amendment is proposed here and applied afterwards):

1. **M5's driver cannot be "a Python function that calls `$.session.compact()`"** — no such call
   surface exists outside a registered Claude Code plugin hook process. Rescope M5's
   `phase_boundary.py` (already the decided path) to a **receipt reader**, not a caller:
   - `compaction_status(worktree_root)` gates everything first; anything false ⇒
     `CompactionReceipt(status="unsupported_host", ...)` immediately, no attempt.
   - For `context_kind="main"` only (subagents/forks stay `unsupported_context` until a future spike
     obtains the runtime proof this one could not), emit the already-declared `compaction.requested`
     `WorkflowEvent` (spec §"Eventos mínimos" already lists it) and then look for the plugin's own
     `$.ui.log` receipt line (the `"<percent>% reduction; ..."` / `"fallback to built-in summary
     (...)"` text `hooks/fast-jev.ts:179-190,270-289` already emits) in whatever transcript/log
     surface the host already exposes to `coder_record_native_observation` (R2/R3, already an
     existing contract) — parse it into `CompactionReceipt.status="completed"|"failed"`,
     `backend="jev"|"builtin"`, and the before/after figures when present.
   - No line found within a bounded wait ⇒ `status="unknown"`, never inferred as `"completed"` from
     silence (this repeats R6's own explicit prohibition, now grounded in "there is no host resume
     event to wait on instead").
2. Record the worktree-vs-main-checkout `compaction_status` divergence found above as a precondition:
   the driver must resolve status per the **worktree it is running in**, never assume the primary
   checkout's installation extends to a feature worktree.
3. Leave subagent/fork addressing as `unsupported_context` in the spec's R6 table exactly as already
   written; this spike found nothing to change there beyond confirming, from the type declarations
   themselves (not merely inferring), that the ambiguity is real and specifically located in
   `$.session.messages()`'s documented main-loop pinning versus `session.compact`'s per-loop
   `agentId` on the *inbound* event only.
4. Q1 stays open. A follow-up spike with genuine host access (an operator driving an actual
   interactive Claude Code session with a real subagent spawn, watching the transcript for which
   loop's `session.compact` event fires and with what `agentId`) is the only way to close it; this
   task registers that as the concrete blocker rather than guessing.
