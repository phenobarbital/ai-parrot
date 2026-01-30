import ast
import os
from pathlib import Path

def generate_init_docs(directory):
    """
    Scans a directory for __init__.py files and ensures they have:
    1. A module docstring.
    2. An __all__ definition based on imports.
    """
    init_path = Path(directory) / "__init__.py"
    if not init_path.exists():
        return

    with open(init_path, "r") as f:
        tree = ast.parse(f.read())

    # Check for existing docstring
    has_docstring = ast.get_docstring(tree) is not None
    
    # Analyze imports to suggest __all__
    exports = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            # from .module import Class
            for alias in node.names:
                exports.append(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            # Check if __all__ is already defined
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    print(f"✅ {init_path} already has __all__ defined.")
                    return

    if not exports:
        print(f"ℹ️ {init_path} has no obvious exports.")
        return

    # If missing, we suggest the fix (AI can read this output and apply it)
    print(f"--- SUGGESTION FOR {init_path} ---")
    if not has_docstring:
        print(f'"""\nPackage initialization for {directory.name}.\n\nExposes:\n' + 
              '\n'.join([f"    - {e}" for e in exports]) + '\n"""\n')
    
    print(f'__all__ = {exports}')
    print("-----------------------------------")

if __name__ == "__main__":
    import sys
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    generate_init_docs(target_dir)