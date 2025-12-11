#!/usr/bin/env python
"""
Debug version of test script to see sys.path state at different points
"""
import sys

print("=" * 80)
print("Testing import order issue fix - DEBUG VERSION")
print("=" * 80)

print("\n0. Initial sys.path (first 5):")
for i, p in enumerate(sys.path[:5]):
    print(f"   [{i}] {p}")

print("\n1. Importing from parrot.bots.data...")
from parrot.bots.data import PandasAgent, PANDAS_SYSTEM_PROMPT, TOOL_INSTRUCTION_PROMPT
print("   ✅ Successfully imported from parrot.bots.data")

print("\n2. sys.path after importing parrot.bots.data (first 10):")
for i, p in enumerate(sys.path[:10]):
    print(f"   [{i}] {p}")

print("\n3. Looking for agents and plugins dirs in sys.path:")
for i, p in enumerate(sys.path):
    if 'agents' in p or 'plugins' in p:
        print(f"   [{i}] {p}")

print("\n4. Importing from agents.troc...")
try:
    # Show which file would be found
    import importlib.util
    spec = importlib.util.find_spec("agents.troc")
    if spec and spec.origin:
        print(f"   Found agents.troc at: {spec.origin}")
    
    from agents.troc import TROCFinance
    print(f"   ✅ Successfully imported TROCFinance from agents.troc")
    print(f"   TROCFinance class: {TROCFinance}")
except ImportError as e:
    print(f"   ❌ Failed to import: {e}")
    raise

print("\n" + "=" * 80)
print("All imports successful! ✅")
print("=" * 80)
