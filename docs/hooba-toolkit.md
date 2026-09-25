# HoobaToolkit

Drafts-only automation of Hooba (app.hooba.com) for AI-Parrot agents (FEAT-602).

## What it does / what it never does

**What it does:**
- Creates sales invoice drafts (`hooba_create_invoice_draft`)
- Creates purchase-invoice drafts from BBVA bank statements (`hooba_import_bbva_statement`)
- Finds existing Hooba contacts (`hooba_find_contact`)
- Lists and downloads invoice drafts (`hooba_list_drafts`, `hooba_download_invoice_pdf`)
- Recovers web sessions and runs catalogued web actions (`hooba_recover_web_session`, `hooba_run_web_action`)
- Attaches documents to drafts (`hooba_attach_document`)

**What it never does:**
- Issues invoices (`:issue`), confirms purchase invoices (`:confirm`), cancels or deletes drafts
- Sends e-mails, remittances, payments, or any SUBMIT-kind operation
- Creates new Hooba contacts, tax codes, accounting accounts, or document types
- Performs any write outside the DRAFT_OPERATIONS set

## Configuration

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `HOOBA_BASE_URL` | No | `https://api.hooba.com` | Hooba API base URL |
| `HOOBA_ACCOUNT_ID` | Yes | — | Account ID used in all API calls (e.g. `23549`) |
| `HOOBA_MEMBER_ID` | No | — | Member ID for multi-tenant accounts |
| `HOOBA_USER_ID` | No | — | User ID for credential resolution |
| `HOOBA_SUBSCRIPTION_ID` | No | — | Subscription ID for credential resolution |
| `HOOBA_LANGUAGE` | No | `es` | Language header (`x-hooba-language`) |
| `HOOBA_ORIGIN` | No | `https://app.hooba.com` | Origin header for cookie mode |
| `HOOBA_CATALOG_DIR` | No | — | Private Playwright catalog directory (fallback only) |
| `HOOBA_SPEC_PATH` | No | — | Override the pinned spec file path |
| `HOOBA_INCLUDE_TAGS` | No | — | Comma-separated list of tags to include (default: read-only operations) |
| `HOOBA_CREDENTIAL_PROVIDER` | No | `hooba` | Credential broker provider name |
| `HOOBA_CREDENTIAL_USER_ID` | No | `hooba` | Credential broker user ID |

Credentials are resolved through `CredentialBroker` with provider `hooba` and user ID `hooba` (or `HOOBA_CREDENTIAL_USER_ID`). The broker looks up `HOOBA_USERNAME` and `HOOBA_PASSWORD` from environment variables.

## Tools

### Composite tools (11)

| Tool | OperationKind | Description |
|------|---------------|-------------|
| `hooba_whoami` | READ | Returns current user information |
| `hooba_find_contact` | READ | Finds existing Hooba contacts by name/ID, returns up to `limit` matches |
| `hooba_list_drafts` | READ | Lists existing drafts of a given kind (invoice/purchase_invoice), up to `limit` |
| `hooba_download_invoice_pdf` | READ | Downloads an invoice PDF to a destination directory |
| `hooba_recover_web_session` | READ | Recovers a web session via the private Playwright catalog and returns the `sid` cookie |
| `hooba_run_web_action` | READ | Runs a catalogued web action (login, navigation) via the private Playwright catalog |
| `hooba_create_invoice_draft` | DRAFT | Creates a new sales invoice draft from an `InvoiceDraft` model |
| `hooba_create_purchase_invoice_draft` | DRAFT | Creates a new purchase-invoice draft from a `PurchaseInvoiceDraft` model |
| `hooba_attach_document` | DRAFT | Attaches a file to an existing draft (invoice or purchase_invoice) |
| `hooba_import_bbva_statement` | DRAFT | Imports a BBVA bank statement and creates purchase-invoice drafts (dry-run by default) |

### Generated API tools (58)

The toolkit generates 58 API tools from the pinned Hooba spec (47 READ + 11 DRAFT). These are:
- GET operations for reading data (contacts, taxes, accounts, invoices, etc.)
- POST operations for creating drafts (limited to the 11 DRAFT_OPERATIONS)
- All generated tools are typed with `OperationKind` metadata for routing

## The pinned API document

The toolkit uses a **pinned, pruned** copy of the Hooba OpenAPI spec:
- **Version**: `2026.6.17`
- **SHA**: `ad42d9aff` (verified against `dev` at commit `ad42d9aff`)
- **File**: `packages/ai-parrot-tools/src/parrot_tools/hooba/spec/hooba-api-2026.6.17.pruned.json`
- **Size**: 4,536 operations (656 paths) before pruning

To regenerate the pinned spec:
```bash
# In the main checkout (not a worktree)
python -m parrot_tools.hooba.spec.prune \
  --source https://api.hooba.com/api/doc.json \
  --out packages/ai-parrot-tools/src/parrot_tools/hooba/spec/hooba-api-2026.6.17.pruned.json
uv lock
```

The pruner removes:
- All SUBMIT-kind operations (`:issue`, `:confirm`, `:cancel`, `:send*`, DELETE, bulk operations)
- Operations not tagged for read access
- Operations that would exceed the default tool budget (58 tools)

## Browser fallback (private catalog)

The toolkit ships a **private Playwright catalog** for session recovery and navigation-only actions:
- **Location**: `HOOBA_CATALOG_DIR` (outside the repo, e.g. `/opt/hooba-catalog/`)
- **Contents**: Login action, navigation actions, and any catalogued web operations
- **Access**: Only for `hooba_recover_web_session` and `hooba_run_web_action`

