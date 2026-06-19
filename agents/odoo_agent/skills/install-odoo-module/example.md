# Example: Installing the `stock` module

This example shows the full interaction flow for installing a module via Oddie.

---

## User request

> "Can you install the inventory / stock module on our Odoo 18 test instance?"

---

## Agent response (following the skill)

### Step 1 — Verify prerequisites

I'll first check the current status of the `stock` module on the database.

```
Tool: odoo_search_records
  model: ir.module.module
  domain: [["name", "=", "stock"]]
  fields: ["name", "state", "depends"]
```

Result: `{"name": "stock", "state": "uninstalled", "depends": ["base", "product"]}`

Good — the module exists and is not yet installed. Its dependencies (`base`,
`product`) are already installed.

---

### Step 2 — Confirm with user (HITL)

> I found the `stock` (Inventory) module.  To install it I will run:
>
> ```
> odoo-bin -d odoo -i stock --stop-after-init
> ```
>
> This will modify the database schema.  Do you want to proceed?

---

### Step 3 — Execute after confirmation

```
Tool: odoo_shell_install_module
  modules: ["stock"]
  database: "odoo"
  upgrade: false
```

---

### Step 4 — Verify

```
Tool: odoo_get_odoo_profile
  include_modules: true
```

Confirm that `stock` appears in `installed_modules`.

---

### Step 5 — Report

> The `stock` (Inventory) module has been installed successfully on database
> `odoo` (Odoo 18).  You may need to restart the Odoo server to activate all
> scheduled actions and worker processes.
