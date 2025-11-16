# 🚀 Quick Start Guide

Get up and running with AgentCrew Builder in 5 minutes!

## Prerequisites

- Node.js 18+ ([Download](https://nodejs.org/))
- Python 3.11+ ([Download](https://www.python.org/))
- npm (comes with Node.js)

## Setup (Option 1: Local Development)

### 1. Run Setup Script

```bash
chmod +x setup.sh
./setup.sh
```

### 2. Start Backend

```bash
python3 backend_example.py
```

The API will start at `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

### 3. Start Frontend (in a new terminal)

```bash
npm run dev
```

The app will start at `http://localhost:5173`

## Setup (Option 2: Docker)

```bash
docker-compose up
```

This starts both frontend and backend automatically!

## Your First Workflow

### Step 1: Create a Research Pipeline

1. **Open** `http://localhost:5173` in your browser

2. **Set crew metadata** in the toolbar:
   - Name: `research_pipeline`
   - Description: `Sequential pipeline for research and writing`

3. **Add your first agent** - Click "Add Agent" button
   - Agent ID: `researcher`
   - Name: `Research Agent`
   - Model: `gemini-2.5-pro`
   - Temperature: `0.7`
   - Tools: Check ✅ `GoogleSearchTool`
   - System Prompt:
     ```
     You are an expert AI researcher. Gather comprehensive 
     information on the given topic and provide detailed findings.
     ```

4. **Add second agent** - Click "Add Agent" again
   - Agent ID: `analyzer`
   - Name: `Analysis Agent`
   - Model: `gemini-2.5-pro`
   - Temperature: `0.6`
   - System Prompt:
     ```
     You are a data analyst. Analyze the research findings 
     and extract key insights.
     ```

5. **Add third agent**
   - Agent ID: `writer`
   - Name: `Writer Agent`
   - Model: `gemini-2.5-pro`
   - Temperature: `0.8`
   - System Prompt:
     ```
     You are a technical writer. Create a well-structured 
     report from the analysis.
     ```

### Step 2: Connect Agents

1. **Drag** from the bottom handle of `Research Agent`
2. **Drop** onto the top handle of `Analysis Agent`
3. **Connect** `Analysis Agent` to `Writer Agent`

Your workflow: `Researcher → Analyzer → Writer`

### Step 3: Export and Use

1. **Click** "Export JSON" button
2. **Save** the file as `research_pipeline.json`

Your workflow is now ready to use!

## Using Your Workflow

### Option A: Upload via API

```bash
curl -X POST http://localhost:8000/api/crews/upload \
  -F "file=@research_pipeline.json"
```

### Option B: Run with Python

```python
import requests

# Upload crew
with open('research_pipeline.json', 'rb') as f:
    response = requests.post(
        'http://localhost:8000/api/crews/upload',
        files={'file': f}
    )

print(response.json())

# Run crew
result = requests.post(
    'http://localhost:8000/api/crews/research_pipeline/run',
    json={
        'task': 'Research the latest trends in AI for 2025'
    }
)

print(result.json())
```

### Option C: Direct Integration with AI-parrot

```python
from ai_parrot import AgentCrew
import json

# Load your exported configuration
with open('research_pipeline.json', 'r') as f:
    crew_config = json.load(f)

# Create crew (assuming you have from_config method)
crew = AgentCrew.from_config(crew_config)

# Run it!
result = crew.run(task="Research the latest trends in AI for 2025")
print(result)
```

## Example Workflows

### 📝 Content Creation Pipeline

```
[Topic Researcher] → [Outline Creator] → [Content Writer] → [Editor]
```

### 🔍 Data Analysis Pipeline

```
[Data Collector] → [Data Cleaner] → [Analyzer] → [Visualizer] → [Reporter]
```

### 🤖 Customer Support

```
[Question Classifier] → [Knowledge Searcher] → [Response Generator] → [Quality Checker]
```

### 💼 Business Intelligence

```
[Market Researcher] → [Competitor Analyzer] → [Trend Analyst] → [Strategy Advisor]
```

## Tips & Tricks

### 🎨 Visual Design
- **Arrange nodes** by dragging them around
- **Zoom** using mouse wheel
- **Pan** by dragging the background
- **Use MiniMap** for navigation (bottom-right)

### ⚙️ Configuration
- **Form mode**: Easy configuration with guided fields
- **JSON mode**: Advanced users can edit raw JSON
- **Switch freely** between modes without losing data

### 🔗 Connections
- **Sequential flow**: Connect agents in order
- **Parallel branches**: Multiple agents can start without connections
- **Execution order**: Determined by topological sort

### 📤 Export
- **Auto-download**: Clicking Export downloads JSON immediately
- **Filename**: Named after your crew (e.g., `research_pipeline.json`)
- **Format**: Ready to use with AgentCrew API

## Common Issues

### Frontend not starting?
```bash
# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install
npm run dev
```

### Backend not starting?
```bash
# Reinstall Python dependencies
pip3 install --upgrade -r requirements.txt
python3 backend_example.py
```

### Agents not connecting?
- Ensure you drag from **bottom** handle (source)
- Drop on **top** handle (target)
- Check that handles are visible when hovering

### Export shows empty agents?
- Verify all required fields are filled:
  - Agent ID (unique)
  - Name
  - System Prompt
- Save configuration before exporting

## Next Steps

1. **Explore examples** in `/examples` directory
2. **Read full documentation** in `README.md`
3. **Integrate with your AI-parrot backend**
4. **Create complex workflows** with multiple branches
5. **Share your workflows** with the community!

## Getting Help

- 📖 [Full Documentation](README.md)
- 🐛 [Report Issues](https://github.com/your-repo/issues)
- 💬 [Community Discord](https://discord.gg/your-link)
- 📧 [Email Support](mailto:support@your-domain.com)

## What's Next?

- [ ] Try creating a parallel execution workflow
- [ ] Experiment with different models and temperatures
- [ ] Add custom tools to your agents
- [ ] Build a production-ready crew for your use case
- [ ] Contribute improvements to the project!

---

**Happy Building! 🦜**
