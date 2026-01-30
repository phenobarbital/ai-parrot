import sys
import os

# Add project root to path
sys.path.insert(0, os.getcwd())

try:
    from parrot.services.mcp.simple import SimpleMCPServer
    print("Import successful")
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
