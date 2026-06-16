---
name: install-odoo-module
description: How to install a new Odoo module on the running instance. Use this skill when the user asks to install, enable, or activate an Odoo add-on or module. Covers both shell-based installation via odoo-bin and UI-based installation via the Apps menu.
trigger: /install-odoo-module
license: Proprietary. See repository LICENSE
compatibility: Odoo 16 (XML-RPC), Odoo 18 and 19 (JSON-RPC / REST / JSON-2). Shell tools require ODOO_BIN to be set.
metadata:
  author: OdooAgent (FEAT-240)
  version: "1.0"
---

# Install an Odoo Module

Use this skill when asked to install a new Odoo module (add-on). Follow these
steps in order; confirm write operations with the user before executing.

---

## Prerequisites

Before installing, verify the following:

1. **Module source is present** — the module's source directory must exist on
   the Odoo server's add-ons path (`addons_path` in the Odoo config file, or the
   `--addons-path` argument).
2. **Database is backed up** — installing modules modifies the database schema.
   Always recommend a backup before proceeding in production.
3. **Odoo version compatibility** — check that the module declares the correct
   `version` in its `__manifest__.py` for the running Odoo version (16/18/19).
4. **Dependencies** — review `depends` in the module's `__manifest__.py` and
   confirm all listed dependencies are already installed.

---

## Installation Methods

### Method A: Shell (preferred for server-side installs)

Use the `odoo_shell_install_module` tool, which calls `odoo-bin -i`:

```
Tool: odoo_shell_install_module
  modules: ["<technical_module_name>"]
  database: "<target_database>"   # defaults to ODOO_TEST_DATABASE
  upgrade: false
```

This executes:
```bash
odoo-bin -d <database> -i <module_name> --stop-after-init
```

> **HITL NOTE**: This tool is gated by HITL confirmation — always present the
> command to the user and wait for approval before executing.

**Version differences:**
- **Odoo 16**: Uses XML-RPC; `odoo-bin -i` is the standard install path.
- **Odoo 18/19**: Uses JSON-RPC / REST; `odoo-bin -i` still works for
  server-side installs.

---

### Method B: Odoo Apps UI (for non-technical users)

1. Log in as an administrator.
2. Go to **Apps** menu (or **Settings → Apps**).
3. Search for the module by name.
4. Click **Install**.

> **Note**: The module must appear in the Apps catalogue.  Custom/local modules
> not published to the Odoo App Store may not appear here unless the database
> catalogue has been refreshed (`Settings → Technical → Update Apps List`).

---

### Method C: RPC (programmatic, Odoo 16 XML-RPC)

For Odoo 16, you can install a module via XML-RPC by writing to `ir.module.module`:

```python
# Step 1: Find the module
modules = client.execute_kw('ir.module.module', 'search_read',
    [[['name', '=', '<technical_name>'], ['state', '=', 'uninstalled']]],
    {'fields': ['id', 'name', 'state']})

# Step 2: Trigger install
client.execute_kw('ir.module.module', 'button_immediate_install',
    [[modules[0]['id']]])
```

> **HITL NOTE**: Any write/delete RPC call is gated by HITL confirmation.

---

## Post-Installation Steps

1. **Restart Odoo** — some modules require a server restart to activate all
   components (workers, cron jobs, assets).  Inform the user.
2. **Verify installation** — use the `odoo_get_odoo_profile` tool to check
   that the module appears in `installed_modules`.
3. **Update Apps List** — if the module is newly added to the file system and
   does not appear in the UI, go to **Settings → Technical → Update Apps List**.
4. **Check logs** — review the Odoo server log for errors during startup.

---

## Upgrade (vs Install)

To **upgrade** an already-installed module (apply code/manifest changes):

```
Tool: odoo_shell_upgrade_module
  modules: ["<technical_module_name>"]
  database: "<target_database>"
```

This calls `odoo-bin -d <db> -u <module> --stop-after-init`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Module not in Apps list | Not on addons_path | Add path to config; refresh Apps List |
| Install fails with dependency error | Missing parent module | Install dependencies first |
| Server won't start after install | Module code error | Check server log; rollback if needed |
| Module state shows "to install" but never completes | Cron not running | Restart Odoo with a worker |

---

## Example: Install the `sale` module on Odoo 18

```
I will install the 'sale' module on the odoo database using odoo-bin.
This is a write operation and requires your confirmation.

Proposed command:
  odoo_shell_install_module(modules=["sale"], database="odoo")
  → odoo-bin -d odoo -i sale --stop-after-init

Please confirm to proceed.
```
