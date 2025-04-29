import urllib.parse
from langchain.tools import BaseTool


class GammaLink(BaseTool):
    """Generate a link to Gamma.app with the provided text."""
    name: str = "gamma_link"
    description: str = (
        "Generate a Link to Gamma.App to be used as presentation."
        " This tool is useful for creating URLs for presentations in Gamma.app."
    )

    def _run(self, query: str) -> dict:
        """
        Generate a link to Gamma.app with the provided text.

        Args:
            text (str): The text to be included in the Gamma link.

        Returns:
            str: The Gamma link containing the provided text.
        """
        base_url = "https://gamma.app"
        encoded_text = urllib.parse.quote(query)
        return {
            "url": f"{base_url}/create?content={encoded_text}",
            "text": query
        }
