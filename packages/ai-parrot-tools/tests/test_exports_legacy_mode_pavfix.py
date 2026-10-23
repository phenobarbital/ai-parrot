"""PA-V2 review fix 8 (PA-11): a host that does NOT set ``app[STUDIO_EXPORTS_STORE_ONLY]`` sees the previous export tools.

Mode OFF is the default: the LLM schemas keep their path / file-name / overwrite / template-path arguments, those
arguments are honoured, templates may be paths, the ``artifact_store`` parameter is not server-managed and a Studio-scoped
call without a store is not refused. The same tools in mode ON are covered by ``test_export_tools_pa11.py``.
"""
from __future__ import annotations

import pandas as pd
import pytest

import parrot.tools.exports_mode as exports_mode

from .test_export_tools_pa11 import (  # noqa: F401  (fixtures + factories of the mode-ON suite)
    FACTORIES,
    _rows,
    sandbox,
    store,
    studio_scope,
)

LEGACY_ARGS = {
    "excel": {"output_dir", "output_filename", "overwrite_existing", "template_file"},
    "data_frame_to_excel": {"output_dir", "output_filename", "overwrite_existing"},
    "csv_export": {"output_dir", "output_filename", "overwrite_existing"},
    "data_frame_to_csv": {"output_dir", "output_filename", "overwrite_existing"},
    "ms_word": {"output_dir", "output_filename", "overwrite_existing", "docx_template"},
    "power_point": {"output_dir", "output_filename", "overwrite_existing", "pptx_template", "pptx_template_path"},
    "pdf_print": {"stylesheets", "template_name"},
    "df_to_html": {"filename"},
}


@pytest.fixture(autouse=True)
def _mode(request):
    exports_mode.configure(False)
    yield
    exports_mode.configure(False)


@pytest.mark.parametrize("name", sorted(LEGACY_ARGS))
def test_off_keeps_the_full_schema_and_on_hides_the_path_arguments(name, sandbox, store):
    tool, _ = FACTORIES[name](sandbox, store)
    off = set(tool.get_schema()["parameters"]["properties"])
    assert LEGACY_ARGS[name] <= off, LEGACY_ARGS[name] - off
    assert not type(tool).server_managed_params                       # artifact_store is not server-managed
    exports_mode.configure(True)
    on = set(tool.get_schema()["parameters"]["properties"])
    hidden = LEGACY_ARGS[name] & tool.studio_hidden_args
    assert hidden and not on & hidden and "artifact_store" in type(tool).server_managed_params


async def test_off_power_bi_keeps_its_export_paths():
    from parrot_tools.powerbi import PowerBIQueryTool

    props = set(PowerBIQueryTool().get_schema()["parameters"]["properties"])
    assert {"export_csv_path", "parquet_path"} <= props


async def test_off_a_custom_output_dir_and_file_name_are_honoured(sandbox):
    from parrot_tools.csv_export import CSVExportTool

    tool = CSVExportTool(output_dir=sandbox.out)
    custom = sandbox.out / "custom"
    result = await tool.execute(content=_rows(), output_dir=str(custom), output_filename="mine")
    payload = result.result if hasattr(result, "result") and isinstance(result.result, dict) else result
    path = payload["metadata"]["file_path"]
    assert path.startswith(str(custom)) and "mine" in path and "url" not in payload["metadata"]


async def test_off_df_to_html_saves_the_named_file(sandbox):
    from parrot_tools.dftohtml import DfToHtmlTool

    tool = DfToHtmlTool(output_dir=sandbox.out)
    result = await tool._execute(dataframe=pd.DataFrame(_rows()), filename="report")
    assert result["file_path"].endswith("report.html") and (sandbox.out / "report.html").exists()


async def test_off_a_template_may_be_a_path_and_on_it_may_not(sandbox):
    from parrot_tools.excel import ExcelArgs

    assert ExcelArgs(content=_rows(), template_file="/abs/t.xlsx").template_file == "/abs/t.xlsx"
    exports_mode.configure(True)
    with pytest.raises(ValueError):
        ExcelArgs(content=_rows(), template_file="/abs/t.xlsx")


async def test_off_a_studio_call_without_a_store_is_not_refused(sandbox):
    from parrot_tools.csv_export import CSVExportTool

    tool = CSVExportTool(output_dir=sandbox.out)
    with studio_scope("acme"):
        result = await tool.execute(content=_rows())
    assert getattr(result, "success", True) is not False, result
    assert any(sandbox.out.glob("*.csv"))                              # the legacy local file, not a refusal


async def test_on_the_same_call_drops_the_hidden_arguments(sandbox, store):
    from parrot_tools.csv_export import CSVExportTool

    exports_mode.configure(True)
    tool = CSVExportTool(output_dir=sandbox.out, artifact_store=store)
    with studio_scope("acme"):
        result = await tool.execute(content=_rows(), output_dir=str(sandbox.root / "evil"), output_filename="x")
    assert getattr(result, "success", True) is not False, result
    assert not (sandbox.root / "evil").exists() and not any(sandbox.out.glob("*.csv"))
