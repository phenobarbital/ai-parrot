#!/usr/bin/env python
"""
Test script to reproduce the import order issue.

This script:
1. First imports from parrot.bots.data (which loads parrot.conf)
2. Then imports from agents.troc

Expected behavior BEFORE fix:
  - Import fails because PLUGINS_DIR is in sys.path but AGENTS_DIR is not

Expected behavior AFTER fix:
  - Import succeeds because AGENTS_DIR is added to sys.path in parrot.conf
"""

print("=" * 80)
print("Testing import order issue fix")
print("=" * 80)

print("\n1. Importing from parrot.bots.data...")
from parrot.bots.data import PandasAgent, PANDAS_SYSTEM_PROMPT, TOOL_INSTRUCTION_PROMPT
print("   ✅ Successfully imported from parrot.bots.data")

print("\n2. Importing from agents.troc...")
try:
    from agents.troc import TROCFinance
    print("   ✅ Successfully imported TROCFinance from agents.troc")
    print(f"   TROCFinance class: {TROCFinance}")
except ImportError as e:
    print(f"   ❌ Failed to import: {e}")
    raise

print("\n" + "=" * 80)
print("All imports successful! ✅")
print("=" * 80)
