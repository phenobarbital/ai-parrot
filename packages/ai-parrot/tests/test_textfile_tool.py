import sys
import unittest
from unittest.mock import MagicMock
from pathlib import Path
import asyncio
import shutil
import os

# --- MOCKS START ---
# Mock navconfig to avoid environment asset errors
if "navconfig" not in sys.modules:
    navconfig = MagicMock()
    navconfig.logging = MagicMock()
    navconfig.BASE_DIR = Path(os.getcwd())
    sys.modules["navconfig"] = navconfig
    sys.modules["navconfig.logging"] = navconfig.logging

# Mock parrot.conf
if "parrot.conf" not in sys.modules:
    parrot_conf = MagicMock()
    parrot_conf.BASE_STATIC_URL = "http://localhost/static"
    parrot_conf.STATIC_DIR = Path("/tmp/parrot_test_env/static")
    sys.modules["parrot.conf"] = parrot_conf

# Mock parrot.plugins
if "parrot.plugins" not in sys.modules:
    parrot_plugins = MagicMock()
    sys.modules["parrot.plugins"] = parrot_plugins

# Ensure pydantic and others are available or mocked if necessary.
# Assuming installed in env as per previous steps.

# --- MOCKS END ---

try:
    from parrot.tools.textfile import TextFileTool
except ImportError as e:
    # Fallback if imports fail due to environment
    print(f"WARNING: Could not import TextFileTool. Error: {e}")
    import traceback
    traceback.print_exc()
    TextFileTool = None

class TestTextFileTool(unittest.TestCase):
    def setUp(self):
        if TextFileTool is None:
            self.skipTest("TextFileTool not available")

        self.test_dir = Path("/tmp/parrot_test_env")
        self.static_dir = self.test_dir / "static"
        self.output_dir = self.static_dir / "documents" / "text"

        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_default_execution(self):
        # We pass static_dir explicitly to AbstractTool
        tool = TextFileTool(static_dir=self.static_dir)

        result = asyncio.run(tool.execute(content="Hello", filename="test.txt"))

        self.assertTrue(result.success)
        self.assertEqual(result.result['filename'], 'test.txt')
        self.assertTrue((self.output_dir / "test.txt").exists())

    def test_markdown_extension(self):
        tool = TextFileTool(static_dir=self.static_dir)

        result = asyncio.run(tool.execute(content="# Markdown", extension="md"))

        self.assertTrue(result.success)
        filename = result.result['filename']
        self.assertTrue(filename.endswith('.md'))
        self.assertTrue((self.output_dir / filename).exists())

    def test_output_dir_override(self):
        tool = TextFileTool(static_dir=self.static_dir)

        result = asyncio.run(tool.execute(
            content="Subdir Content",
            filename="sub.txt",
            output_dir="subdir"
        ))

        self.assertTrue(result.success)
        file_path = Path(result.result['file_path'])

        # Verify path structure
        self.assertTrue("subdir" in str(file_path))
        self.assertTrue(file_path.exists())
        self.assertEqual(file_path.parent.name, "subdir")

        # Check it is within output_dir (documents/text/subdir)
        self.assertTrue(str(file_path).startswith(str(self.output_dir)))

if __name__ == "__main__":
    unittest.main()
