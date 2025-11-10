# EmployeesTool - Employee Hierarchy Tool for AI-Parrot

A comprehensive tool for querying and analyzing employee organizational hierarchies in AI-Parrot. This tool provides a unified interface for agents and chatbots to access employee relationships, reporting structures, and departmental information.

## 📋 Overview

`EmployeesTool` extends `AbstractTool` and provides a standardized way to interact with the `EmployeeHierarchyManager` interface. It enables AI agents to answer questions about organizational structures, reporting relationships, and employee connections.

## 🎯 Features

- **Multiple Query Actions**: Support for 9 different hierarchy operations
- **Async-First Design**: Built on asyncio for high-performance operations
- **Type-Safe**: Uses Pydantic models for input validation
- **Tool Result Format**: Returns standardized `ToolResult` objects
- **Error Handling**: Comprehensive error handling with detailed messages
- **Agent Integration**: Easy integration with BasicAgent, custom agents, and AgentCrew
- **Connection Management**: Automatic connection handling for the hierarchy manager

## 🚀 Quick Start

```python
from parrot.tools.employees_tool import EmployeesTool, EmployeeAction
from parrot.interfaces.hierarchy import EmployeeHierarchyManager
from parrot.bots.agent import BasicAgent

# Initialize hierarchy manager
hierarchy_manager = EmployeeHierarchyManager(
    connection_string="your_connection_string"
)
await hierarchy_manager.connection()

# Create the tool
employees_tool = EmployeesTool(hierarchy_manager=hierarchy_manager)

# Use directly
result = await employees_tool.execute(
    action=EmployeeAction.GET_COLLEAGUES,
    employee_id="E12345"
)
print(result.result)

# Or integrate with an agent
agent = BasicAgent(
    name="HR Assistant",
    model="claude-sonnet-4-20250514"
)
agent.add_tool(employees_tool)
```

## 📊 Available Actions

### 1. `GET_DEPARTMENT_CONTEXT`
Get complete department and organizational context for an employee.

**Parameters:**
- `employee_id` (str, required): Employee ID

**Returns:**
```python
{
    "employee_id": "E12345",
    "found": True,
    "employee": {...},  # Employee details
    "department": "Engineering",
    "program": "Core Platform",
    "reports_to_chain": ["E67890", "E99999"],  # Manager hierarchy
    "colleagues": ["E11111", "E22222"],
    "direct_reports": ["E33333", "E44444"],
    "all_subordinates": [...],
    "direct_reports_count": 2,
    "total_subordinates": 15
}
```

### 2. `GET_SUPERIORS`
Get all managers in the chain of command.

**Parameters:**
- `employee_id` (str, required): Employee ID

**Returns:**
```python
{
    "employee_id": "E12345",
    "found": True,
    "superiors": ["E67890", "E99999"],
    "chain_length": 2,
    "direct_manager": "E67890"
}
```

### 3. `GET_DIRECT_MANAGER`
Get the immediate/direct manager.

**Parameters:**
- `employee_id` (str, required): Employee ID

**Returns:**
```python
{
    "employee_id": "E12345",
    "found": True,
    "direct_manager": "E67890",
    "has_manager": True
}
```

### 4. `GET_COLLEAGUES`
Get employees who share the same manager.

**Parameters:**
- `employee_id` (str, required): Employee ID

**Returns:**
```python
{
    "employee_id": "E12345",
    "found": True,
    "colleagues": ["E11111", "E22222", "E33333"],
    "colleagues_count": 3
}
```

