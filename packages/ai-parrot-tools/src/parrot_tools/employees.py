"""
Employee Hierarchy Tool for AI-Parrot.

Provides employee hierarchy operations as a unified tool interface
for AI agents and chatbots.
"""
from typing import Dict, Any, Optional
from enum import Enum
from pydantic import Field
from navconfig.logging import logging

from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot.interfaces.hierarchy import EmployeeHierarchyManager


class EmployeeAction(str, Enum):
    """Available employee hierarchy actions."""
    GET_SUPERIORS = "get_superiors"
    GET_DIRECT_MANAGER = "get_direct_manager"
    GET_COLLEAGUES = "get_colleagues"
    GET_DIRECT_REPORTS = "get_direct_reports"
    GET_ALL_SUBORDINATES = "get_all_subordinates"
    GET_DEPARTMENT_CONTEXT = "get_department_context"
    DOES_REPORT_TO = "does_report_to"
    ARE_COLLEAGUES = "are_colleagues"
    GET_EMPLOYEE_INFO = "get_employee_info"


class EmployeesToolArgsSchema(AbstractToolArgsSchema):
    """Arguments schema for EmployeesTool."""

    action: EmployeeAction = Field(
        description=(
            "Action to perform. Options:\n"
            "- get_superiors: Get all superiors in the chain of command\n"
            "- get_direct_manager: Get the immediate manager\n"
            "- get_colleagues: Get colleagues with the same manager\n"
            "- get_direct_reports: Get direct reports (if manager)\n"
            "- get_all_subordinates: Get all subordinates recursively\n"
            "- get_department_context: Get complete department context\n"
            "- does_report_to: Check if employee_id reports to other_employee_id\n"
            "- are_colleagues: Check if two employees are colleagues\n"
            "- get_employee_info: Get basic employee information"
        )
    )

    employee_id: str = Field(
        description="Employee ID or associate_oid (e.g., 'E12345', 'EMP001', 'A123')"
    )

    other_employee_id: Optional[str] = Field(
        default=None,
        description=(
            "Second employee ID for comparative operations "
            "(required for 'does_report_to' and 'are_colleagues' actions)"
        )
    )

    include_details: bool = Field(
        default=True,
        description="Include detailed employee information (name, email, position)"
    )

    max_depth: Optional[int] = Field(
        default=None,
        description="Maximum depth for hierarchical queries (for get_all_subordinates)"
    )


