#!/bin/bash
# Helper script to run commands inside the virtual environment
set -e

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PATH="$PROJECT_ROOT/.venv"

if [ ! -d "$VENV_PATH" ]; then
    echo "Error: Virtual environment not found at $VENV_PATH"
    echo "Please run 'uv venv' to create it."
    exit 1
fi

# Activate the virtual environment
source "$VENV_PATH/bin/activate"

# execute the command
exec "$@"
