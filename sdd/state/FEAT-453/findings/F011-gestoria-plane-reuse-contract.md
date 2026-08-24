---
id: F011
query_id: Q019
type: read
intent: Extract the concrete, merged contract for standing up a second domain wiki plane, now that FEAT-452 has landed
executed_at: 2026-08-23T10:05:00Z
depth: 1
parent_id: F009
---

# F011 — The merged three-step contract for a `gestoria` wiki plane, and the ValueError that forbids the obvious shortcut

## Summary

FEAT-452's completed task artifacts define a reusable, now-merged recipe for
adding a domain-scoped wiki plane. Three steps, plus one hard constraint that
rules out the approach most people would try first.

**The constraint.** A second plane is **not a parameter change**.
`LLMWikiToolkit._config_for()` (`wiki/toolkit.py:1205`) raises `ValueError` when
the requested `wiki_name` does not match the toolkit's own configured wiki, and
its docstring says so explicitly: *"Construct a separate LLMWikiToolkit for each
wiki instance."* Passing `"gestoria"` to an existing toolkit instance will
raise, not route. Because the planes use different storage roots they share no
manifest and no `wiki.db`, so there is no cross-instance consistency hazard.

**The recipe.**

1. Config constants + instance attributes for the plane (`<X>_WIKI_NAME`,
   `<X>_WIKI_STORAGE_DIR`, `<X>_FOLDER`) with constructor overrides mirroring
   the existing `wiki_name` / `wiki_storage_dir`.
2. A dedicated `_build_<x>_wiki_toolkit()` — a near-copy of
   `_build_wiki_toolkit()` pointed at the new storage root, with its own
   PageIndex plane and its own graph toolkit (`tenant_id=<plane name>`) — wired
   into `configure()` alongside the primary build, and bootstrapped once via the
   idempotent `create_wiki(<name>)`. Best-effort: failure logs a warning, leaves
   the handle `None`, and lets the agent boot.
3. Register the built store as a FEAT-450 namespace of kind `store` / backend
   `sqlite` pointing at the storage dir, via `wikitoolkit ns add`. Without this
   the plane is *written but unreachable* — `wikitoolkit query` reads exactly one
   plane, so an unregistered plane is invisible to both the CLI and the MCP
   tools. After registration `wikitoolkit query --ns <name>` reaches it and the
   default broadcast does too.

TASK-2382 carried a hard blocker on FEAT-450 being merged first. **Both
dependencies are now satisfied**: FEAT-450 merged (per `wikitoolkit ns list`
working and CLAUDE.md documenting `--ns`), and FEAT-452 merged via PR #1209.

## Citations

- path: `sdd/tasks/completed/TASK-2379-notes-wiki-plane.md`
  lines: 14-50
  symbol: "Module 2 — separate wiki plane"
  excerpt: |
    This is **not a parameter change** — it requires a second `LLMWikiToolkit`
    instance. `LLMWikiToolkit._config_for()` (`wiki/toolkit.py:1205`) **raises
    `ValueError`** when the requested `wiki_name` does not match the toolkit's
    own configured wiki. Its docstring is explicit: *"Construct a separate
    LLMWikiToolkit for each wiki instance."*
    Because the two planes use **different storage roots**, they share no
    manifest and no `wiki.db` — there is no cross-instance consistency hazard.

- path: `sdd/tasks/completed/TASK-2379-notes-wiki-plane.md`
  lines: 33-50
  symbol: "scope — build + bootstrap"
  excerpt: |
    Implement `async def _build_notes_wiki_toolkit(self) -> Optional[Any]` — a
    near-copy of `_build_wiki_toolkit()` (line 243) pointed at the notes storage
    root, with its own PageIndex plane and its own graph toolkit
    (`tenant_id=self.notes_wiki_name`).
    Call `create_wiki(self.notes_wiki_name)` once after construction ... It is
    **idempotent** ... Wire the call into `configure()`.
    Best-effort throughout: any failure logs a warning, leaves `_notes_wiki = None`.

- path: `sdd/tasks/completed/TASK-2382-register-notes-wiki-namespace.md`
  lines: 14-45
  symbol: "Module 6 — namespace registration"
  excerpt: |
    TASK-2379 gives audio notes their own wiki plane — written, but
    **unreachable**. Without namespaces, `wikitoolkit query` reads exactly one
    plane ...
    Its `store` namespace kind points at a pre-built store directory — exactly
    what the notes plane is. Registering it makes `wikitoolkit query --ns notes`
    (and the default `--ns all` broadcast) reach audio notes.
    - Register the notes plane as a namespace named `notes`, pointing at
      AUDIO_NOTES_WIKI_STORAGE_DIR (the `store` kind, `sqlite` backend).
    - Document the registration step in the operator runbook ... a fresh
      deployment must run it once.

- path: `sdd/tasks/completed/TASK-2382-register-notes-wiki-namespace.md`
  lines: 45-52
  symbol: "explicit non-scope"
  excerpt: |
    **NOT in scope**: injecting a `FederatedWikiStore` into `LLMWikiToolkit`
    (spec §1 Non-Goals ...); auto-registering the namespace from agent code.

## Notes

Two consequences worth carrying into the FEAT-453 spec:

1. **Namespace registration is an operator step, not agent code.** TASK-2382
   explicitly excludes auto-registering from agent code. A fresh FEAT-453
   deployment must run `wikitoolkit ns add` once for the `gestoria` plane, and
   that belongs in the runbook as an acceptance criterion.
2. **A note is not a memory.** The plane holds structured pages; reachability is
   what makes it a brain. An unregistered `gestoria` plane would silently
   accumulate accounting knowledge nobody can query — the same failure TASK-2382
   was written to prevent.