To seed the catalog:
```bash
# Run the seed helper in the catalog directory
python -m parrot_tools.hooba.web.seed_catalog --catalog-dir /opt/hooba-catalog
```

**Session recovery flow:**
1. Agent calls `hooba_recover_web_session()`
2. HoobaWebAdapter runs the `hooba-login` action in the catalog
3. Browser cookies (including `sid`) are exported via `exec_get_cookies`
4. The `sid` cookie is injected into the API toolkit's cookie jar
5. Subsequent API calls use the recovered session

**Important**: The catalog is private and contains real selectors. It is **not** committed to the repo.

## Importing a BBVA statement

The BBVA importer turns a bank export into purchase-invoice drafts under Spanish autónomo rules:

### Dry-run → review → apply

1. **Dry run** (default):
   - `hooba_import_bbva_statement(path, period, dry_run=True)`
   - Parses the Excel file, extracts debit rows
   - Applies the rule table (deductibility, tax codes, legal basis)
   - Returns an `ExpenseDraftBatch` with `planned` drafts and `skipped` rows
   - **No API calls are made**

2. **Review**:
   - Inspect the `ExpenseDraftBatch` output
   - Verify `review_required` rows (gestoría sign-off needed)
   - Check `legal_basis` and `tax_code` for each row
   - Optionally adjust the rule table or contact matching

3. **Apply**:
   - Call `hooba_import_bbva_statement(path, period, dry_run=False)`
   - Creates purchase-invoice drafts idempotently by `row_id`
   - Returns the list of created `DraftReceipt` objects
   - Manifest is written to `checkpoint_dir_for(path)` for resumption

### Manifest and resumption

- **Manifest location**: `<checkpoint_dir_for(path)>/hooba_bbva_<digest>.json`
- **Permissions**: 0o600 (file), 0o700 (directory)
- **Resumption**: If the import fails, re-running with the same `path` and `period` skips already-completed rows
- **Reconciliation**: `reconciled` flag is `True` when `planned == created + previously completed`

### Deductibility rules (autonomo_es_v1)

The rule table is a YAML file under `packages/ai-parrot-tools/src/parrot_tools/hooba/rules/`:
- **File**: `autonomo_es_v1.yaml`
- **Format**: `AeatRule` → `DeductibilityVerdict` mapping
- **Fields**: `category`, `tax_code`, `subject_to_income_tax`, `income_tax_code`, `simplified`, `accounting_account_code`
- **Priority**: First match wins; fallback rule for unknown concepts

**Every draft carries:**
- `legal_basis`: The rule's legal basis text (e.g. "LIVA art. 20.Uno.18º exento")
- `review_required`: `True` for `unclassified` and `insurance` rules (gestoría sign-off needed)
- `tax_code`: IVA code (IVA21, IVA10, IVA4, EXENTO)
- `subject_to_income_tax`: Whether IRPF withholding applies

## Troubleshooting

### 401 Unauthorized

**Symptom**: API calls return `401 Unauthorized`

**Causes**:
- Session expired (cookie `sid` is stale)
- Credentials invalid or missing
- Network issue preventing login

**Resolution**:
1. Check `HOOBA_USERNAME` and `HOOBA_PASSWORD` are set
2. Verify the broker provider is registered: `CredentialBroker.register("hooba", EnvCredentialResolver(), auth_kind="static_key")`
3. Call `hooba_recover_web_session()` to recover a fresh `sid` cookie
4. If the issue persists, check the login hook logs for errors

### Session recovery fails

**Symptom**: `hooba_recover_web_session()` returns an error

**Causes**:
- `HOOBA_CATALOG_DIR` is not set or invalid
- Catalog is not seeded or missing the `hooba-login` action
- Browser driver not available

**Resolution**:
1. Set `HOOBA_CATALOG_DIR` to the private catalog directory
2. Run `seed_catalog` to populate the catalog
3. Ensure Playwright is installed and the browser is available

### HoobaLookupError

**Symptom**: `HoobaLookupError` raised when looking up contacts, taxes, or accounts

**Causes**:
- Contact not found (threshold 0.85)
- Tax code not found
- Account ID invalid

**Resolution**:
- For contacts: increase the threshold or use `hooba_find_contact` with a broader query
- For taxes: verify the tax code exists in Hooba (check via API)
- For accounts: verify `HOOBA_ACCOUNT_ID` is correct

### HoobaStateError

**Symptom**: `HoobaStateError` raised when creating a draft with state != `draft`

**Causes**:
- Attempting to create a draft that is already issued, confirmed, or cancelled

**Resolution**:
- Check the draft's state before creating (use `hooba_list_drafts`)
- Use `hooba_attach_document` to add to an existing draft instead

### Spec pin mismatch

**Symptom**: `HoobaSpecError` raised with SHA256 mismatch

**Causes**:
- The pinned spec file was tampered with or corrupted
- A different version of the spec was downloaded

**Resolution**:
- Re-run the prune command to regenerate the pinned spec
- Verify the SHA256 hash matches the expected value
- Do not commit the pinned spec to the repo (it is in `.gitignore`)

## Security notes

- **Never log** cookie values, passwords, IBANs, or full bank rows at INFO or above
- **Credentials** are resolved through `CredentialBroker` and never stored in code
- **Private catalog** is outside the repo and contains real selectors; do not commit it
- **Manifest files** are written with restrictive permissions (0o600/0o700)
- **Dry-run mode** is the default for BBVA imports; always review before applying
- **Drafts only**: no code path may call `:issue`, `:confirm`, `:cancel`, `:send*`, or any write outside `DRAFT_OPERATIONS`
