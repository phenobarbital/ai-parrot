# TASK-4689: FormDesigner toolkit (M6)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4682
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6**: two LLM-callable tools so a model can reach forms without
a slash command. **Metadata only** — the tools never render or send a card.
`formdesigner_get_form` resolves one form, calls an injected `enqueue_card(uid)`
callback, and returns metadata with `card_pending: true`; the mixin (TASK-4691)
sends the card after the turn. Tenant and bearer come from injected resolvers,
never from tool arguments, so the LLM can neither choose a tenant nor see a token.

Depends on TASK-4682 (`FormReader`, `FormDescriptor`, `FormDesignerError`,
`parse_form_ref`). Wave 2.

---

## Scope

- Create `tools/formdesigner.py` with `FormDesignerToolkit(AbstractToolkit)` and
  exactly two public async methods: `formdesigner_list_forms()` and
  `formdesigner_get_form(form: str)`.
- No usable context (tenant or bearer resolver returns `None`) → return
  `{"status": "unavailable", "reason": "login_required" | "tenant_unresolved"}`
  with ZERO reader calls and no enqueue.
- Reader errors → `{"status": "error", "reason": <short fixed string>}`; never raise into the agent loop; never echo the bearer.
- `formdesigner_get_form`: slug → `get_form_by_slug` (None → `{"status": "not_found"}`),
  then `get_form` for section/field counts; enqueue BEFORE returning.
- Write `tests/msteams/test_formdesigner_toolkit.py`.

**NOT in scope**: editing `tools/__init__.py` (the mixin imports the module
directly); the local reader (TASK-4690); sending cards.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/tools/formdesigner.py` | CREATE | FormDesignerToolkit (2 tools, metadata only) |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_toolkit.py` | CREATE | M6 unit tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit          # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:225
from ..formdesigner_client import (                       # created by TASK-4682
    FormDescriptor, FormDesignerError, FormReader, parse_form_ref,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ServerManagedToolkit, ABC):          # line 225 — every PUBLIC async method becomes a tool
    exclude_tools: tuple[str, ...] = ()                     # line 262
    tool_prefix: str | None = None                          # line 276 — leave None: tool names must stay formdesigner_*
    def __init__(self, **kwargs): ...                       # line 357 — reads config kwargs only; call it FIRST, then set attrs
    def get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]: ...  # line 522

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/tools/__init__.py — exports RequestFormTool only; do not edit

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema: sections: list[FormSection]  # line 487 ; FormSection.fields: list[SectionItem]  # line 279
#   SectionItem is a field OR a subsection (subsections have their own .fields) — count leaf fields
```

### Does NOT Exist
- ~~`FormDesignerToolkit`~~, ~~`formdesigner_list_forms`~~, ~~`formdesigner_get_form`~~ — created here.
- ~~`parrot_tools.formdesigner`~~ — the toolkit deliberately lives in ai-parrot-integrations.
- ~~tenant / bearer tool parameters~~ — forbidden; the LLM must not supply them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/tools/formdesigner.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_toolkit.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.get_tools"
  ]
}
```

---

## Implementation Notes

- **Docstrings are the LLM contract** (spec M6) — keep the two tool docstrings as written in the blueprint.
- Private helpers must start with `_` so `_generate_tools()` does not expose them.
- Field counting: a `SectionItem` with a `fields` attribute is a subsection — FILL IN: count its leaf fields recursively.

---

## Implementation Blueprint