class EmployeesTool(AbstractTool):
    """
    Employee Hierarchy Tool for querying organizational structure.

    This tool provides unified access to employee hierarchy operations through
    the EmployeeHierarchyManager interface. It supports various queries including:
    - Reporting relationships (managers, subordinates)
    - Peer relationships (colleagues)
    - Department and organizational context
    - Hierarchical comparisons

    Example Usage:
        ```python
        # Initialize the tool
        hierarchy_manager = EmployeeHierarchyManager(...)
        employees_tool = EmployeesTool(hierarchy_manager=hierarchy_manager)

        # Register with an agent
        agent.add_tool(employees_tool)

        # Query examples:
        # "Who is John's manager?"
        # "Get all employees reporting to Mary"
        # "Are Alice and Bob colleagues?"
        # "Show me the department context for employee E12345"
        ```

    Args:
        hierarchy_manager: Instance of EmployeeHierarchyManager
        name: Tool name (default: "employees_hierarchy")
        description: Tool description
        **kwargs: Additional arguments passed to AbstractTool
    """

    name: str = "employees_hierarchy"
    description: str = (
        "Query employee hierarchy and organizational structure. "
        "Get information about managers, subordinates, colleagues, "
        "and reporting relationships."
    )
    args_schema = EmployeesToolArgsSchema
    return_direct: bool = False

    def __init__(
        self,
        hierarchy_manager: EmployeeHierarchyManager,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize the EmployeesTool.

        Args:
            hierarchy_manager: EmployeeHierarchyManager instance
            name: Optional tool name override
            description: Optional description override
            **kwargs: Additional arguments for AbstractTool
        """
        super().__init__(
            name=name or self.name,
            description=description or self.description,
            **kwargs
        )

        self.hierarchy_manager = hierarchy_manager
        self.logger = logging.getLogger(f"Parrot.Tools.{self.name}")

    async def _ensure_connection(self) -> None:
        """Ensure the hierarchy manager is connected."""
        if not getattr(self.hierarchy_manager, "db", None):
            try:
                await self.hierarchy_manager.connection()
            except Exception as e:
                self.logger.error(f"Failed to connect hierarchy manager: {e}")
                raise RuntimeError(
                    f"Could not establish connection to hierarchy service: {e}"
                ) from e

    async def _execute(
        self,
        action: EmployeeAction,
        employee_id: str,
        other_employee_id: Optional[str] = None,
        include_details: bool = True,
        max_depth: Optional[int] = None,
        **kwargs
    ) -> Any:
        """
        Execute the employee hierarchy operation.

        Args:
            action: The action to perform
            employee_id: Primary employee ID
            other_employee_id: Secondary employee ID (for comparative operations)
            include_details: Include detailed information
            max_depth: Maximum depth for recursive queries
            **kwargs: Additional arguments

        Returns:
            Result data depending on the action performed
        """
        # Ensure connection
        await self._ensure_connection()

        # Route to appropriate handler
        action_handlers = {
            EmployeeAction.GET_SUPERIORS: self._get_superiors,
            EmployeeAction.GET_DIRECT_MANAGER: self._get_direct_manager,
            EmployeeAction.GET_COLLEAGUES: self._get_colleagues,
            EmployeeAction.GET_DIRECT_REPORTS: self._get_direct_reports,
            EmployeeAction.GET_ALL_SUBORDINATES: self._get_all_subordinates,
            EmployeeAction.GET_DEPARTMENT_CONTEXT: self._get_department_context,
            EmployeeAction.DOES_REPORT_TO: self._does_report_to,
            EmployeeAction.ARE_COLLEAGUES: self._are_colleagues,
            EmployeeAction.GET_EMPLOYEE_INFO: self._get_employee_info,
        }

        if handler := action_handlers.get(action):
            # Execute the handler
            return await handler(
                employee_id=employee_id,
                other_employee_id=other_employee_id,
                include_details=include_details,
                max_depth=max_depth,
                **kwargs
            )
        raise ValueError(
            f"Unknown action: {action}"
        )

    async def _get_department_context(
        self,
        employee_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get complete department context for an employee."""
        try:
            context = await self.hierarchy_manager.get_department_context(employee_id)
            if not context or 'employee' not in context:
                return {
                    "employee_id": employee_id,
                    "found": False,
                    "message": f"No context found for employee {employee_id}"
                }

            return {
                "employee_id": employee_id,
                "found": True,
                "employee": context.get('employee', {}),
                "department": context.get('department'),
                "program": context.get('program'),
                "reports_to_chain": context.get('reports_to_chain', []),
                "colleagues": context.get('colleagues', []),
                "direct_reports": context.get('manages', []),
                "all_subordinates": context.get('all_subordinates', []),
                "direct_reports_count": context.get('direct_reports_count', 0),
                "total_subordinates": context.get('total_subordinates', 0),
            }
        except Exception as e:
            self.logger.error(f"Error getting department context: {e}")
            raise

    async def _get_superiors(
        self,
        employee_id: str,
        include_details: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Get all superiors in the chain of command."""
        context = await self._get_department_context(employee_id)

        if not context.get('found'):
            return context

        reports_chain = context.get('reports_to_chain', [])

        return {
            "employee_id": employee_id,
            "found": True,
            "superiors": reports_chain,
            "chain_length": len(reports_chain),
            "direct_manager": reports_chain[0] if reports_chain else None,
        }

    async def _get_direct_manager(
        self,
        employee_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get the immediate/direct manager."""
        context = await self._get_department_context(employee_id)

        if not context.get('found'):
            return context

        reports_chain = context.get('reports_to_chain', [])
        direct_manager = reports_chain[0] if reports_chain else None

        return {
            "employee_id": employee_id,
            "found": True,
            "direct_manager": direct_manager,
            "has_manager": direct_manager is not None,
        }

    async def _get_colleagues(
        self,
        employee_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get colleagues with the same manager."""
        context = await self._get_department_context(employee_id)

        if not context.get('found'):
            return context

        colleagues = context.get('colleagues', [])

        return {
            "employee_id": employee_id,
            "found": True,
            "colleagues": colleagues,
            "colleagues_count": len(colleagues),
        }

    async def _get_direct_reports(
        self,
        employee_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get direct reports (employees directly managed)."""
        context = await self._get_department_context(employee_id)

        if not context.get('found'):
            return context

        direct_reports = context.get('direct_reports', [])

        return {
            "employee_id": employee_id,
            "found": True,
            "is_manager": len(direct_reports) > 0,
            "direct_reports": direct_reports,
            "direct_reports_count": len(direct_reports),
        }

    async def _get_all_subordinates(
        self,
        employee_id: str,
        max_depth: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Get all subordinates recursively."""
        context = await self._get_department_context(employee_id)

        if not context.get('found'):
            return context

        all_subordinates = context.get('all_subordinates', [])
        direct_reports = context.get('direct_reports', [])

        # If max_depth is specified, we'd need to implement depth filtering
        # For now, return all subordinates from the context

        return {
            "employee_id": employee_id,
            "found": True,
            "is_manager": len(direct_reports) > 0,
            "direct_reports": direct_reports,
            "all_subordinates": all_subordinates,
            "direct_reports_count": len(direct_reports),
            "total_subordinates": len(all_subordinates),
        }

    async def _does_report_to(
        self,
        employee_id: str,
        other_employee_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Check if employee_id reports to other_employee_id."""
        if not other_employee_id:
            return {
                "employee_id": employee_id,
                "found": False,
                "error": "other_employee_id is required for 'does_report_to' action"
            }

        # Get the employee's superiors
        superiors_result = await self._get_superiors(employee_id)

        if not superiors_result.get('found'):
            return superiors_result

        superiors = superiors_result.get('superiors', [])
        reports_to = other_employee_id in superiors

        # Determine relationship level
        relationship = "none"
        if reports_to:
            try:
                level = superiors.index(other_employee_id) + 1
                relationship = "direct_manager" if level == 1 else f"reports_to_level_{level}"
            except ValueError:
                relationship = "reports_to"

        return {
            "employee_id": employee_id,
            "other_employee_id": other_employee_id,
            "found": True,
            "reports_to": reports_to,
            "relationship": relationship,
        }

    async def _are_colleagues(
        self,
        employee_id: str,
        other_employee_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Check if two employees are colleagues (same manager)."""
        if not other_employee_id:
            return {
                "employee_id": employee_id,
                "found": False,
                "error": "other_employee_id is required for 'are_colleagues' action"
            }

        # Get both employees' contexts
        context1 = await self._get_department_context(employee_id)
        context2 = await self._get_department_context(other_employee_id)

        if not context1.get('found') or not context2.get('found'):
            return {
                "employee_id": employee_id,
                "other_employee_id": other_employee_id,
                "found": False,
                "error": "Could not find one or both employees"
            }

        # Check if they have the same direct manager
        manager1 = (context1.get('reports_to_chain') or [None])[0]
        manager2 = (context2.get('reports_to_chain') or [None])[0]

        are_colleagues = manager1 is not None and manager1 == manager2

        # Also check department
        same_department = (
            context1.get('department') == context2.get('department')
            if context1.get('department') and context2.get('department')
            else False
        )

        return {
            "employee_id": employee_id,
            "other_employee_id": other_employee_id,
            "found": True,
            "are_colleagues": are_colleagues,
            "same_manager": are_colleagues,
            "same_department": same_department,
            "employee1_manager": manager1,
            "employee2_manager": manager2,
        }

    async def _get_employee_info(
        self,
        employee_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get basic employee information."""
        context = await self._get_department_context(employee_id)

        if not context.get('found'):
            return context

        employee = context.get('employee', {})

        return {
            "employee_id": employee_id,
            "found": True,
            "employee": {
                "associate_oid": employee.get('associate_oid'),
                "employee_id": employee.get('employee_id'),
                "display_name": employee.get('display_name'),
                "email": employee.get('email'),
                "position_id": employee.get('position_id'),
                "job_code": employee.get('job_code'),
            },
            "department": context.get('department'),
            "program": context.get('program'),
            "direct_manager": (context.get('reports_to_chain') or [None])[0],
        }
