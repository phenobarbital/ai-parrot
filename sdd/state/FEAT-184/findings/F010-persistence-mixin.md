# F010 — ReportPersistenceMixin

**Path**: `packages/ai-parrot-tools/src/parrot_tools/security/persistence.py`
**Lines**: 59-198

Mixin for producer toolkits. Provides `_persist_report(...)` and
`_mirror_rendered_report(...)`.

Constructor protocol: pop `file_manager` and `report_store` from
kwargs BEFORE super().__init__().

The new toolkit is a **consumer**, not a producer. It should NOT
inherit this mixin. Instead, it directly composes `SecurityReportStore`
and `FileManagerInterface` for reading.
