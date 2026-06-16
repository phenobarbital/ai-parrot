---
name: structured-operation-response
description: How to answer "how do I do X in Odoo?" questions. Use this skill whenever the user asks a how-to or operational question about Odoo (e.g. "how do I create an invoice?", "how do I install a module?"). Responds with an ordered list of concrete, version-aware steps grounded in the PageIndex documentation.
trigger: /structured-operation-response
license: Proprietary. See repository LICENSE
compatibility: All Odoo versions (16 XML-RPC, 18/19 JSON-RPC / REST). Version differences are called out inline.
metadata:
  author: OdooAgent (FEAT-240)
  version: "1.0"
---

# Structured Operation Response

Use this skill whenever the user asks an operational how-to question about Odoo,
such as:
- "How do I create a customer invoice in Odoo?"
- "How do I install a module?"
- "What is the process to confirm a sale order?"
- "How do I import partner records?"

---

## Response Contract

Always respond with an **ordered (numbered) list of concrete steps**.

### Required structure

```
## How to [do X] in Odoo [version if known]

> Grounded in: Odoo [version] documentation (PageIndex)

1. **[Step title]** — [Concrete action description].
   - Version note (if applicable): In Odoo 16 (XML-RPC) use X; in Odoo 18/19 (REST) use Y.
   - HITL note (if write): This step requires confirmation before execution.

2. **[Step title]** — ...

3. **[Step title]** — ...

> Note: Steps N–M involve write operations and will require your confirmation.
```

---

## Rules

### 1. Ground every answer in the PageIndex

Before composing a response, search the PageIndex for the relevant operation:

```
Tool: pageindex_search
  tree_name: odoo_16   # or odoo_18 / odoo_19 depending on context
  query: "<operation description>"
```

If you are unsure which version the user is on, search all three trees
(`odoo_16`, `odoo_18`, `odoo_19`) and synthesise the results.

**Do not** answer from parametric memory alone. Always retrieve nodes from
the PageIndex first and cite them.

### 2. Be version-aware

Odoo 16 uses **XML-RPC** (endpoint: `/xmlrpc/2/`).
Odoo 18 and 19 use **JSON-RPC** and **REST** (endpoints vary).
Odoo 19 also adds the **JSON-2** envelope protocol.

Always call out differences when they affect the steps:
- Method signatures differ between XML-RPC and JSON-RPC.
- REST endpoints are only available from Odoo 18+.
- Some modules exist only in certain versions.

### 3. Use ordered/numbered steps

- Steps MUST be numbered (1, 2, 3 …).
- Each step must be concrete: name the tool, endpoint, UI path, or menu.
- Never use vague guidance like "configure as needed".
- Sub-steps (within a step) may use bullet points.

### 4. Flag write operations clearly

Any step that creates, updates, or deletes data must include a note:

> **Write operation** — this step will be gated by HITL confirmation.

This ensures the user is aware before the agent executes.

### 5. Admit gaps honestly

If the PageIndex does not contain sufficient information for a step, say so:

> I did not find documentation for this step in the PageIndex for Odoo [version].
> I will note this gap for learning (see below).

Then use `pageindex_insert_content` to record the gap as a learning in the
documentation tree.

### 6. Document new learnings

If you discover a step or detail not covered in the documentation:
1. Answer the user fully.
2. Call `pageindex_insert_content` to persist the learning in the relevant
   version tree (`odoo_16`, `odoo_18`, or `odoo_19`).
3. Optionally call `document_skill` to save the full procedure as a new skill.

---

## Example

**User**: How do I create and post a customer invoice in Odoo 18?

**Response** (following this skill):

## How to Create and Post a Customer Invoice in Odoo 18

> Grounded in: Odoo 18 documentation (PageIndex — tree: `odoo_18`)

1. **Navigate to the Invoicing module** — Go to **Accounting → Customers → Invoices**.

2. **Create a new invoice** — Click **New**.
   - Fill in: Customer, Invoice Date, Due Date.
   - Add one or more invoice lines (product, quantity, price, tax).
   - **Write operation** — Creating the invoice record will require your confirmation.
   ```
   Tool: odoo_create_invoice (HITL gated)
     partner_id: <customer_id>
     invoice_lines: [...]
   ```

3. **Review the draft** — Verify all lines and amounts before posting.

4. **Post (confirm) the invoice** — Click **Confirm** (or use the `Post` button).
   - This sets the invoice state from `draft` → `posted` and assigns a sequence number.
   - **Write operation** — Requires your confirmation.
   ```
   Tool: odoo_post_invoice (HITL gated)
     invoice_id: <id>
   ```

5. **Register payment (optional)** — Click **Register Payment** to link a
   payment to the invoice.
   - **Write operation** — Requires your confirmation.

> **Version note**: In Odoo 16 (XML-RPC) the same steps apply via XML-RPC
> calls to `account.move`; in Odoo 18/19 you may alternatively use the REST
> endpoint `POST /api/account.move` (Odoo 19+).
