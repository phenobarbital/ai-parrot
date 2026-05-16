---
id: F009
query: "Knowledge base RequestContext usage"
type: read
files: parrot/stores/kb/{abstract,hierarchy,user,local}.py
---

AbstractKnowledgeBase.search() accepts `ctx: RequestContext = None`.
EmployeeHierarchyKB._get_employee_id() reads ctx.request.session for auth data.

KBs are the primary CONSUMER of RequestContext beyond the handler layer.
With ContextVar, KBs could call current_context() directly instead of receiving
ctx through the _build_kb_context() → search() call chain.
