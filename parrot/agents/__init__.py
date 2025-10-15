"""
Parrot Agents - Core and Plugin Agents
"""
from parrot.plugins import setup_plugin_importer, dynamic_import_helper

setup_plugin_importer('parrot.agents', 'agents')

# Enable dynamic imports
def __getattr__(name):
    return dynamic_import_helper(__name__, name)