### 5. `GET_DIRECT_REPORTS`
Get employees who directly report to this person (if they're a manager).

**Parameters:**
- `employee_id` (str, required): Employee ID

**Returns:**
```python
{
    "employee_id": "E67890",
    "found": True,
    "is_manager": True,
    "direct_reports": ["E12345", "E11111"],
    "direct_reports_count": 2
}
```

### 6. `GET_ALL_SUBORDINATES`
Get all subordinates recursively (entire hierarchy tree).

**Parameters:**
- `employee_id` (str, required): Employee ID
- `max_depth` (int, optional): Maximum depth to traverse

**Returns:**
```python
{
    "employee_id": "E67890",
    "found": True,
    "is_manager": True,
    "direct_reports": ["E12345", "E11111"],
    "all_subordinates": ["E12345", "E11111", "E33333", ...],
    "direct_reports_count": 2,
    "total_subordinates": 15
}
```

### 7. `DOES_REPORT_TO`
Check if one employee reports to another (directly or indirectly).

**Parameters:**
- `employee_id` (str, required): First employee ID
- `other_employee_id` (str, required): Second employee ID (potential manager)

**Returns:**
```python
{
    "employee_id": "E12345",
    "other_employee_id": "E67890",
    "found": True,
    "reports_to": True,
    "relationship": "direct_manager"  # or "reports_to_level_2", "reports_to_level_3", etc.
}
```

### 8. `ARE_COLLEAGUES`
Check if two employees are colleagues (share the same manager).

**Parameters:**
- `employee_id` (str, required): First employee ID
- `other_employee_id` (str, required): Second employee ID

**Returns:**
```python
{
    "employee_id": "E12345",
    "other_employee_id": "E11111",
    "found": True,
    "are_colleagues": True,
    "same_manager": True,
    "same_department": True,
    "employee1_manager": "E67890",
    "employee2_manager": "E67890"
}
```

### 9. `GET_EMPLOYEE_INFO`
Get basic employee information and context.

**Parameters:**
- `employee_id` (str, required): Employee ID

**Returns:**
```python
{
    "employee_id": "E12345",
    "found": True,
    "employee": {
        "associate_oid": "A12345",
        "employee_id": "E12345",
        "display_name": "John Doe",
        "email": "john.doe@company.com",
        "position_id": "P123",
        "job_code": "ENG-SR"
    },
    "department": "Engineering",
    "program": "Core Platform",
    "direct_manager": "E67890"
}
```

## 🔧 Integration Examples

### With BasicAgent

```python
agent = BasicAgent(
    name="HR Assistant",
    model="claude-sonnet-4-20250514",
    system_prompt="You help employees understand organizational structure."
)

employees_tool = EmployeesTool(hierarchy_manager=hierarchy_manager)
agent.add_tool(employees_tool)

# Now the agent can answer questions like:
# - "Who is my manager?"
# - "List my colleagues"
# - "Does John report to Mary?"
response = await agent.chat("Who does employee E12345 report to?")
```

### With Custom Agent

```python
class HRAgent(BasicAgent):
    def __init__(self, hierarchy_manager, **kwargs):
        super().__init__(
            name="HR Agent",
            system_prompt=self._build_system_prompt(),
            **kwargs
        )

        employees_tool = EmployeesTool(hierarchy_manager=hierarchy_manager)
        self.add_tool(employees_tool)

    def _build_system_prompt(self) -> str:
        return """
        You are an HR assistant with access to organizational hierarchy.
        Help employees understand reporting structures and find colleagues.
        """

hr_agent = HRAgent(
    hierarchy_manager=hierarchy_manager,
    model="claude-sonnet-4-20250514"
)
```

### With AgentCrew

```python
from parrot.bots.orchestration import AgentCrew

# Create specialized agents
org_analyst = BasicAgent(
    name="Org Analyst",
    system_prompt="Analyze organizational structures"
)
org_analyst.add_tool(employees_tool)

hr_coordinator = BasicAgent(
    name="HR Coordinator",
    system_prompt="Coordinate HR activities"
)
hr_coordinator.add_tool(employees_tool)

# Create crew
crew = AgentCrew(
    agents=[org_analyst, hr_coordinator],
    execution_mode="sequential"
)

# Execute complex organizational analysis
result = await crew.execute(
    "Analyze the Engineering department structure"
)
```

## 📝 Common Query Patterns

### Pattern 1: "Who is my manager?"
```python
result = await tool.execute(
    action=EmployeeAction.GET_DIRECT_MANAGER,
    employee_id="E12345"
)
manager = result.result['direct_manager']
```

### Pattern 2: "List my team members"
```python
result = await tool.execute(
    action=EmployeeAction.GET_COLLEAGUES,
    employee_id="E12345"
)
colleagues = result.result['colleagues']
```

### Pattern 3: "Show reporting hierarchy"
```python
result = await tool.execute(
    action=EmployeeAction.GET_DEPARTMENT_CONTEXT,
    employee_id="E12345"
)
chain = result.result['reports_to_chain']
```

### Pattern 4: "Am I a manager?"
```python
result = await tool.execute(
    action=EmployeeAction.GET_DIRECT_REPORTS,
    employee_id="E12345"
)
is_manager = result.result['is_manager']
```

### Pattern 5: "Are we colleagues?"
```python
result = await tool.execute(
    action=EmployeeAction.ARE_COLLEAGUES,
    employee_id="E12345",
    other_employee_id="E67890"
)
are_colleagues = result.result['are_colleagues']
```

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AI Agent / Chatbot                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ add_tool()
                         │
┌────────────────────────▼────────────────────────────────────┐
│                     EmployeesTool                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  • args_schema (Pydantic validation)                 │  │
│  │  • execute() → routes to action handlers             │  │
│  │  • _ensure_connection()                              │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ async calls
                         │
┌────────────────────────▼────────────────────────────────────┐
│              EmployeeHierarchyManager                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  • connection()                                       │  │
│  │  • get_department_context()                          │  │
│  │  • [other hierarchy methods]                         │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ queries
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    ArangoDB / Database                       │
│              (Employee Hierarchy Graph Data)                 │
└─────────────────────────────────────────────────────────────┘
```

## ⚙️ Configuration

### Tool Initialization

```python
employees_tool = EmployeesTool(
    hierarchy_manager=hierarchy_manager,  # Required
    name="employees_hierarchy",           # Optional, default shown
    description="Query employee hierarchy",  # Optional
    output_dir="/path/to/output",         # Optional
    base_url="https://your-domain.com"   # Optional
)
```

### Connection Management

The tool automatically manages connections to the hierarchy manager:

```python
# Connection is established automatically on first use
result = await tool.execute(
    action=EmployeeAction.GET_COLLEAGUES,
    employee_id="E12345"
)

# Or ensure connection manually
await tool._ensure_connection()
```

## 🧪 Testing

```python
import pytest
from parrot.tools.employees_tool import EmployeesTool, EmployeeAction

@pytest.mark.asyncio
async def test_get_colleagues():
    # Mock hierarchy manager
    mock_manager = MockEmployeeHierarchyManager()
    tool = EmployeesTool(hierarchy_manager=mock_manager)

    result = await tool.execute(
        action=EmployeeAction.GET_COLLEAGUES,
        employee_id="E12345"
    )

    assert result.status == "success"
    assert "colleagues" in result.result
    assert result.result["found"] is True
```

## 🔒 Security Considerations

1. **Access Control**: Implement proper access control in the `EmployeeHierarchyManager`
2. **Data Filtering**: Ensure sensitive employee data is filtered based on user permissions
3. **Input Validation**: The tool uses Pydantic for automatic input validation
4. **Error Messages**: Avoid exposing sensitive information in error messages

## 🐛 Error Handling

The tool provides comprehensive error handling:

```python
result = await tool.execute(
    action=EmployeeAction.GET_COLLEAGUES,
    employee_id="INVALID_ID"
)

if result.status == "error":
    print(f"Error: {result.error}")
elif not result.result.get("found"):
    print(f"Employee not found: {employee_id}")
else:
    print(f"Colleagues: {result.result['colleagues']}")
```

## 📊 Performance Considerations

1. **Caching**: The `EmployeeHierarchyManager` should implement caching for frequently accessed data
2. **Batch Operations**: For multiple queries, consider batching at the manager level
3. **Connection Pooling**: Use connection pooling in the hierarchy manager
4. **Async Execution**: All operations are async for maximum concurrency

## 🔄 Extension Points

### Adding Custom Actions

```python
class CustomEmployeesTool(EmployeesTool):
    async def _execute(self, action, **kwargs):
        if action == "custom_action":
            return await self._custom_action(**kwargs)
        return await super()._execute(action, **kwargs)

    async def _custom_action(self, employee_id: str, **kwargs):
        # Your custom logic
        pass
```

### Custom Result Formatting

```python
class FormattedEmployeesTool(EmployeesTool):
    async def _get_colleagues(self, employee_id: str, **kwargs):
        result = await super()._get_colleagues(employee_id, **kwargs)

        # Add custom formatting
        if result["found"]:
            result["formatted_list"] = "\n".join(
                f"- {colleague}"
                for colleague in result["colleagues"]
            )

        return result
```

## 📚 Related Documentation

- [AbstractTool Documentation](../abstract.md)
- [EmployeeHierarchyManager Interface](../../interfaces/hierarchy.md)
- [BasicAgent Documentation](../../bots/agent.md)
- [AgentCrew Documentation](../../bots/orchestration/crew.md)

## 🤝 Contributing

When contributing to this tool:

1. Maintain backward compatibility with existing actions
2. Add comprehensive tests for new actions
3. Update this documentation with new features
4. Follow the existing code style and patterns
5. Ensure all async operations are properly awaited

## 📄 License

Part of the AI-Parrot library. See main project license for details.

## 🆘 Support

For issues and questions:
- Open an issue in the AI-Parrot repository
- Check the examples in `employees_tool_examples.py`
- Review the AI-Parrot documentation at https://docs.ai-parrot.dev
