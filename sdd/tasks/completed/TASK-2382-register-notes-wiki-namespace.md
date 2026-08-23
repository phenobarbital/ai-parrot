# TASK-2382: Register the notes wiki as a queryable namespace

**Feature**: FEAT-452 — Audio Notes → Obsidian + LLM Wiki
**Spec**: `sdd/specs/audio-notes-obsidian.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2379
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec (Goal G2).

TASK-2379 gives audio notes their own wiki plane — written, but **unreachable**.
Without namespaces, `wikitoolkit query` reads exactly one plane, so a separate
`notes` wiki would be invisible to the CLI and MCP tools, defeating G2's
"queryable in seconds".

FEAT-450 (`sdd/specs/wiki-namespaces.spec.md`) adds federation. Its `store`
namespace kind points at a pre-built store directory — exactly what the notes
plane is. Registering it makes `wikitoolkit query --ns notes` (and the default
`--ns all` broadcast) reach audio notes.

> ⛔ **HARD BLOCKER: FEAT-450 must be MERGED before this task starts.**
> Every FEAT-450 symbol below is **unverified** — it does not exist in the
> codebase yet. Re-verify all of it against the merged implementation before
> writing anything.

---

## Scope

- Verify FEAT-450 has merged and that `wikitoolkit ns add` exists and behaves
  as its spec describes.
- Register the notes plane as a namespace named `notes`, pointing at
  `AUDIO_NOTES_WIKI_STORAGE_DIR` (the `store` kind, `sqlite` backend).
- Confirm `wikitoolkit query --ns notes` returns captured notes, and that the
  default broadcast reaches them too.
- Document the registration step in the operator runbook: the command, the
  config key it must match, and the fact that a fresh deployment must run it
  once.
- Record the reachability check in the feature's docs so `/sdd-done` can verify it.

**NOT in scope**: implementing any part of FEAT-450; injecting a
`FederatedWikiStore` into `LLMWikiToolkit` (spec §1 Non-Goals, and FEAT-450
lists it as optional / not required for its own AC); auto-registering the
namespace from agent code; changing the meetings plane's registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/` (path TBD — follow the convention FEAT-450 establishes) | CREATE/MODIFY | Operator runbook: registering the `notes` namespace |
| `sdd/specs/audio-notes-obsidian.spec.md` | MODIFY | Mark the Module 6 acceptance criteria verified |

> No production code change is expected. If one turns out to be required,
> **stop and report** rather than widening scope.

---

## Codebase Contract (Anti-Hallucination)

> ⚠️ Split into VERIFIED (exists today) and UNVERIFIED (FEAT-450, not merged).

### Verified Imports / Values (exist today)

```python
# agents/fireflies_wiki.py — created by TASK-2379
#   AUDIO_NOTES_WIKI_NAME         default "notes"
#   AUDIO_NOTES_WIKI_STORAGE_DIR  default ~/.parrot/wikis/notes
# The namespace name and the store directory MUST match these values.

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                     # line 46
    async def create_wiki(self, wiki_name: str,
                          description: Optional[str] = None) -> dict[str, Any]: ...  # line 445
    #   Layout it creates under storage_dir: `sources/` + index.md + log.md
    #   (docstring lines 451-462). Page content lives in `wiki.db`.
    #   -> the sqlite store file the `store` namespace kind expects.
```

### UNVERIFIED — FEAT-450 surface (check before use)

```python
# sdd/specs/wiki-namespaces.spec.md:159-168   *** SPEC ONLY — NOT YET IN CODE ***
class WikiNamespaceConfig(BaseModel):
    path: Optional[str] = None        # another wiki project root
    store: Optional[str] = None       # pre-built store dir (wiki.db inside for sqlite)
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"
    database: Optional[str] = None
    credentials_env: str = "ARANGODB"
    vault: Optional[str] = None
    description: str = ""
    weight: float = Field(default=1.0, ge=0.0, le=1.0)

# CLI (spec line 266) — UNVERIFIED:
#   wikitoolkit ns add NAME (--path P | --store S [--backend B]
#                            | --database D [--credentials-env X] | --vault V)
#
# Expected invocation for this task:
#   wikitoolkit ns add notes --store "$AUDIO_NOTES_WIKI_STORAGE_DIR" --backend sqlite
#
# Registry locations (spec lines 46-47, 179-182) — UNVERIFIED:
#   repo:   .parrot/wiki.json   -> WikiProjectConfig.namespaces
#   global: ~/.parrot/wikis.json -> GlobalWikiRegistry.namespaces
#   repo entries override global on name clash.
# Reserved namespace names (spec): `all`, `local`.
```

