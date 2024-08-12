import requests
from crewai_tools import BaseTool


class ValidateURLsTool(BaseTool):
    """Validate URLs Tool."""
    name: str = "Validate URLs"
    description: str = "Validate URLs for status code and response time."

    def _run(self, urls: list) -> dict:
        """Run the Validate URLs Tool."""
        valid_urls = []
        for url in urls:
            try:
                response = requests.head(url, allow_redirects=True)
                if response.status_code == 200:
                    valid_urls.append(url)
            except requests.RequestException:
                # Handle exceptions or log errors here
                continue
        return valid_urls
