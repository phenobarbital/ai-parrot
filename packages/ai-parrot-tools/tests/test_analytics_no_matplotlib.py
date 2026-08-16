"""FEAT-423 (TASK-2222): analytics tools must not import matplotlib/seaborn."""
import ast
from pathlib import Path

TOOLS_SRC = Path(__file__).parent.parent / "src" / "parrot_tools"


def _imports_module(filepath: Path, module_name: str) -> bool:
    """Check if a Python file imports ``module_name`` (or a submodule of it)."""
    tree = ast.parse(filepath.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(module_name):
                    return True
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(module_name):
            return True
    return False


def _imports_matplotlib(filepath: Path) -> bool:
    """Check if a Python file imports matplotlib."""
    return _imports_module(filepath, "matplotlib")


def _imports_seaborn(filepath: Path) -> bool:
    """Check if a Python file imports seaborn."""
    return _imports_module(filepath, "seaborn")


def test_quickeda_no_matplotlib():
    assert not _imports_matplotlib(TOOLS_SRC / "quickeda.py")


def test_quickeda_no_seaborn():
    assert not _imports_seaborn(TOOLS_SRC / "quickeda.py")


def test_correlationanalysis_no_matplotlib():
    assert not _imports_matplotlib(TOOLS_SRC / "correlationanalysis.py")


def test_correlationanalysis_no_seaborn():
    assert not _imports_seaborn(TOOLS_SRC / "correlationanalysis.py")


def test_seasonaldetection_no_matplotlib():
    assert not _imports_matplotlib(TOOLS_SRC / "seasonaldetection.py")


def test_sandboxtool_no_matplotlib_import():
    assert not _imports_matplotlib(TOOLS_SRC / "sandboxtool.py")


def test_sandboxtool_no_matplotlib_default():
    content = (TOOLS_SRC / "sandboxtool.py").read_text()
    # Check the default pip_packages list does not contain matplotlib/seaborn
    assert '"matplotlib"' not in content.split("pip_packages: List[str] = field(default_factory=lambda: [")[1].split("])")[0]


def test_sandboxtool_no_matplotlib_in_analysis_templates():
    """The correlation/distribution analysis_code templates must not
    reference matplotlib/seaborn (they'd ImportError since matplotlib is no
    longer a default pip_packages entry)."""
    content = (TOOLS_SRC / "sandboxtool.py").read_text()
    analysis_code_block = content.split('analysis_code = {')[1].split("code = analysis_code.get")[0]
    assert "matplotlib" not in analysis_code_block
    assert "seaborn" not in analysis_code_block