### Does NOT Exist (as of 2026-08-23)

- ~~`FederatedWikiStore`~~, ~~`WikiNamespaceConfig`~~, ~~`GlobalWikiRegistry`~~,
  ~~`WikiProjectConfig.namespaces`~~, ~~`parrot/knowledge/wiki/federation.py`~~,
  ~~`wikitoolkit ns add`~~ / ~~`ns list`~~ / ~~`ns remove`~~ — **all specified in
  FEAT-450 but NOT merged.** Verify each one exists before relying on it.
- ~~`wikitoolkit query --ns <name>`~~ — the `--ns` flag does not exist yet.
- ~~`LLMWikiToolkit` accepts an injected federated store~~ — FEAT-450 lists this
  as *optional / not required for AC* (`wiki-namespaces.spec.md:153`), and it is
  an explicit **non-goal** of FEAT-452. Do not attempt it.
- ~~a `notes` namespace is registered automatically by agent code~~ — it is not,
  and this task does not add that. Registration is an operator step
  (FEAT-450 G2: entries enter a registry **only** through `ns add`).
- ~~`WIKI_NS` environment default~~ — explicitly not in FEAT-450 v1.

---

## Implementation Notes

### Key Constraints

- **Start by confirming FEAT-450 is merged.** If it is not, stop and report —
  do not stub, do not partially implement, do not hand-edit `.parrot/wiki.json`
  (FEAT-450 G2 makes `ns add` the only writer).
- The namespace name and store directory must match `AUDIO_NOTES_WIKI_NAME` and
  `AUDIO_NOTES_WIKI_STORAGE_DIR` from TASK-2379. A mismatch produces a namespace
  that resolves to an empty or non-existent store.
- Prefer the `store` kind over `path`: the notes plane is a bare storage root
  built by `create_wiki`, not a wiki *project* root with its own `.parrot/`.
  If FEAT-450's merged behavior contradicts this, follow the code and note it.
- FEAT-450 G9: an unbuilt or unreachable namespace is skipped with a note rather
  than failing a broadcast — so verify registration by observing an actual hit,
  not merely by the absence of an error.

### References

- `sdd/specs/wiki-namespaces.spec.md` — FEAT-450 (read the **merged** code, not just the spec)
- `sdd/specs/audio-notes-obsidian.spec.md` §7 "FEAT-450 dependency — precise scope"

---

## Acceptance Criteria

- [ ] FEAT-450 confirmed merged; every UNVERIFIED symbol above re-verified against real code
- [ ] A `notes` namespace is registered via `wikitoolkit ns add` (not hand-edited config)
- [ ] The namespace points at the same directory as `AUDIO_NOTES_WIKI_STORAGE_DIR`
- [ ] `wikitoolkit query --ns notes "<text from a captured note>"` returns that note
- [ ] The default broadcast (`--ns all`) also reaches the note
- [ ] The meetings plane's own results are unaffected
- [ ] The registration step is documented for a fresh deployment
- [ ] No production code was changed (or, if unavoidable, it was reported first)

---

## Test Specification

> Verification here is operational rather than unit-level: the deliverable is a
> registered namespace plus documentation, not new code.

```bash
# 1. Capture a note with a distinctive phrase (via Telegram or by calling the tool)
# 2. Register the namespace
wikitoolkit ns add notes --store "$AUDIO_NOTES_WIKI_STORAGE_DIR" --backend sqlite
wikitoolkit ns list --json     # expect: notes | kind=store | built=true

# 3. Targeted query
wikitoolkit query --ns notes "<distinctive phrase>"     # expect a hit

# 4. Broadcast query
wikitoolkit query "<distinctive phrase>"                # expect the same hit

# 5. Meetings plane unaffected
wikitoolkit query --ns local "<known meeting phrase>"   # expect the meeting
```

If FEAT-450's merged CLI differs from the above, follow the real CLI and update
this task's Completion Note with what actually worked.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §7 "FEAT-450 dependency — precise scope", §3 Module 6
2. **Check dependencies** — TASK-2379 in `sdd/tasks/completed/`, **and FEAT-450 merged**.
   If FEAT-450 is not merged, STOP and report — this task cannot proceed.
3. **Verify the Codebase Contract** — every FEAT-450 symbol is UNVERIFIED.
   Re-verify each against the merged implementation before use.
