"""
Executable Python REPL Tool.
"""
import io
import base64
import json
import matplotlib.pyplot as plt
from langchain_experimental.tools.python.tool import PythonAstREPLTool


class ExecutablePythonREPLTool(PythonAstREPLTool):
    """
    Executable Python REPL Tool.
    """
    def execute_code(self, code: str) -> str:
        """
        Execute the provided Python code and return the output.

        Args:
            code (str): The Python code to execute.

        Returns:
            str: The output of the executed code.
        """
        try:
            # Set up a namespace for execution
            namespace = {}
            exec(code, namespace)

            # Check if a plot was created
            if 'plt' in namespace:
                buf = io.BytesIO()
                plt.savefig(buf, format='png')
                plt.close()
                buf.seek(0)
                # Encode the image in base64
                # Encode the image in base64
                img_str = base64.b64encode(buf.read()).decode('utf-8')

                # Prepare the JSON output
                result = {
                    "image": {
                        "format": "png",
                        "base64": img_str
                    }
                }
                # Return both the code and the JSON result
                return f"**Code Executed**:\n```python\n{code}\n```\n\n**Result**:\n{json.dumps(result)}"
            else:
                return f"**Code Executed**:\n```python\n{code}\n```\n\n"

        except Exception as e:
            return f"Error executing code: {e}"

    def __call__(self, code: str) -> str:
        return self.execute_code(code)
