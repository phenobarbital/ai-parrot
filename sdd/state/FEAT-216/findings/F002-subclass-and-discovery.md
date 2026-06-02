# F002 — Subclass extension is the supported pattern

**Confidence:** high

`AbstractToolkit.get_tools()`
(`packages/ai-parrot/src/parrot/tools/toolkit.py:337`) discovers tools by
**runtime reflection**: it iterates instance attributes via `inspect`, keeps
`inspect.iscoroutinefunction(attr)` methods (toolkit.py:413), and applies
`tool_prefix` with an idempotent rule (toolkit.py:383-385). It also reads
`@tool_schema`/`@requires_permission` annotations.

Implication: a subclass `OdooFieldServiceToolkit(OdooToolkit)` automatically
**inherits all ~30 parent CRUD tools AND auto-registers its own new `async def`
methods** as tools — no manual registration. New methods get the inherited
`tool_prefix` unless the subclass overrides it.

**Precedent confirmed:** the DatabaseToolkit family already does domain
subclassing — `class SqlToolkit(DatabaseToolkit)` and siblings at
`packages/ai-parrot/src/parrot/bots/database/toolkits/{sql,elastic,influx,documentdb}.py`.
So a domain-specialised Odoo toolkit follows an established repo pattern.

Open design choice: subclass (inherit all generic CRUD tools too) vs. compose
(wrap an OdooToolkit instance and expose ONLY the 8 FSM tools). Subclassing is
less code; composition gives a tighter, safer tool surface for a field rep.

**Citations:** `packages/ai-parrot/src/parrot/tools/toolkit.py` (337,383-385,413,422);
`packages/ai-parrot/src/parrot/bots/database/toolkits/sql.py`