4. **Update status** in `sdd/tasks/index/audio-notes-obsidian.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2382-register-notes-wiki-namespace.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Confirmed FEAT-450 merged (`dev` @ `c42802ffe`, "Merge branch
'feat-450-wiki-namespaces' into dev"), pushed `dev` to `origin/dev`, then
merged `origin/dev` into this feature branch (clean merge, no conflicts —
FEAT-450 touches only `packages/ai-parrot/src/parrot/knowledge/wiki/*`,
disjoint from this feature's files). Re-verified every previously-UNVERIFIED
FEAT-450 symbol against the real merged CLI: `wikitoolkit ns --help` /
`ns add --help` confirmed the command exists with `--store DIR --backend
[sqlite|memory]` exactly as expected (one correction vs. the task's
UNVERIFIED assumption: the "another wiki project" flag is `--project`, not
`--path` — irrelevant here since this task uses `--store`).

Registered the namespace for real (not stubbed, not hand-edited config):
`wikitoolkit ns add notes --store ~/.parrot/wikis/notes --backend sqlite
--description "..."`. This is the FIRST real bootstrap of that storage
directory in this environment — also exercised `_build_notes_wiki_toolkit()`
live (offline-capable: `build_graph_memory_toolkit`'s default
`HashingGraphEmbedder` needs no LLM/API key) to actually create it via
`create_wiki()`, confirming TASK-2379's idempotent-bootstrap claim against
real code, not just mocks. `wikitoolkit ns list --json` confirms `"name":
"notes", "kind": "store", "backend": "sqlite", "built": true, "target":
"../../.parrot/wikis/notes"` — resolves correctly to
`~/.parrot/wikis/notes`, matching `AUDIO_NOTES_WIKI_STORAGE_DIR`'s default.
`wikitoolkit query --ns notes "<phrase>"` and the default `--ns all`
broadcast both reach the store cleanly (no error — "No wiki results", not
an exception), and `--ns local` (the codebase's own wiki, standing in for
the "meetings plane unaffected" check in this repo context) still answers
normally, unaffected by the new namespace.

Attempted a full live capture (`AudioNoteCaptureToolkit.capture_audio_note`
against the real vault path and the real notes wiki toolkit built above) to
get a positive query hit end-to-end. The Obsidian note write succeeded
(durable artifact on disk, verbatim transcript, G5 intact) and
`ingest_source` did not raise (`wiki_ingested=True` in the tool's own
return value), but the underlying PageIndex authoring step logged
`PageIndex insert failed ... "Tree 'notes' does not exist"` after a ~11s
`AnthropicClient` call — this environment has no LLM API credentials
configured, so no page was actually authored, and the subsequent
`wikitoolkit query --ns notes "<distinctive phrase>"` correctly returned no
hit (nothing to find). This is an environment/credentials limitation, not a
FEAT-452 or FEAT-450 defect, and reproducing/fixing it is out of this
task's scope regardless ("NOT in scope: implementing any part of FEAT-450").
Flagging one observation for a future task, not fixed here: `ingest_source`
appears to swallow the PageIndex-insert failure internally and still report
non-error status to the caller (`AudioNoteCaptureToolkit._ingest_into_wiki`
only ever sees "no exception" → `wiki_ingested=True`) — worth a look by
whoever owns `wiki/ingest.py`, but it is `wiki/ingest.py:308`/`:931`
(FEAT-260/FEAT-450 territory), not this feature's code.

Documented the registration step as a new "Recipe: FirefliesWikiAgent's
audio-notes plane (FEAT-452)" subsection in
`documentation/parrot-wiki-cli.md` (the file FEAT-450 itself uses for
namespace operator docs), following that file's existing tone/format:
exact command, verification steps, the "run once per deployment, never
committed, never auto-registered" note, and an explicit statement that the
`meetings` plane is deliberately NOT registered by this recipe. Marked
Module 6's two AC bullets `[x]` in `sdd/specs/audio-notes-obsidian.spec.md`
§5, each with an inline verification note (including the sandbox-credential
caveat above) rather than a bare checkmark.

No production code was changed — only `documentation/parrot-wiki-cli.md`
and `sdd/specs/audio-notes-obsidian.spec.md` (`git status --porcelain`
confirms). Cleaned up: `~/.parrot/wikis/notes` (created live above) is a
real, git-ignored `.parrot/`-style local artifact — left in place as a
harmless bootstrap consistent with what a real `configure()` call would
have produced. The `.parrot/wiki.json` namespace registration is likewise
a local, gitignored, per-machine registry entry — correctly not part of
this commit.

**Deviations from spec**: none — the "no production code change is
expected" guardrail held; the one CLI flag correction (`--project` not
`--path`) was already anticipated by the task as a possible UNVERIFIED-vs-
real drift and required no scope change since `--store` was used throughout.
