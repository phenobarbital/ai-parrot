import sys
import os
import re
from pathlib import Path

# Ultra-simple template expansion script
def generate_tool(tool_name):
    # Robustly find the template relative to this script
    script_dir = Path(__file__).resolve().parent
    skill_root = script_dir.parent
    template_path = skill_root / "resources" / "ToolTemplate.py.hbs"
    
    # Calculate target directory (parrot/tools)
    # This assumes the skill is located deep in the repo tree, 
    # so we need to find the project root.
    # For this environment, we know it's at /home/jesuslara/proyectos/navigator/ai-parrot/parrot/tools
    # But let's try to be relative if possible, or assume running from root
    
    # Strategy: Find 'parrot' directory
    current = script_dir
    project_root = None
    while current != current.parent:
        if (current / "parrot").exists() and (current / "parrot").is_dir():
            project_root = current
            break
        current = current.parent
        
    if not project_root:
        # Fallback to current working directory if parrot not found
        project_root = Path(os.getcwd())
        
    tools_dir = project_root / "parrot" / "tools"
    if not tools_dir.exists():
        # if parrot/tools doesn't exist, maybe we are just in a random place. 
        # Fallback to current dir? Or error?
        # The user request implies creating tools FOR ai-parrot.
        print(f"Warning: Could not find parrot/tools at {tools_dir}. Using current directory.")
        tools_dir = Path(os.getcwd())

    # CamelCase to snake_case
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', tool_name)
    snake_case = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    
    output_filename = f"{snake_case}.py"
    target_path = tools_dir / output_filename
    
    if target_path.exists():
        print(f"Error: {target_path} already exists.")
        sys.exit(1)

    if not template_path.exists():
        print(f"Error: Template not found at {template_path}")
        sys.exit(1)

    with open(template_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace variables
    content = content.replace("{{ToolName}}", tool_name)
    content = content.replace("{{tool_name}}", snake_case)
    content = content.replace("{{toolDescription}}", f"Tool functionality for {tool_name}")

    with open(target_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Successfully generated {target_path}")
    print(f"Class: {tool_name}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scaffold_tool.py <ToolName>")
        sys.exit(1)
    
    generate_tool(sys.argv[1])
