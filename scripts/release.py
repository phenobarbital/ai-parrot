import argparse
import re
import subprocess
import sys
from pathlib import Path

# --- CONFIGURATION ---
VERSION_PY_PATH = Path("parrot/version.py") 
CARGO_TOML_PATH = Path("yaml-rs/Cargo.toml") 
# ---------------------

def get_python_version():
    """Reads version from version.py as the SOURCE OF TRUTH."""
    if not VERSION_PY_PATH.exists():
        sys.exit(f"Error: {VERSION_PY_PATH} not found.")
        
    with open(VERSION_PY_PATH, "r") as f:
        content = f.read()
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        sys.exit("Error: Could not find __version__ in version.py")
    return match.group(1)

def bump_version(current_ver, part):
    major, minor, patch = map(int, current_ver.split('.'))
    if part == "major":
        return f"{major + 1}.0.0"
    elif part == "minor":
        return f"{major}.{minor + 1}.0"
    else: # patch
        return f"{major}.{minor}.{patch + 1}"

def update_python(new_ver):
    """Updates the master version in Python."""
    with open(VERSION_PY_PATH, "r") as f:
        content = f.read()
    
    new_content = re.sub(
        r'(__version__\s*=\s*")[^"]+(")', 
        f'\\g<1>{new_ver}\\g<2>', 
        content
    )
    
    with open(VERSION_PY_PATH, "w") as f:
        f.write(new_content)
    print(f"Updated {VERSION_PY_PATH} to {new_ver}")

def sync_cargo(new_ver):
    """Syncs the follower version in Cargo.toml."""
    if not CARGO_TOML_PATH.exists():
        print(f"Warning: {CARGO_TOML_PATH} not found. Skipping Cargo sync.")
        return

    with open(CARGO_TOML_PATH, "r") as f:
        content = f.read()
    
    # Updates version = "x.y.z" at the top level
    new_content = re.sub(
        r'(^version\s*=\s*")[^"]+(")', 
        f'\\g<1>{new_ver}\\g<2>', 
        content, 
        count=1, 
        flags=re.MULTILINE
    )
    
    with open(CARGO_TOML_PATH, "w") as f:
        f.write(new_content)
    print(f"Synced {CARGO_TOML_PATH} to {new_ver}")

def run_git(new_ver):
    files_to_add = [str(VERSION_PY_PATH)]
    if CARGO_TOML_PATH.exists():
        files_to_add.append(str(CARGO_TOML_PATH))
        
    subprocess.run(["git", "add"] + files_to_add, check=True)
    subprocess.run(["git", "commit", "-m", f"chore: release v{new_ver}"], check=True)
    print(f"✅ Bumped to v{new_ver} and committed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("part", choices=["major", "minor", "patch"], default="patch")
    args = parser.parse_args()

    current = get_python_version()
    new_ver = bump_version(current, args.part)
    
    print(f"Bumping {current} -> {new_ver}...")
    update_python(new_ver)
    sync_cargo(new_ver)
    run_git(new_ver)