### Steps (in order)
1. Constructor stores reader + resolvers + callback after `super().__init__(**kwargs)` — *why*: base init only reads config kwargs.
2. A private `_context()` returning `(tenant, bearer)` or an unavailable dict — *why*: both tools fail closed the same way.
3. The two tools.
4. Tests with a fake `FormReader`.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/tools/formdesigner.py` (CREATE)
```python
"""FormDesigner toolkit (FEAT-734 M6): list and resolve forms; the channel sends the card."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from parrot.tools.toolkit import AbstractToolkit

from ..formdesigner_client import FormDesignerError, FormReader, parse_form_ref


class FormDesignerToolkit(AbstractToolkit):
    """Lists and resolves FormDesigner forms for the current tenant."""

    def __init__(
        self,
        client: FormReader,
        *,
        tenant_resolver: Callable[[], str | None],
        bearer_resolver: Callable[[], str | None],
        enqueue_card: Callable[[uuid.UUID], bool | None],
        **kwargs: Any,
    ) -> None:
        """Resolvers and enqueue read M4's request-local turn context; no context -> fail closed."""
        super().__init__(**kwargs)
        self._reader = client
        self._tenant_resolver = tenant_resolver
        self._bearer_resolver = bearer_resolver
        self._enqueue_card = enqueue_card
        self._fd_logger = logging.getLogger(__name__)

    def _context(self) -> tuple[str, str] | dict[str, Any]:
        bearer = self._bearer_resolver()
        if not bearer:
            return {"status": "unavailable", "reason": "login_required"}
        tenant = self._tenant_resolver()
        if not tenant:
            return {"status": "unavailable", "reason": "tenant_unresolved"}
        return tenant, bearer

    async def formdesigner_list_forms(self) -> dict[str, Any]:
        """List the forms available in the caller's tenant.

        Returns {"tenant": str, "forms": [{"form_uid", "form_id", "title",
        "description"}]}. Use it to find a form before asking for it by slug.
        """
        ctx = self._context()
        if isinstance(ctx, dict):
            return ctx
        tenant, bearer = ctx
        # FILL IN: await self._reader.list_forms(tenant=tenant, bearer_token=bearer); FormDesignerError ->
        #   {"status": "error", "reason": "forms_unavailable"}; map rows to the 4 documented keys (form_uid as str)
        raise NotImplementedError

    async def formdesigner_get_form(self, form: str) -> dict[str, Any]:
        """Resolve ONE form by slug or form_uid and queue its card for sending.

        `form` is a slug (e.g. "store-visit") or a form_uid. Returns
        {"form_uid", "form_id", "title", "sections", "field_count",
        "card_pending": true}; the Adaptive Card is sent by the channel, so do
        not describe the form's fields back to the user.
        """
        ctx = self._context()
        if isinstance(ctx, dict):
            return ctx
        tenant, bearer = ctx
        ref = parse_form_ref(form)
        # FILL IN: slug -> get_form_by_slug (None -> {"status": "not_found", "form": form}) -> uid;
        #   get_form(uid) for counts; enqueue = self._enqueue_card(uid); a False return (closed turn) ->
        #   {"status": "unavailable", "reason": "turn_closed"} and card_pending must NOT be true;
        #   FormDesignerError(404) -> not_found; other FormDesignerError -> {"status": "error", "reason": "form_unavailable"}.
        #   The return dict must contain NO Adaptive Card JSON.
        raise NotImplementedError
```
**Why this shape**: the constructor signature is spec §3 M6's skeleton (`enqueue_card` returns the turn's `enqueue()` bool so a closed turn is visible). Do not add tenant/bearer parameters to either tool.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_toolkit.py` (CREATE)
```python
"""FEAT-734 M6 — FormDesignerToolkit with a fake reader."""
import uuid

import pytest

from parrot.integrations.msteams.formdesigner_client import FormDescriptor
from parrot.integrations.msteams.tools.formdesigner import FormDesignerToolkit


class FakeReader:
    def __init__(self):
        self.calls: list[tuple] = []
    # FILL IN: list_forms / get_form / get_form_by_slug recording (method, tenant, bearer)


def _toolkit(reader, *, tenant="acme", bearer="nav-tok", queue=None):
    queue = [] if queue is None else queue
    return FormDesignerToolkit(reader, tenant_resolver=lambda: tenant, bearer_resolver=lambda: bearer,
                               enqueue_card=lambda uid: queue.append(uid) or True), queue


async def test_toolkit_get_form_returns_metadata_not_card(): ...   # FILL IN: card_pending True, no "body"/"AdaptiveCard" anywhere
async def test_toolkit_list_forms_scoped_to_tenant(): ...          # FILL IN: reader saw tenant "acme"
async def test_toolkit_without_context_fails_closed(): ...         # FILL IN: bearer None -> unavailable, reader.calls == []
async def test_toolkit_closed_turn_not_pending(): ...              # FILL IN: enqueue returns False -> no card_pending
async def test_toolkit_slug_not_found(): ...                       # FILL IN
def test_toolkit_exposes_exactly_two_tools(): ...                  # FILL IN: names from get_tools() == {formdesigner_list_forms, formdesigner_get_form}
```

### FILL IN checklist
- [ ] `formdesigner_list_forms` body
- [ ] `formdesigner_get_form` body + leaf field counting
- [ ] `FakeReader` and six test bodies (`get_tools()` may need `await` — check whether it is sync at toolkit.py:522; it is declared `def`, so sync)

---

## Acceptance Criteria

- [ ] Exactly two tools exposed, named `formdesigner_list_forms` / `formdesigner_get_form`.
- [ ] No context → structured unavailable result, zero reader calls.
- [ ] `formdesigner_get_form` returns metadata with `card_pending: true`, never card JSON; enqueue happens before return.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_toolkit.py -q`


---

## Test Specification

Six tests in the blueprint (first two are spec §4 M6 rows).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4689 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
