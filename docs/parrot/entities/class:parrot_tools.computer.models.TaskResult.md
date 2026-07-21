---
type: Wiki Entity
title: TaskResult
id: class:parrot_tools.computer.models.TaskResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a single task execution.
---

# TaskResult

Defined in [`parrot_tools.computer.models`](../summaries/mod:parrot_tools.computer.models.md).

```python
class TaskResult(BaseModel)
```

Result of a single task execution.

Captures whether the task succeeded, any screenshots taken during
execution, optionally extracted data, and the final URL.

Attributes:
    task_name: Name of the task that was executed.
    success: Whether the task completed without errors.
    screenshots: List of PNG bytes captured during the task.
    extracted_data: Optional structured data extracted during the task.
    error: Error message if the task failed; None on success.
    url: The page URL at the end of the task.
