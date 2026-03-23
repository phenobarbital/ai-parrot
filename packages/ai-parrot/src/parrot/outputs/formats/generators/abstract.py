from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import pandas as pd

class AbstractAppGenerator(ABC):
    """
    Abstract base class for Application Generators.
    Handles payload extraction and defines the interface for generation.
    """

    def __init__(self, response: Any):
        self.response = response
        self.payload = self._extract_payload(response)

    def _extract_payload(self, response: Any) -> Dict[str, Any]:
        """
        Extract and normalize the payload from the Agent Response.
        Can be overridden by subclasses for specific needs.
        """
        payload = {
            "input": getattr(response, "input", "No query provided"),
            "explanation": "",
            "data": pd.DataFrame(),
            "code": None
        }

        # 1. Extract Explanation
        output = getattr(response, "output", "")
        if hasattr(output, "explanation"):
            payload["explanation"] = output.explanation
        elif hasattr(output, "response"):
            payload["explanation"] = output.response
        elif isinstance(output, str):
            payload["explanation"] = output

        # 2. Extract Data
        if hasattr(output, "to_dataframe"):
            payload["data"] = output.to_dataframe()
        elif hasattr(output, "data") and output.data is not None:
            payload["data"] = pd.DataFrame(output.data)
        elif hasattr(response, "data") and response.data is not None:
            if isinstance(response.data, pd.DataFrame):
                payload["data"] = response.data
            else:
                payload["data"] = pd.DataFrame(response.data)

        # 3. Extract Code
        if hasattr(output, "code") and output.code:
            payload["code"] = output.code
        elif hasattr(response, "code") and response.code:
            payload["code"] = response.code

        return payload

    @abstractmethod
    def generate(self) -> Any:
        """
        Generate the application output.
        Returns source code string (for web apps) or Renderable (for terminal).
        """
        pass
