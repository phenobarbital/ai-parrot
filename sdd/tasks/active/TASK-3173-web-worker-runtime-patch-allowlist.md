# TASK-3173: Web Worker runtime & patch allowlist — `renderers/worker_bridge.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3161
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13, resolving OQ-7 (G6/C6). Today's client bridge in
`renderers/html5.py` only does `fetch()`-based remote event dispatch — no
Web Worker exists anywhere in this renderer (spec §6 "Does NOT Exist"). A
Web Worker has no DOM, so client-side snippet logic returns **typed patch
operations** that the HOST PAGE applies; the host owns a six-operation
allowlist and anything else is discarded and logged. Because the server
re-runs every rule with a counterpart (G7/C7, unaffected by this task), a
forged or malformed patch can at worst mislead the UI — never corrupt a
submission.

**Anchor drift from the spec's Codebase Contract**: the spec (verified
2026-08-24) cites `_LIFECYCLE_SCRIPT_TEMPLATE` at `renderers/html5.py:423`
(used at `:574`). **Re-verified at task-writing time (2026-09-11): the
template is now at line 479, used at line 630.** Use these corrected line
numbers, not the spec's.

---

## Scope

- Implement `renderers/worker_bridge.py`: a Python module that generates
  the JS "Worker boot block" (a `postMessage` request/response protocol
  between the host page and a Web Worker) as a string, plus the **host-
  side** patch-allowlist enforcement logic — described here as
  Python-callable validation so it can be unit-tested, even though the
  actual host-page enforcement runs as injected JS (document this
  duality clearly in the module, since testing generated JS strings from
  Python has real limits — see Test Specification).
- Implement the six-operation allowlist EXACTLY as specified:
  `set_visibility`, `set_required`, `set_enabled`, `set_value`,
  `set_hint`, `narrow_options` — each over an existing field UID, never
  new fields/structure/identity/action-URL/CSRF-token.
