---
kind: inline
jira_key: null
fetched_at: 2026-05-13T00:00:00Z
summary_oneline: Make DatabaseFormTool pluggable via AbstractFormService; migrate networkninja query into a NetworkninjaFormService.
---

# multi-origin-formdesigner

Current `DatabaseFormTool` in `parrot_designer/tools/database_form.py` (actual path:
`packages/parrot-formdesigner/src/parrot_formdesigner/tools/database_form.py`) is
integrated with one database and form system only (networkninja).

The idea is to make this a pluggable tool by adding a sub-package `services/` where the
current networkninja query is migrated. `DatabaseFormInput` will then accept a `service`
field (default `'networkninja'`), and the tool uses that attribute to load an instance
of the corresponding service.

## Logic dependency

`AbstractFormService(ABC)` will receive all logic for getting form data from databases
(or even other sources such as REST APIs in the future — outside this scope) and
converting it into `FormSchema` objects.

`DatabaseFormTool` then becomes a thin client that consumes `service` and returns the
`FormSchema` produced by the service.

## Tasks

- Create `AbstractFormService(ABC)` at `parrot_formdesigner/tools/services/` with all
  required logic to:
  - run SQL queries against databases
  - build `FormSchema` objects

- Create `NetworkninjaFormService(AbstractFormService)` that migrates the current
  logic for converting this query:

  ```sql
  SELECT
      f.formid, f.form_name, f.description, f.client_id, f.client_name, f.orgid,
      f.question_blocks,
      jsonb_agg(
          jsonb_build_object(
              'column_id', m.column_id, 'column_name', m.column_name,
              'description', m.description, 'data_type', m.data_type
          )
      ) AS metadata
  FROM networkninja.forms f
  JOIN networkninja.form_metadata m USING(formid)
  WHERE f.formid = $1 AND f.orgid = $2 AND m.is_active = true
  GROUP BY f.formid, f.form_name, f.description, f.client_id, f.client_name,
           f.orgid, f.question_blocks
  ```

  into a `FormSchema`.

- Modify `DatabaseFormInput` to support a `service` declaration (default
  `'networkninja'`).

- Modify `DatabaseFormTool` to dynamically resolve an `AbstractFormService` instance
  based on the `service` field of `DatabaseFormInput`, invoke it, and return the
  resulting `FormSchema`.
