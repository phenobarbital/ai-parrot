from typing import Tuple, List, Dict, Any, Optional
from navigator_auth.conf import AUTH_SESSION_OBJECT
from .abstract import AbstractKnowledgeBase
from ...utils.helpers import RequestContext
from .cache import TTLCache
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
        **kwargs
    ):
        """


        Args:
            permission_service: EmployeeHierarchyManager instance.
            always_active: if True, always active (default True)
            priority: Priority of the KB (higher = included first)
        """
        super().__init__(
            name="Employee Hierarchy",
            category="organizational_context",
            description=(
                "Add employee hierarchy context, "
                "including their boss, department, colleagues, and direct reports."
            ),
            activation_patterns=[
                "jefe", "boss", "manager", "reports",
                "department", "department", "unit", "program",
                "colega", "colleague", "equipo", "team",
                "subordinado", "subordinate", "reporte", "organigrama"
            ],
            always_active=always_active,
            priority=priority,
            **kwargs
        )
        self.service = permission_service

    async def should_activate(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> Tuple[bool, float]:
        """
        Determina si este KB debe activarse para la consulta.

        Como always_active=True, siempre se activa con alta confianza.
        """
        if self.always_active:
            return True, 1.0

        # Buscar patrones de activación en la query
        query_lower = query.lower()
        return next(
            (
                (True, 0.9)
                for pattern in self.activation_patterns
                if pattern.lower() in query_lower
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

        if not employee_id:
            # There is no employee_id, cannot provide hierarchy context
            return []

        try:
            emp_context = await self.service.get_department_context(employee_id)
            if not emp_context or 'employee' not in emp_context:
                return []

            # Build structured facts for User Context
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
        Extract the employee id (associate_oid) from various sources.

        Order of priority:
        1. From kwargs (explicit)
        2. From ctx.request.session (web session)
        3. From user_id (if it has associate_oid format)
        4. search in DB by user_id
        """
        # From kwargs (explicit)
        if 'associate_oid' in kwargs:
            return kwargs['associate_oid']

        # 2. From RequestContext (web session)
        if ctx and ctx.request:
            if session := getattr(ctx.request, 'session', None):
                auth_obj = session.get(AUTH_SESSION_OBJECT, {})
                # Find Employee OID
                if associate_oid := (
                    auth_obj.get('associate_oid') or
                    session.get('associate_oid')
                ):
                    return associate_oid

        # 3. From user_id (if it has associate_oid format)
        if user_id and isinstance(user_id, str) and user_id.startswith(('E', 'EMP', 'A')):
            return user_id

        return None

    def _build_hierarchy_facts(
        self,
        emp_context: Dict[str, Any],
        associate_oid: str
    ) -> List[Dict[str, Any]]:
        """
        Build Facts from the employee context.

        Args:
            emp_context: Employee context dictionary
            associate_oid: Employee ID

        Returns:
            List of facts with content and metadata
        """
        facts = []
        # Fact 1: Basic employee info
        facts.append({
            'content': (
                f"Employee: {associate_oid} "
                f"works in {emp_context['department']} - {emp_context['program']}."
            ),
            'metadata': {
                'category': 'employee_info',
                'entity_type': 'employee',
                'confidence': 1.0,
                'tags': ['employee', 'department', 'program']
            }
        })

        # Fact 2: Reporting chain (supervisors)
        reports_to = emp_context.get('reports_to_chain', [])
        if reports_to:
            if len(reports_to) == 1:
                facts.append({
                    'content': f"Direct manager is {reports_to[0]}.",
                    'metadata': {
                        'category': 'reporting_structure',
                        'entity_type': 'manager',
                        'confidence': 1.0,
                        'tags': ['manager', 'direct_report']
                    }
                })
            else:
                chain = " → ".join(reports_to)
                facts.append({
                    'content': f"Reporting chain: {chain}.",
                    'metadata': {
                        'category': 'reporting_structure',
                        'entity_type': 'hierarchy',
                        'confidence': 1.0,
                        'tags': ['hierarchy', 'management_chain']
                    }
                })
        else:
            facts.append({
                'content': "Is a high-level executive with no direct reports.",
                'metadata': {
                    'category': 'reporting_structure',
                    'entity_type': 'executive',
                    'confidence': 1.0,
                    'tags': ['executive', 'leadership']
                }
            })

        # Fact 4: Direct reports (if manager)
        if manages := emp_context.get('manages', []):
            reports_str = ", ".join(manages[:5])
            more = len(manages) - 5
            facts.append({
                'content': (
                    f"Has {len(manages)} direct report(s): {reports_str}"
                    f"{f' and {more} more' if more > 0 else ''}."
                ),
                'metadata': {
                    'category': 'management',
                    'entity_type': 'direct_reports',
                    'confidence': 1.0,
                    'tags': ['manager', 'direct_reports', 'leadership']
                }
            })

        return facts

    def format_context(self, results: List[Dict]) -> str:
        """
        Format the results for injection into the prompt.

        Override the base method for a more readable format.
        """
        if not results:
            return ""

        lines = [f"## {self.name}:"]

        # Group by category
        by_category = {}
        for result in results:
            category = result.get('metadata', {}).get('category', 'general')
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(result['content'])

        # Format by category
        category_names = {
            'employee_info': 'Employee Information',
            'reporting_structure': 'Reporting Structure',
            'management': 'Direct Reports'
        }

        for category, contents in by_category.items():
            category_title = category_names.get(category, category.title())
            lines.append(f"\n**{category_title}:**")
            lines.extend(f"  • {content}" for content in contents)

        return "\n".join(lines)
