---
id: F015
query_id: Q016
type: read
intent: Depth-1 follow-up: does https://api.hooba.com/api/doc serve a machine-readable OpenAPI document, and which endpoints cover the three requested capabilities?
executed_at: 2026-09-25T11:30:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F015 — Hooba publishes a real OpenAPI 3.0.0 (Nelmio/Symfony) at /api/doc.json — 656 paths, cookie-session auth, and native draft states for invoices and purchase invoices

## Summary

`GET https://api.hooba.com/api/doc` → 200 text/html Swagger UI (NelmioApiDocBundle) embedding the spec; `GET /api/doc.json` → 200 application/json, `openapi: 3.0.0`, title "hooba API", version **2026.6.17**, 656 paths / 970 operations, `servers: null`, **no `securitySchemes` and no global `security`** (auth is the `sid` session cookie set by `POST /auth/login {username,password}` → 200 `User` schema; also `GET /auth/check`, `POST /auth/logout`). Every business path is `/accounts/{accountId}/...`. Invoices: `POST /accounts/{accountId}/invoices` (fields invoiceSerieId, contactId, currencyId, languageId, paymentMethodId, paymentTermId, reference, notes, periodStart/End, operationDate, simplified, subjectToIncomeTax...), lines via `POST .../invoices/{invoiceId}/invoice-lines` (oneOf product/title: type, name, price, quantity, discount, taxId?, incomeTaxId, accountingAccountId), `InvoiceState = canceled|draft|issued|replaced|scheduled`, and `:issue` is a separate `POST .../invoices/{invoiceId}:issue` → creation yields a **draft**. Expenses/purchases: `POST /accounts/{accountId}/purchase-invoices` (date, number, simplified, currencyId, contactId, paymentMethodId, bankAccountId, periodStart/End, accountingDate, operationDate, notes, subjectToEquivalenceSurcharge, subjectToIncomeTax, globalDiscount...), lines via `POST .../purchase-invoices/{id}/purchase-invoice-lines` (accountingAccountId, productId, name, price, unitOfMeasureId, quantity, discount, taxId, incomeTaxId, notes), `PurchaseInvoiceState = confirmed|draft|replaced`, `:confirm` separate → creation yields a **draft**; `POST .../purchase-invoices:create-from-inbox-file {inboxFileId, date, number, contactId, simplified, taxIncluded, documentTypeId}`; `GET /accounts/{accountId}/inbox-files` (no POST in spec). Attachments: `POST /accounts/{accountId}/documents/{documentTypeId}/{entityRecordId}` multipart `file` + `data` JSON. Supporting lookups: `/invoice-series`, `/contacts` (+`:import`), `/account-bank-accounts`, `/reports/purchase-invoice-tax-summary`, `/reports/purchase-invoice-model-347-summary`. Compact digest persisted at `sdd/state/FEAT-602/hooba-openapi-digest.json` (217 ops across the relevant tags).

## Citations


- path: `sdd/state/FEAT-602/hooba-openapi-digest.json`
  lines: 1-1
  symbol: `digest`
  excerpt: |
    openapi 3.0.0, info.version 2026.6.17, securitySchemes null, totals {paths: 656, operations: 970}

- path: `https://api.hooba.com/api/doc.json`
  lines: POST /auth/login
  symbol: `Authentication`
  excerpt: |
    responses 200 → #/components/schemas/User (id, firstName, firstSurname, secondSurname, timeZone, phone, email, ...); 401; 409

- path: `https://api.hooba.com/api/doc.json`
  lines: POST /accounts/{accountId}/invoices
  symbol: `Invoice create (draft)`
  excerpt: |
    invoiceSerieId, simplified, currencyId, exchangeRate, languageId, contactId(min 1), paymentMethodId, issuerBankAccountId, recipientBankAccountId, paymentTermId, globalDiscount, earlyPaymentDiscount, subjectToEquivalenceSurcharge, subjectToIncomeTax, reference, considerations, periodStart, periodEnd, operationDate, notes, priceListId

- path: `https://api.hooba.com/api/doc.json`
  lines: POST /accounts/{accountId}/invoices/{invoiceId}:issue
  symbol: `Invoice issue (SUBMIT-kind)`
  excerpt: |
    separate action; InvoiceState enum: canceled, draft, issued, replaced, scheduled

- path: `https://api.hooba.com/api/doc.json`
  lines: POST /accounts/{accountId}/purchase-invoices
  symbol: `PurchaseInvoice create (draft)`
  excerpt: |
    date(Y-m-d), number, simplified, currencyId, exchangeRate, contactId, contactOrganizationalUnitId, issuerBankAccountId, paymentMethodId, bankAccountId, paymentTermId, periodStart, periodEnd, accountingDate, operationDate, notes, subjectToEquivalenceSurcharge, subjectToIncomeTax, globalDiscount ...

- path: `https://api.hooba.com/api/doc.json`
  lines: POST /accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines
  symbol: `PurchaseInvoiceLine`
  excerpt: |
    accountingAccountId, productId, name, price, unitOfMeasureId, quantity, discount, taxId, incomeTaxId, notes

- path: `https://api.hooba.com/api/doc.json`
  lines: POST /accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}:confirm
  symbol: `PurchaseInvoice confirm (SUBMIT-kind)`
  excerpt: |
    PurchaseInvoiceState enum: confirmed, draft, replaced

- path: `https://api.hooba.com/api/doc.json`
  lines: POST /accounts/{accountId}/purchase-invoices:create-from-inbox-file
  symbol: `create from inbox file`
  excerpt: |
    inboxFileId, date, number, contactId, simplified, subjectToEquivalenceSurcharge, subjectToIncomeTax, taxIncluded, documentTypeId

- path: `https://api.hooba.com/api/doc.json`
  lines: POST /accounts/{accountId}/documents/{documentTypeId}/{entityRecordId}
  symbol: `Document upload`
  excerpt: |
    multipart/form-data: file (binary), data (json string)

- path: `https://api.hooba.com/api/doc.json`
  lines: GET /accounts/{accountId}/member
  symbol: `Member`
  excerpt: |
    sample in source.md: member/user/roleIds/applicationIds

## Notes

External evidence (public doc, read-only GET, fetched 2026-09-25). The captured request in the source used `cookie: sid=...`, `origin: https://app.hooba.com`, `x-hooba-language: es`, `ngsw-bypass: true`; none of these headers are declared in the spec, so the client must set them explicitly. Whether the API also accepts a token (subscriptionId hints at plan tiers) is not stated anywhere in the document.

