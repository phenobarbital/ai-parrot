# F004 — Pydantic model layer & the fieldservice model gap

**Confidence:** high

The toolkit splits its models cleanly into three modules under
`packages/ai-parrot-tools/src/parrot_tools/odoo/models/`:
- `entities.py` — typed Odoo records (`_OdooEntity` base; `ResPartner`,
  `SaleOrder`, `StockPicking` at entities.py:227, `HrEmployee`, ...).
- `inputs.py` — `_OdooBaseInput` subclasses bound via `@tool_schema`
  (e.g. `FindPartnerInput` inputs.py:111 with `Field(default=..., ge=, le=)`).
- `envelopes.py` — result wrappers (`SearchResult`, `CreateResult`,
  `ServerInfoResult`, ...).

`_DEFAULT_KNOWN_MODELS` (toolkit.py:136-148) registers known models:
`res.partner, res.users, product.template/product, sale.order(.line),
account.move(.line), crm.lead, stock.picking`.

**Gap:** the OCA fieldservice models are NOT present —
`fsm.order` and `fsm.location` have no entity classes and are not in
`_DEFAULT_KNOWN_MODELS`. The feature must add:
- `FsmOrder` / `FsmLocation` (and likely `FsmStage`) entities,
- their input schemas (`GetTodayFsosInput`, `GetKioskInput`,
  `CreateReturnDraftInput`, `ValidateLoadingPickInput`, ...),
- result envelopes (loading/return summary lines), and
- registration entries so `list_models`/permission checks see them.

Return pickings (`create_return_draft`, `validate_returns`) ride on the existing
`stock.picking` plumbing — `StockPicking` entity (entities.py:227) and the
`stock.picking` model are already known; `button_validate` is callable through
`_execute("stock.picking", "button_validate", [[ids]])`. Photo attachment reuses
`attach_document` (toolkit.py:906).

**Domain unknowns (codebase cannot answer):**
- The field on `fsm.order` that encodes "Navigator sequence" ordering.
- The `fsm.location` field holding the "planogram ref".
- Mapping `rep_id` → `fsm.order` rep (likely `person_id`/`user_id`) and →
  outbound pickings for the day.

**Citations:** `packages/ai-parrot-tools/src/parrot_tools/odoo/models/entities.py` (22,34,129,227,245);
`.../models/inputs.py:111`; `.../models/envelopes.py`;
`.../odoo/toolkit.py` (136-148,906)
