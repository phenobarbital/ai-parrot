from typing import Type, List
from pydantic import BaseModel, Field
from .base import WebAppGenerator


class HTMLApp(BaseModel):
    """Pydantic schema for HTML application output."""
    code: str = Field(description="Complete HTML code with embedded CSS and JS")
    title: str = Field(description="Page title")
    description: str = Field(description="App description")
    features: List[str] = Field(description="Key features implemented")


class HTMLGenerator(WebAppGenerator):
    """Generator for standalone HTML/CSS/JS applications."""

    def get_system_prompt(self) -> str:
        return """You are an expert web developer creating modern, self-contained HTML applications.

**User Requirements:**
{user_description}

**Technical Requirements:**
- Complete HTML5 document in a single file
- Embedded CSS using <style> tags
- Embedded JavaScript using <script> tags
- Vanilla JavaScript (ES6+) - no frameworks required
- Responsive design with mobile-first approach
- Cross-browser compatible (Chrome, Firefox, Safari, Edge)

**Libraries Available via CDN (if needed):**
- Chart.js for charts: https://cdn.jsdelivr.net/npm/chart.js
- Tailwind CSS: https://cdn.tailwindcss.com
- Alpine.js for reactivity: https://unpkg.com/alpinejs

**HTML Structure:**
1. <!DOCTYPE html> declaration
2. <html lang="en"> with proper lang attribute
3. <head> with meta tags, title, and styles
4. <body> with semantic HTML5 elements
5. <script> section at the end

**CSS Standards:**
- Modern CSS with flexbox/grid layouts
- CSS custom properties for theming
- Smooth transitions and animations
- Mobile-responsive with media queries
- Clean, maintainable styling

**JavaScript Standards:**
- ES6+ syntax (const, let, arrow functions)
- Event delegation for better performance
- Error handling with try-catch
- Local storage for data persistence (if appropriate)
- Form validation
- Loading states for async operations

**Design Requirements:**
- Modern, clean aesthetic
- Intuitive user interface
- Loading indicators for async operations
- Error messages for validation
- Smooth animations and transitions
- Accessible (ARIA labels, keyboard navigation)

Generate a complete, production-ready HTML application."""

    def get_output_schema(self) -> Type[BaseModel]:
        return HTMLApp

    def get_examples(self) -> str:
        return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Task Manager</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        :root {
            --primary: #3b82f6;
            --primary-dark: #2563eb;
            --bg: #f9fafb;
            --card: #ffffff;
            --text: #1f2937;
            --text-light: #6b7280;
            --border: #e5e7eb;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }

        .container {
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem;
        }

        .header {
            background: var(--card);
            padding: 2rem;
            border-radius: 1rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 2rem;
        }

        h1 {
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }

        .input-group {
            display: flex;
            gap: 1rem;
            margin-top: 1rem;
        }

        input {
            flex: 1;
            padding: 0.75rem;
            border: 1px solid var(--border);
            border-radius: 0.5rem;
            font-size: 1rem;
        }

        button {
            padding: 0.75rem 1.5rem;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 0.5rem;
            font-size: 1rem;
            cursor: pointer;
            transition: background 0.3s;
        }

        button:hover {
            background: var(--primary-dark);
        }

        .task-list {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }

        .task {
            background: var(--card);
            padding: 1rem;
            border-radius: 0.5rem;
            display: flex;
            align-items: center;
            gap: 1rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            transition: transform 0.2s;
        }

        .task:hover {
            transform: translateY(-2px);
        }

        .task.completed {
            opacity: 0.6;
            text-decoration: line-through;
        }

        @media (max-width: 640px) {
            .container {
                padding: 1rem;
            }
            .input-group {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📝 Task Manager</h1>
            <p style="color: var(--text-light)">Manage your daily tasks efficiently</p>

            <div class="input-group">
                <input
                    type="text"
                    id="taskInput"
                    placeholder="Enter a new task..."
                    aria-label="New task input"
                >
                <button onclick="addTask()" aria-label="Add task">
                    Add Task
                </button>
            </div>
        </div>

        <div class="task-list" id="taskList"></div>
    </div>

    <script>
        // Load tasks from localStorage
        let tasks = JSON.parse(localStorage.getItem('tasks') || '[]');

        // Initialize on page load
        document.addEventListener('DOMContentLoaded', () => {
            renderTasks();

            // Allow Enter key to add task
            document.getElementById('taskInput').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') addTask();
            });
        });

        function addTask() {
            const input = document.getElementById('taskInput');
            const text = input.value.trim();

            if (!text) {
                alert('Please enter a task');
                return;
            }

            tasks.push({
                id: Date.now(),
                text: text,
                completed: false,
                createdAt: new Date().toISOString()
            });

            saveTasks();
            renderTasks();
            input.value = '';
            input.focus();
        }

        function toggleTask(id) {
            tasks = tasks.map(task =>
                task.id === id ? {...task, completed: !task.completed} : task
            );
            saveTasks();
            renderTasks();
        }

        function deleteTask(id) {
            tasks = tasks.filter(task => task.id !== id);
            saveTasks();
            renderTasks();
        }

        function saveTasks() {
            localStorage.setItem('tasks', JSON.stringify(tasks));
        }

        function renderTasks() {
            const listEl = document.getElementById('taskList');

            if (tasks.length === 0) {
                listEl.innerHTML = '<p style="text-align:center;color:var(--text-light)">No tasks yet. Add one above!</p>';
                return;
            }

            listEl.innerHTML = tasks.map(task => `
                <div class="task ${task.completed ? 'completed' : ''}">
                    <input
                        type="checkbox"
                        ${task.completed ? 'checked' : ''}
                        onchange="toggleTask(${task.id})"
                        aria-label="Toggle task completion"
                    >
                    <span style="flex:1">${task.text}</span>
                    <button
                        onclick="deleteTask(${task.id})"
                        style="background:#ef4444;padding:0.5rem 1rem"
                        aria-label="Delete task"
                    >
                        Delete
                    </button>
                </div>
            `).join('');
        }
    </script>
</body>
</html>
'''
