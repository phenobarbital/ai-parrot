---
id: F003
title: AbstractTool / ToolResult — base contract DatabaseFormTool implements
source_queries: [Q003]
---

`packages/ai-parrot/src/parrot/tools/abstract.py`

- `AbstractTool` is ABC with `_execute(self, **kwargs) -> Any` as the only
  required abstract method (line 200-201).
- `execute()` (line 375) is the public wrapper — it validates args via
  `args_schema`, runs permission checks (`resolver.can_execute`), and
  invokes `_execute(*args, **validated_args.model_dump())` (line 432).
- `ToolResult` (lines 36-43): `success`, `status`, `result`, `error`,
  `metadata` (dict). Tools return `ToolResult` from `_execute` per the
  established pattern.

This means: a refactored `DatabaseFormTool._execute(formid, orgid, service, persist)`
will still receive these kwargs from `args_schema` validation. The new
`service` field is therefore passed in transparently.

The `args_schema = DatabaseFormInput` (line 154 of database_form.py) is how
the framework injects validated kwargs — adding `service` to the input model
is sufficient to surface it inside `_execute`.
