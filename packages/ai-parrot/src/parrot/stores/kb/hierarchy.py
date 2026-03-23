from typing import Tuple, List, Dict, Any, Optional
import json
from navigator_auth.conf import AUTH_SESSION_OBJECT
from .abstract import AbstractKnowledgeBase
from ...utils.helpers import RequestContext
from ...interfaces.hierarchy import EmployeeHierarchyManager


class EmployeeHierarchyKB(AbstractKnowledgeBase):
    """
    Knowledge Base what provides employee hierarchy context.

    Extracts the associate_oid of the user from the session and searches for:
    - Their direct boss and chain of command
    - Their department and unit
    - Their colleagues
    - Their direct reports (if they are a manager)

    This context is automatically incorporated into the user-context so that
    the LLM is aware of the user's hierarchical position.
    Args:
        permission_service: An instance of HierarchyPermissionService to fetch hierarchy data.
        always_active: If True, this KB is always active (default True)
        priority: The priority of this KB (higher = included first)

    Example:
    ```python
    hierarchy_kb = EmployeeHierarchyKB(
        permission_service=service,
        always_active=True
    )
    bot.register_kb(hierarchy_kb)
    ```
    """

    def __init__(
        self,
        permission_service: EmployeeHierarchyManager,
        always_active: bool = True,
        priority: int = 10,
        employee_id_field: str = "employee_id",
        **kwargs
    ):
        super().__init__(
            name="Employee Hierarchy",
            category="organizational_context",
            description=(
                "Add employee hierarchy context, including their manager, "
                "department, colleagues, and direct reports."
            ),
            activation_patterns=[
                "jefe", "boss", "manager", "reports",
                "department", "unit", "program",
                "colega", "colleague", "equipo", "team",
                "subordinado", "subordinate", "reporte", "organigrama"
            ],
            always_active=always_active,
            priority=priority,
            **kwargs
        )
        self.service = permission_service
        self.employee_id_field = employee_id_field

    async def close(self):
        """Cleanup resources if needed."""
        await self.service.close()

    async def should_activate(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, float]:
        if self.always_active:
            return True, 1.0

        q = query.lower()
        return next(
            (
                (True, 0.9)
                for pattern in self.activation_patterns
                if pattern.lower() in q
            ),
            (False, 0.0),
        )

    async def search(
        self,
        query: str,
        user_id: str = None,
        session_id: str = None,
        ctx: RequestContext = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Search and return the employee hierarchy context.

        Args:
            query: User query (not used directly)
            user_id: User ID
            session_id: Session ID
            ctx: RequestContext with session information

        Returns:
            List of facts about the employee hierarchy
        """
        employee_id = await self._get_employee_id(
            ctx,
            session_id,
            user_id,
            kwargs
        )
        print('HERE > ', employee_id)

        if not employee_id:
            return []

        # Ensure async hierarchy manager is connected
        try:
            if not getattr(self.service, "db", None):
                await self.service.connection()
        except Exception as e:
            self.logger.error(f"Error connecting to hierarchy service: {e}")
            return []

        try:
            emp_context = await self.service.get_department_context(employee_id)
            if not emp_context or 'employee' not in emp_context:
                return []

            return self._build_hierarchy_facts(emp_context, employee_id)

        except Exception as e:
            self.logger.error(f"Error getting hierarchy context: {e}")
            return []

    async def _get_employee_id(
        self,
        ctx: Optional[RequestContext],
        session_id: Optional[str],
        user_id: Optional[str],
        kwargs: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extract the employee id from various sources.

        Order of priority:
        1. From kwargs (explicit)
        2. From ctx.request.session (web session)
        3. From user_id (if it has self.employee_id_field format)
        4. search in DB by user_id
        """
        # 1. From kwargs (explicit)
        if self.employee_id_field in kwargs:
            return kwargs[self.employee_id_field]

        # 2. From RequestContext (web session)
        if ctx and ctx.request:
            if session := getattr(ctx.request, 'session', None):
                auth_obj = session.get(AUTH_SESSION_OBJECT, {})
                if employee_id := (
                    auth_obj.get(self.employee_id_field) or
                    session.get(self.employee_id_field)
                ):
                    return employee_id

        # 3. From user_id if it looks like an employee id
        if user_id and isinstance(user_id, str) and user_id.startswith(('E', 'EMP', 'A')):
            return user_id

        return None

    def _build_hierarchy_facts(
        self,
        emp_context: Dict[str, Any],
        employee_id: str
    ) -> List[Dict[str, Any]]:
        """
        Produce a compact, LLM-friendly hierarchy summary + a few readable facts.

        This is meant to be injected directly into the Agent System Prompt.
        """
        emp = emp_context.get('employee', {}) or {}
        dept = emp_context.get('department')
        prog = emp_context.get('program')

        reports_chain = emp_context.get('reports_to_chain') or []
        colleagues = emp_context.get('colleagues') or []
        direct_reports = emp_context.get('manages') or []
        total_subordinates = emp_context.get(
            'total_subordinates',
            len(emp_context.get('all_subordinates') or [])
        )
        direct_reports_count = emp_context.get(
            'direct_reports_count',
            len(direct_reports)
        )

        direct_manager = reports_chain[0] if reports_chain else None

        compact = {
            "employee_id": emp.get("employee_id") or employee_id,
            "associate_oid": emp.get("associate_oid") or employee_id,
            "name": emp.get("display_name"),
            "email": emp.get("email"),
            "department": dept,
            "program": prog,
            "position_id": emp.get("position_id"),
            "job_code": emp.get("job_code"),
            "direct_manager": direct_manager,
            "manager_chain": reports_chain,            # ordered, closest first
            "colleagues_sample": colleagues[:8],       # peers w/ same boss
            "colleagues_count": len(colleagues),
            "direct_reports_sample": direct_reports[:8],
            "direct_reports_count": direct_reports_count,
            "total_subordinates": total_subordinates,
        }

        facts: List[Dict[str, Any]] = [
            {
                "content": "EmployeeHierarchyContext:: "
                + json.dumps(compact, ensure_ascii=False),
                "metadata": {
                    "category": "employee_hierarchy_compact",
                    "entity_type": "employee_hierarchy",
                    "confidence": 1.0,
                    "tags": [
                        "employee",
                        "hierarchy",
                        "compact_context",
                        "manager",
                        "colleagues",
                        "subordinates",
                    ],
                },
            }
        ]

        # 2) Minimal human-readable facts (still concise)
        if compact.get("name") and dept and prog:
            facts.append({
                "content": (
                    f"{compact['name']} ({compact['employee_id']}) "
                    f"works in {dept} - {prog}."
                ),
                "metadata": {
                    "category": "employee_info",
                    "entity_type": "employee",
                    "confidence": 1.0,
                    "tags": ["employee", "department", "program"],
                },
            })

        if direct_manager:
            facts.append({
                "content": f"Direct manager: {direct_manager}.",
                "metadata": {
                    "category": "reporting_structure",
                    "entity_type": "manager",
                    "confidence": 1.0,
                    "tags": ["manager", "direct_manager"],
                },
            })

        if direct_reports_count > 0:
            text = f"{direct_reports_count} direct report(s)"
            if sample := ", ".join(direct_reports[:5]):
                text += f": {sample}"
            if more := max(0, direct_reports_count - 5):
                text += f" and {more} more"
            text += "."
            facts.append({
                "content": text,
                "metadata": {
                    "category": "management",
                    "entity_type": "direct_reports",
                    "confidence": 1.0,
                    "tags": ["manager", "direct_reports", "team"],
                },
            })

        if colleagues:
            sample = ", ".join(colleagues[:5])
            more = max(0, len(colleagues) - 5)
            text = f"Colleagues with the same manager: {sample}"
            if more:
                text += f" and {more} more"
            text += "."
            facts.append({
                "content": text,
                "metadata": {
                    "category": "colleagues",
                    "entity_type": "peers",
                    "confidence": 0.9,
                    "tags": ["colleagues", "team", "peers"],
                },
            })

        return facts

    def format_context(self, results: List[Dict[str, Any]]) -> str:
        """
        Final string injected into the Agent System Prompt.

        Puts the compact JSON-like context first so tools/LLM can parse it,
        then short readable bullets.
        """
        if not results:
            return ""

        by_category: Dict[str, List[str]] = {}
        for r in results:
            cat = r.get("metadata", {}).get("category", "general")
            by_category.setdefault(cat, []).append(r["content"])

        lines: List[str] = [f"## {self.name}"]

        # 1) Compact block (highest priority for LLM)
        compact = by_category.get("employee_hierarchy_compact")
        if compact:
            lines.append("### Compact Hierarchy Context")
            lines.extend(iter(compact))

        # 2) Other concise sections (only if present)
        ordered = [
            ("employee_info", "Employee Information"),
            ("reporting_structure", "Reporting Structure"),
            ("management", "Direct Reports"),
            ("colleagues", "Colleagues"),
        ]

        for key, title in ordered:
            contents = by_category.get(key)
            if not contents:
                continue
            lines.append(f"\n**{title}:**")
            lines.extend(f"  • {c}" for c in contents)

        # 3) Any remaining categories
        for key, contents in by_category.items():
            if key in {"employee_hierarchy_compact", "employee_info",
                       "reporting_structure", "management", "colleagues"}:
                continue
            lines.append(f"\n**{key.title()}:**")
            lines.extend(f"  • {c}" for c in contents)

        return "\n".join(lines)
