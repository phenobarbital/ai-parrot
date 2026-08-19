# F003 — FEAT-301 is un-actioned prior art that overlaps SPEC-B

**Citations:** `sdd/proposals/infographic-theme-catalog-a2ui.proposal.md` (FEAT-301,
  `status: review`); `sdd/state/FEAT-301/findings/F012-feat273-conflict.md`
**Confidence:** high

FEAT-301 — *"Themed Component Catalog — HTML Renderer v2 + A2UI Output"* — sits at
`status: review` and **has no task index**, i.e. it was never decomposed or implemented.
It declares `related: FEAT-094 (infographic-html-output)`, `FEAT-273 (a2ui-implementation)`.

Its own research recorded a direct conflict with FEAT-273 (F012):

> This spec (FEAT-301 draft) targets A2UI v0.9.1 and creates a standalone A2UIRenderer in
> `parrot/outputs/formats/a2ui.py`. This conflicts with: 1. Version v0.9.1 vs v1.0;
> 2. standalone renderer vs centralized catalog+registry; 3. fresh envelope models vs
> FEAT-273's shared models; 4. standalone `parrot-catalog.json` vs `@register_component`.
> **WS-C must be reconciled with FEAT-273 or risk creating parallel A2UI infrastructure.**

FEAT-273 subsequently shipped (F001), so the conflict is resolved by fact: the centralized
`parrot.outputs.a2ui` catalog+registry won. **SPEC-B must explicitly supersede or close
FEAT-301**, otherwise the same "parallel A2UI infrastructure" risk it warned about is
re-created by a third effort. Its theming content may still be worth absorbing.
