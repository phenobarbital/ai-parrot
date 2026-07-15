---
type: Wiki Overview
title: OdooToolkit Capabilities
id: doc:docs-odoo-toolkit-capabilities-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: The `OdooToolkit` exposes Odoo ERP operations as agent tools. It composes
  an Odoo transport (JSON-2, JSONRPC, or XML-RPC depending on the detected version)
  and turns each of its public async methods into a tool.
---

# OdooToolkit Capabilities

The `OdooToolkit` exposes Odoo ERP operations as agent tools. It composes an Odoo transport (JSON-2, JSONRPC, or XML-RPC depending on the detected version) and turns each of its public async methods into a tool.

Below is the complete list of capabilities (tools) provided by the `OdooToolkit`, grouped by their domain:

## Discovery
1. **`server_info`**
   - **Description:** Returns Odoo server version, transport protocol used, and connection status.
2. **`list_models`**
   - **Description:** Lists the explicit Odoo models the toolkit knows about and returns their read/write/create/unlink permissions based on the user's ACLs.
3. **`fields_get`**
   - **Description:** Returns the field definitions and metadata for any Odoo model.

## Generic CRUD Operations
4. **`search_records`**
   - **Description:** Searches for records in any Odoo model using domain filters, sorting/ordering, and pagination.
5. **`get_record`**
   - **Description:** Reads a single record from any defined model by its numeric ID.
6. **`create_record`**
   - **Description:** Creates one record in a specified model and returns the new ID plus a summary of the record. *(Requires `odoo.write` permission)*
7. **`create_records`**
   - **Description:** Creates multiple records in a single round-trip for bulk operations (max 1000). *(Requires `odoo.write` permission)*
8. **`update_record`**
   - **Description:** Updates a single record by its ID with new field values. *(Requires `odoo.write` permission)*
9. **`update_records`**
   - **Description:** Applies the same patch/update to many records in one bulk call (max 1000). *(Requires `odoo.write` permission)*
10. **`delete_record`**
    - **Description:** Deletes a single record by its ID. *(Requires `odoo.delete` permission)*
11. **`delete_records`**
    - **Description:** Deletes multiple records simultaneously in one bulk call (max 1000). *(Requires `odoo.delete` permission)*
12. **`import_records`**
    - **Description:** Performs an idempotent upsert via Odoo's `load` mechanism. Mirrors Odoo's CSV import semantics where rows with an existing external ID are updated, and new rows are created. *(Requires `odoo.write` permission)*

## Contact / Partner Helpers (`res.partner`)
13. **`find_partner`**
    - **Description:** Searches for `res.partner` records using friendly arguments (name, email, phone, vat, is_company) and returns strongly-typed results.
14. **`create_partner`**
    - **Description:** Creates a `res.partner` (either an individual or a company) with specific arguments and returns it as a typed model. *(Requires `odoo.write` permission)*
15. **`update_partner_contact_info`**
    - **Description:** Updates contact and address fields (email, phone, address, website) on an existing partner. *(Requires `odoo.write` permission)*

## Sales Helpers (`sale.order`)
16. **`create_quotation`**
    - **Description:** Creates a draft `sale.order` (quotation) with one or more order lines for a specific partner. *(Requires `odoo.write` permission)*
17. **`confirm_sale_order`**
    - **Description:** Confirms a draft quotation, transitioning it to the 'sale' state. *(Requires `odoo.write` permission)*

## Invoicing Helpers (`account.move`)
18. **`create_invoice`**
    - **Description:** Creates a draft invoice or vendor bill on `account.move` containing multiple invoice lines. *(Requires `odoo.write` permission)*
19. **`post_invoice`**
    - **Description:** Posts a draft invoice using the `action_post` procedure in Odoo. *(Requires `odoo.write` permission)*
20. **`register_payment`**
    - **Description:** Registers a payment on a posted invoice via `account.payment.register`. Returning the created `account.payment` records. *(Requires `odoo.write` permission)*

## Binary / Document Helpers
21. **`set_binary_field`**
    - **Description:** Uploads raw bytes (from a URL or a base64 string) into a specific Binary or Image field on an existing record. *(Requires `odoo.write` permission)*
22. **`attach_document`**
    - **Description:** Creates an `ir.attachment` linked to a specific record in Odoo, handling URL fetching and base64 parsing directly. *(Requires `odoo.write` permission)*
