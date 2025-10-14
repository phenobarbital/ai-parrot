# AgentCrew Builder - Visual Workflow Designer

A visual workflow builder for AI-parrot's AgentCrew, built with SvelteFlow. Create, configure, and orchestrate AI agent pipelines through an intuitive drag-and-drop interface.

## Features

✨ **Visual Workflow Design**
- Drag-and-drop agent nodes
- Visual connections representing execution flow
- Real-time workflow visualization

🎨 **Flexible Configuration**
- Form-based agent configuration
- JSON editor for advanced users
- Switch seamlessly between form and JSON modes

🤖 **Agent Management**
- Configure agent properties (ID, name, model, temperature)
- Add tools to agents (GoogleSearchTool, WebScraperTool, etc.)
- Define custom system prompts
- Support for multiple LLM models

📤 **Export & Integration**
- Export workflows as JSON
- Direct compatibility with AgentCrew API
- Sequential execution order based on visual connections

## Installation

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build
```

## Usage

### 1. Create a New Crew

1. **Set Crew Metadata**: In the toolbar, enter:
   - Crew name (e.g., "research_pipeline")
   - Description
   - Execution mode (currently supports sequential)

### 2. Add Agents

1. **Click "Add Agent"** in the toolbar
2. A new agent node appears on the canvas
3. **Click the node** to open the configuration panel

### 3. Configure Agents

#### Form Mode (Recommended for beginners)
- **Agent ID**: Unique identifier (e.g., "researcher")
- **Name**: Human-readable name (e.g., "Research Agent")
- **Model**: Select from available models
  - gemini-2.5-pro
  - gpt-4, gpt-3.5-turbo
  - claude-3-opus, claude-3-sonnet
  - claude-sonnet-4-5-20250929
- **Temperature**: 0.0 (deterministic) to 2.0 (creative)
- **Tools**: Check boxes for required tools
  - GoogleSearchTool
  - WebScraperTool
  - FileReaderTool
  - CalculatorTool
  - CodeInterpreterTool
- **System Prompt**: Define the agent's role and behavior

#### JSON Mode (Advanced)
Switch to JSON mode to edit the complete agent configuration:

```json
{
  "agent_id": "researcher",
  "name": "Research Agent",
  "agent_class": "Agent",
  "config": {
    "model": "gemini-2.5-pro",
    "temperature": 0.7
  },
  "tools": ["GoogleSearchTool"],
  "system_prompt": "You are an expert AI researcher..."
}
```

### 4. Connect Agents

1. **Drag from the bottom handle** of one agent node
2. **Connect to the top handle** of another agent
3. Connections define the **execution order** in sequential mode
4. The system uses **topological sorting** to determine the final order

### 5. Export Workflow

Click **"Export JSON"** to download your workflow as a JSON file ready for the AgentCrew API.

Example exported structure:
```json
{
  "name": "research_pipeline",
  "description": "Sequential pipeline for research and writing",
  "execution_mode": "sequential",
  "agents": [
    {
      "agent_id": "researcher",
      "name": "Research Agent",
      "agent_class": "Agent",
      "config": {
        "model": "gemini-2.5-pro",
        "temperature": 0.7
      },
      "tools": ["GoogleSearchTool"],
      "system_prompt": "You are an expert AI researcher."
    }
  ]
}
```

## Integration with Backend

### Option 1: Direct API Upload

```python
import requests

# Load exported JSON
with open('my_crew.json', 'r') as f:
    crew_config = json.load(f)

# Send to AgentCrew API
response = requests.post(
    'http://your-api/crews',
    json=crew_config
)
```

### Option 2: Python Integration

```python
from ai_parrot import AgentCrew

# Load exported JSON
with open('my_crew.json', 'r') as f:
    crew_config = json.load(f)

# Create crew from configuration
crew = AgentCrew.from_config(crew_config)

# Run the crew
result = crew.run(task="Your research task here")
```

## Architecture

```
agent-crew-builder/
├── src/
│   ├── components/
│   │   ├── AgentNode.svelte      # Custom agent node component
│   │   ├── ConfigPanel.svelte    # Configuration sidebar
│   │   └── Toolbar.svelte        # Top toolbar with actions
│   ├── stores/
│   │   └── crewStore.js          # State management & export logic
│   ├── App.svelte                # Main application
│   ├── main.js                   # Entry point
│   └── app.css                   # Global styles
├── index.html
├── package.json
└── vite.config.js
```

## Key Components

### CrewStore
Central state management using Svelte stores:
- **Node Management**: Add, update, delete agents
- **Edge Management**: Track connections between agents
- **Export Logic**: Convert visual flow to AgentCrew JSON format
- **Topological Sort**: Determine execution order from connections

### AgentNode
Custom SvelteFlow node representing an agent:
- Visual representation of agent properties
- Shows model, tools, and prompt preview
- Connection handles for workflow

### ConfigPanel
Sliding panel for agent configuration:
- Form mode with validation
- JSON editor with syntax checking
- Tool selection with checkboxes
- Real-time updates

## Execution Order

The builder uses **topological sorting** to determine agent execution order:

1. Build a directed graph from connections
2. Find nodes with no incoming edges (starting points)
3. Process nodes level by level
4. Disconnected nodes are added at the end

Example:
```
[Researcher] → [Analyzer] → [Writer]
     ↓
[Fact-Checker]
```

Execution order: `Researcher → Analyzer → Writer → Fact-Checker`

## Future Enhancements

- [ ] **Parallel Execution Mode**: Run agents concurrently
- [ ] **Hierarchical Mode**: Manager-worker patterns
- [ ] **Custom Tool Definition**: Create tools in the UI
- [ ] **Workflow Templates**: Pre-built agent patterns
- [ ] **Validation**: Real-time config validation
- [ ] **Import**: Load existing JSON workflows
- [ ] **Versioning**: Save multiple workflow versions
- [ ] **Testing**: Built-in workflow testing
- [ ] **Collaboration**: Multi-user editing
- [ ] **MCP Integration**: Model Context Protocol support

## Customization

### Adding New Models

Edit `ConfigPanel.svelte`:
```javascript
const models = [
  'gemini-2.5-pro',
  'your-new-model',
  // ... more models
];
```

### Adding New Tools

Edit `ConfigPanel.svelte`:
```javascript
const availableTools = [
  'GoogleSearchTool',
  'YourCustomTool',
  // ... more tools
];
```

### Custom Node Styling

Edit `AgentNode.svelte` styles to customize appearance:
```css
.agent-node {
  background: your-color;
  border: your-border;
  /* ... */
}
```

## Troubleshooting

### Connections Not Appearing
- Ensure you're dragging from source handle (bottom) to target handle (top)
- Check that both nodes exist and are properly rendered

### Export Returns Empty Agents
- Verify all agents have required fields (agent_id, name, system_prompt)
- Check that agents are properly saved after configuration

### Invalid JSON in Editor
- Use the built-in JSON validator
- Check for missing commas, quotes, or brackets
- Switch to form mode to see structured fields

## Contributing

Contributions welcome! Areas for improvement:
- Additional execution modes
- Enhanced validation
- Performance optimization
- Accessibility improvements
- Documentation

## License

[Your License Here]

## Credits

Built with:
- [Svelte](https://svelte.dev/) - Reactive framework
- [SvelteFlow](https://svelteflow.dev/) - Flow/node editor
- [Vite](https://vitejs.dev/) - Build tool
- [AI-parrot](https://github.com/your-repo) - Agent framework