- Wire the generated boot block into `_LIFECYCLE_SCRIPT_TEMPLATE`
  (`renderers/html5.py:479`, corrected line number) as an **additive**
  block — the existing `fetch`-based remote bridge must be preserved
  intact (spec Integration Points table: "The existing remote-fetch
  bridge is preserved intact").
- Write `packages/parrot-formdesigner/tests/unit/test_worker_bridge.py`.

**NOT in scope**: the TS source / bundler (TASK-3174 compiles snippet TS
halves to the `client.js` a bundle carries — this task's Worker *boot*
block is separate, generic infrastructure that loads and runs whatever
compiled snippet JS a form's bundles provide, it does not compile
anything itself); server-side patch re-validation (there is none — the
server never sees client patches at all, per G7, it only re-runs the
Python half authoritatively).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/worker_bridge.py` | CREATE | Boot-block generator + patch validation |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | Inject the Worker boot block into `_LIFECYCLE_SCRIPT_TEMPLATE` |
| `packages/parrot-formdesigner/tests/unit/test_worker_bridge.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.snippets import SnippetBundle  # TASK-3161
```

### Existing Signatures to Use (RE-VERIFIED 2026-09-11, corrected from spec)
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py
# _LIFECYCLE_SCRIPT_TEMPLATE definition starts at line 479 (spec said 423 — STALE)
_LIFECYCLE_SCRIPT_TEMPLATE = (
    "\n<script>\n"
    "(function() {\n"
    "  var FORM_ID = __FORM_ID__;\n"
    "  var FORM_UID = __FORM_UID__;\n"
    "  var TENANT = __TENANT__;\n"
    "  var EVENTS_CONFIG = __EVENTS_CONFIG__;\n"
    # ... (existing fetch-based bridge body, unmodified by this task) ...
)

# Used (interpolated) at line 630 (spec said 574 — STALE):
def _inject_lifecycle(self, html_str: str, form: FormSchema, csrf_token: str | None) -> str:
    ...
    script = (
        self._LIFECYCLE_SCRIPT_TEMPLATE.replace("__FORM_ID__", json.dumps(form.form_id))
        # ... more .replace() calls follow ...
    )
```

### Does NOT Exist
- ~~A Web Worker anywhere in `renderers/html5.py`~~ — confirmed absent;
  `_LIFECYCLE_SCRIPT_TEMPLATE` only does `fetch`-based remote bridging
  (spec §6, re-confirmed by reading the template at task-writing time).
- ~~`renderers/worker_bridge.py`~~ — created by this task.
- ~~Any DOM access from Worker-generated code~~ — a Web Worker has no
  `document`/`window` by browser design; do not write JS that assumes it
  does (e.g. no `document.getElementById` inside the Worker-side script —
  only inside the HOST-side script that applies patches).
- ~~Markup/structure patch operations~~ — there is no `innerHTML` path
  and none should be added; patches are the six named operations only.

---

## Implementation Notes

### Key Constraints
- **Six operations only, exact names**: `set_visibility(field_uid, bool)`,
  `set_required(field_uid, bool)`, `set_enabled(field_uid, bool)`,
  `set_value(field_uid, value)` (only for fields the schema marks
  computable), `set_hint(field_uid, text)`, `narrow_options(field_uid,
  subset)` (subset of ALREADY-declared options, never new ones).
- **Structurally refused, not merely undocumented**: the submit URL/
  `form.action`, CSRF token meta tag, `form_uid`/`form_id`/`tenant`,
  add/remove field or section, any change to a field's `name`/`uid`, raw
  HTML/DOM injection, navigation/cookies/storage access. The host-side
  applier must have literally no code path for any of these — not a
  runtime check that happens to reject them.
- Because the host-side enforcement is generated JavaScript (a string),
  this task's Python unit tests can only verify: (a) the generator
  produces the correct six operation names in the emitted JS, (b) the
  structurally-refused items are provably absent from the generated
  string (e.g. no `innerHTML`, no `document.cookie`), and (c) any
  Python-side helper that VALIDATES a patch dict (for the case a patch is
  ever inspected/logged server-side, e.g. for the discard-and-log
  requirement) behaves correctly. A real browser-level Worker
  round-trip test is out of scope for this task's `pytest` suite (no
  headless-browser tooling is part of this package's test stack).

### References in Codebase
- `renderers/html5.py:479-629` (corrected) — read the whole existing
  template before writing the additive block, to match its style (raw JS
  string, `__SENTINEL__` placeholders, no Python f-string brace
  conflicts).

---

## Implementation Blueprint

### Steps (in order)
1. Define the six-operation allowlist as a Python-side constant (used for
   the "any patch dict this Python code ever inspects" validation path,
   and to keep the generated JS's operation names in sync with one source
   of truth).
2. Implement `render_worker_boot_block(bundle_client_sources: list[str]) -> str`
   — generates the additive `<script>` block.
3. Implement `validate_patch(patch: dict) -> bool` — the Python-side
   discard-and-log check (used if/when a patch is ever logged or
   inspected server-side, per the six-operation contract).
4. Wire into `html5.py`'s `_LIFECYCLE_SCRIPT_TEMPLATE`.
5. Write and run tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/worker_bridge.py` (CREATE)
```python
"""Web Worker boot block + patch allowlist (FEAT-459 / M13, OQ-7).

Generates the additive JS block injected into html5.py's
_LIFECYCLE_SCRIPT_TEMPLATE. The Worker itself has NO DOM (G6) and
communicates via postMessage; the HOST page applies patches through a
fixed six-operation allowlist. The existing fetch-based remote bridge in
_LIFECYCLE_SCRIPT_TEMPLATE is untouched — this module is purely additive.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# The ONLY six patch operations a Worker may request the host apply
# (spec §2 "Client patch allowlist", OQ-7). Exact names/arities fixed.
ALLOWED_PATCH_OPERATIONS: frozenset[str] = frozenset(
    {"set_visibility", "set_required", "set_enabled", "set_value", "set_hint", "narrow_options"}
)


def validate_patch(patch: dict) -> bool:
    """True if `patch` names an allowlisted operation with a field_uid.

    This is the Python-side mirror of the host-page's JS allowlist check
    — used wherever a patch is inspected/logged server-side (e.g.
    security auditing), NOT the actual client-side enforcement (which
    runs as generated JS in the browser, see render_worker_boot_block()).
    """
    op = patch.get("op")
    if op not in ALLOWED_PATCH_OPERATIONS:
        logger.warning("worker patch discarded: unrecognised operation %r", op)
        return False
    if "field_uid" not in patch:
        logger.warning("worker patch discarded: missing field_uid for op %r", op)
        return False
    return True


def render_worker_boot_block() -> str:
    """Generate the additive Worker boot block for _LIFECYCLE_SCRIPT_TEMPLATE.

    Returns:
        A raw JS string (no Python f-string interpolation — matching the
        existing template's __SENTINEL__ convention) implementing:
        1. Worker instantiation from a Blob (so no separate static file
           is needed per form — the compiled snippet client_source(s)
           are embedded via the __SNIPPET_CLIENT_SOURCES__ sentinel).
        2. A postMessage listener applying ONLY the six allowlisted ops.
        3. No DOM access inside the Worker's own script body.

    The returned string uses the sentinel __SNIPPET_CLIENT_SOURCES__
    (a JSON array of compiled JS strings, one per bundle with a
    client_source) — html5.py's _inject_lifecycle() must .replace() it
    the same way it already replaces __FORM_ID__ etc.
    """
    allowed_ops_js = json.dumps(sorted(ALLOWED_PATCH_OPERATIONS))
    return (
        "\n<script>\n"
        "(function() {\n"
        "  var ALLOWED_PATCH_OPS = " + allowed_ops_js + ";\n"
        "  var SNIPPET_CLIENT_SOURCES = __SNIPPET_CLIENT_SOURCES__;\n"
        "  if (!SNIPPET_CLIENT_SOURCES.length) { return; }\n"
        "  var workerSrc = SNIPPET_CLIENT_SOURCES.join('\\n');\n"
        "  var blob = new Blob([workerSrc], {type: 'application/javascript'});\n"
        "  var worker = new Worker(URL.createObjectURL(blob));\n"
        "  worker.onmessage = function(evt) {\n"
        "    var patches = evt.data && evt.data.patches ? evt.data.patches : [];\n"
        "    patches.forEach(function(patch) {\n"
        "      if (ALLOWED_PATCH_OPS.indexOf(patch.op) === -1 || !patch.field_uid) {\n"
        "        console.warn('discarded disallowed worker patch', patch);\n"
        "        return;\n"
        "      }\n"
        "      applyFieldPatch(patch);\n"  # FILL IN below
        "    });\n"
        "  };\n"
        "  function applyFieldPatch(patch) {\n"
        "    var el = document.querySelector('[data-field-uid=\"' + patch.field_uid + '\"]');\n"
        "    if (!el) { return; }\n"
        "    switch (patch.op) {\n"
        "      // FILL IN: one case per ALLOWED_PATCH_OPERATIONS entry —\n"
        "      //   set_visibility toggles el.hidden; set_required/\n"
        "      //   set_enabled toggle attributes; set_value writes\n"
        "      //   el.value ONLY when the field's data-computable=\"true\"\n"
        "      //   attribute is present (bounded by 'only for fields the\n"
        "      //   schema marks computable'); set_hint writes to a\n"
        "      //   sibling hint element; narrow_options REMOVES <option>\n"
        "      //   elements not in patch.subset, never ADDS one (bounded\n"
        "      //   by 'subset of already-declared options').\n"
        "      default: console.warn('unhandled patch op', patch.op);\n"
        "    }\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )
```
**Why this shape**: `validate_patch()` (Python) and the generated JS's
`ALLOWED_PATCH_OPS` check are deliberately the SAME six-name list, sourced
from one Python constant (`ALLOWED_PATCH_OPERATIONS`) serialized into the
JS via `json.dumps` — this is what prevents the two enforcement points
from drifting apart if the allowlist ever changes. `applyFieldPatch`'s
per-operation `switch` cases are left as FILL IN because each one's exact
DOM manipulation depends on this renderer's existing field markup
conventions (`data-field-uid`, hint element structure) which should be
cross-checked against `html5.py`'s field-rendering Jinja templates before
writing real selectors — guessing them here risks silently breaking on
real markup.

### `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            self._LIFECYCLE_SCRIPT_TEMPLATE.replace("__FORM_ID__", json.dumps(form.form_id))' packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py)
# AFTER — insert as an additional .replace() chained onto the existing
# `script = (...)` assignment (verified: renderers/html5.py:629-630,
# CORRECTED from the spec's stale :573-574)
            .replace(
                "__SNIPPET_CLIENT_SOURCES__",
                json.dumps([b.client_source for b in _snippet_bundles_for(form) if b.client_source]),
            )
```
**Why**: chaining onto the EXISTING `.replace()` call chain (rather than
adding a second `script2 = ...` and concatenating) keeps the single
`script` variable as the one place downstream code appends to `html_str`
— minimizing the diff against the existing method. `_snippet_bundles_for(form)`
is a **new helper this task must also add** (a `# FILL IN` — see
checklist) since `html5.py` currently has no way to look up which
snippet bundles apply to a given `FormSchema`; it likely delegates to
whatever registry/resolver TASK-3163-3165 expose, but the exact call
shape depends on how server-side code wires those together at render
time (out of this task's file list, but required for this MODIFY block
to compile) — implementer must add a minimal version or leave a TODO
returning `[]` and note the gap explicitly in the Completion Note.

### `packages/parrot-formdesigner/tests/unit/test_worker_bridge.py` (CREATE)
```python
"""Unit tests for worker_bridge.py — FEAT-459 / TASK-3173."""

from __future__ import annotations

from parrot_formdesigner.renderers.worker_bridge import (
    ALLOWED_PATCH_OPERATIONS,
    render_worker_boot_block,
    validate_patch,
)


def test_worker_patch_allowlist_has_exactly_six_operations() -> None:
    assert ALLOWED_PATCH_OPERATIONS == {
        "set_visibility", "set_required", "set_enabled", "set_value", "set_hint", "narrow_options",
    }


def test_validate_patch_accepts_allowlisted_op() -> None:
    assert validate_patch({"op": "set_visibility", "field_uid": "f1", "value": False}) is True


def test_validate_patch_rejects_unknown_op() -> None:
    assert validate_patch({"op": "delete_field", "field_uid": "f1"}) is False


def test_validate_patch_rejects_missing_field_uid() -> None:
    assert validate_patch({"op": "set_visibility", "value": False}) is False


def test_patch_rejects_structure_change() -> None:
    """Operations that would add/remove a field are simply not in the allowlist."""
    for forbidden_op in ("add_field", "remove_field", "set_field_uid", "set_form_action"):
        assert validate_patch({"op": forbidden_op, "field_uid": "f1"}) is False


def test_boot_block_contains_all_six_op_names() -> None:
    block = render_worker_boot_block()
    for op in ALLOWED_PATCH_OPERATIONS:
        assert op in block


def test_boot_block_has_no_direct_innerHTML_or_cookie_access() -> None:
    """Structural check: no raw markup injection or cookie/storage path exists."""
    block = render_worker_boot_block()
    assert "innerHTML" not in block
    assert "document.cookie" not in block
    assert "localStorage" not in block
    assert "sessionStorage" not in block


def test_patch_narrow_options_subset_only() -> None:
    # FILL IN: this is fundamentally a browser-DOM behavior
    #   (narrow_options must remove, never add, <option> elements) — a
    #   pure-Python test can only assert the generated JS's comment/intent
    #   documents this constraint, OR (better) that the FILL IN switch
    #   case, once implemented, contains no code path that APPENDS an
    #   <option> element. Revisit once applyFieldPatch's cases are
    #   implemented; a real assertion needs either a JS test runner (not
    #   in this package's stack) or a code-search assertion
    #   (`"appendChild" not in block` or similar) — pick one and justify it.
    pass
```
**Why**: six of the eight tests are complete and are pure string/dict
assertions requiring no browser; the structural absence test
(`test_boot_block_has_no_direct_innerHTML_or_cookie_access`) is the
Python-testable proxy for G6/OQ-7's DOM-injection prohibitions. The
`narrow_options`-specific test is honestly stubbed because it is the one
genuinely hard-to-test-from-Python assertion in this task — the note
explains why rather than faking a passing assertion.

### FILL IN checklist
- [ ] `worker_bridge.py::render_worker_boot_block` — `applyFieldPatch`'s six `switch` cases; bounded by each operation's one-line spec description and by real field markup (cross-check `html5.py`'s field templates for `data-field-uid`/hint element conventions before guessing selectors)
- [ ] `html5.py` — add a `_snippet_bundles_for(form)` helper (or equivalent) so the MODIFY block compiles; flag as a cross-task coordination point if TASK-3163-3165's public API for "get bundles for this form" is not yet finalized
- [ ] `test_patch_narrow_options_subset_only` — decide the Python-testable proxy assertion

---

## Acceptance Criteria

- [ ] `ALLOWED_PATCH_OPERATIONS` contains exactly the six named operations, no more, no fewer
- [ ] `validate_patch()` rejects any operation not in the allowlist, and any patch missing `field_uid`
- [ ] The generated boot block contains no `innerHTML`, `document.cookie`, `localStorage`, or `sessionStorage` reference
- [ ] The existing `_LIFECYCLE_SCRIPT_TEMPLATE` fetch-based remote bridge body is byte-for-byte unchanged by this task's `html5.py` edit (only an additional `.replace()` is appended to the chain)
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_worker_bridge.py -v`
- [ ] `ruff check` and `mypy` clean on `renderers/worker_bridge.py`

---

## Test Specification

See the blueprint's test file above — 8 test functions, 1 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 "Client patch allowlist" resolved OQ-7, §3 Module 13)
2. **Check dependencies** — TASK-3161 must be `done`
3. **Verify the Codebase Contract** — **re-run** `grep -n "_LIFECYCLE_SCRIPT_TEMPLATE" renderers/html5.py` before editing; this task file already corrects the spec's stale line numbers (423/574 → 479/630) but the file may have moved again since 2026-09-11
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`, cross-checking real field markup in `html5.py` before writing DOM selectors
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3173-web-worker-runtime-patch-allowlist.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
