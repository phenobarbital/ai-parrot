---
id: F004
query: Q004
type: read
file: packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
lines: 566-648
---

## submit_data Handler

**Route**: POST `/api/v1/forms/{form_id}/data`
**Flow**:
1. Load form from registry (404 if missing)
2. Parse JSON body (400 if invalid)
3. `FormValidator.validate(form, data)` → ValidationResult
4. Build FormSubmission with sanitized_data
5. Store locally via FormSubmissionStorage (optional)
6. Forward to endpoint if configured
7. Return {submission_id, is_valid, forwarded, ...}

**Integration point**: The final submit could merge partial saves from
Redis into the submission data before validation. Or the frontend
could reconstruct the full payload from cached partials + final edits.

**Handler constructor** (lines 51-64):
- Accepts registry, client, submission_storage, forwarder
- Creates FormValidator and JsonSchemaRenderer internally
- New partial_save_store would need to be injected similarly
