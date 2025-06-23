from typing import Optional
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import numexpr as ne
import seaborn as sns
from datamodel.parsers.json import json_decoder, json_encoder  # noqa  pylint: disable=E0611
from navconfig import BASE_DIR
from navconfig.logging import logging
from langchain_experimental.tools.python.tool import PythonAstREPLTool
import parrot.bots.tools as parrot_tools



class PythonREPLTool(PythonAstREPLTool):
    """
    Python REPL Tool with:
    - Pre-loaded data science libraries: pandas (pd), numpy (np), matplotlib.pyplot (plt), seaborn (sns)
    - Helper functions from parrot.bots.tools under `parrot_tools`
    - An `execution_results` dict for capturing intermediate results
    - A `report_directory` Path for saving outputs
    - An extended JSON encoder/decoder based on orjson (`extended_json`)

    Use `extended_json.dumps(obj)` / `extended_json.loads(bytes)`
    instead of the standard `json` library for better performance.
    """
    name: str = "python_repl_ast"
    description: str = (
        "A Python shell. Use this to execute python commands. "
        "Input should be a valid python command. "
        "When using this tool, sometimes output is abbreviated - "
        "make sure it does not look abbreviated before using it in your answer."
        "There are several pre-loaded libraries available: "
        "pandas (pd), numpy (np), matplotlib.pyplot (plt), seaborn (sns), "
        "An `execution_results` dict for capturing intermediate results, "
        "A `report_directory` Path for saving outputs, "
        "and an extended JSON encoder/decoder based on orjson (`extended_json`). "
        "Use `extended_json.dumps(obj)` / `extended_json.loads(bytes)` "
        "instead of the standard `json` library for better performance. "
        "You can also use the `quick_eda`, `generate_eda_report`, "
        "and helper functions from parrot.bots.tools under `parrot_tools`."
    )
    _bootstrapped = False
    setup_code: str = ''
    logger: logging.Logger = None
    _default_setup_code = """
# Ensure essential libraries are imported
from parrot.bots.tools import (
    quick_eda,
    generate_eda_report,
    list_available_dataframes,
    create_plot,
    generate_pdf_from_html
)

# (You could switch this to a logger call if your REPL captures it)
print(f"Pandas version: {pd.__version__}")
"""
    def __init__(
        self,
        locals: Optional[dict] = None,
        globals: Optional[dict] = None,
        report_dir: Optional[Path] = None,
        plt_style: str = 'seaborn-v0_8-whitegrid',
        palette: str = 'Set2',
        setup_code: Optional[str] = None,
        **kwargs
    ):
        locals = locals or {}
        # Initialize locals with essential libraries and tools
        if not isinstance(locals, dict):
            raise TypeError("locals must be a dictionary")
        locals.update({
            'pd': pd,
            'np': np,
            'plt': plt,
            'sns': sns,
            'ne': ne,
            'json_encoder': json_encoder,
            'json_decoder': json_decoder,
            'extended_json': {
                'dumps': json_encoder,
                'loads': json_decoder,
            },
            'quick_eda': parrot_tools.quick_eda,
            'generate_eda_report': parrot_tools.generate_eda_report,
            'list_available_dataframes': parrot_tools.list_available_dataframes,
            'parrot_tools': parrot_tools,
        })
        # Set the report directory to the user-provided path or default
        report_dir = report_dir or BASE_DIR.joinpath('static', 'reports')
        # Ensure the report directory exists
        if not report_dir.exists():
            report_dir.mkdir(parents=True, exist_ok=True)
        # Add the report directory to locals
        locals['report_directory'] = report_dir
        # Initialize execution results
        locals['execution_results'] = {}
        super().__init__(locals=locals, globals=globals or {}, verbose=True, **kwargs)
        # Choose between the user‐provided or the default bootstrap snippet
        self.setup_code = setup_code or self._default_setup_code
        # Mirror locals into globals so user code can see everything
        self.globals = self.locals
        self.logger = logging.getLogger(__name__)
        self.logger.info("Python REPL Tool initialized.")
        self._bootstrap(plt_style, palette)

    def _bootstrap(self, plt_style: str, palette: str):
        if PythonREPLTool._bootstrapped:
            return
        self.logger.info("Running REPL bootstrap code…")
        try:
            # .run() is the method that actually executes code in the AST-based REPL
            self.run(self.setup_code)
        except Exception as e:
            self.logger.error("Error during REPL bootstrap", exc_info=e)
        try:
            plt.style.use(plt_style)
            sns.set_palette(palette)
            self.logger.debug(f"Pandas version: {pd.__version__}")
        except Exception as e:
            self.logger.error("Error during REPL bootstrap", exc_info=e)
        PythonREPLTool._bootstrapped = True
