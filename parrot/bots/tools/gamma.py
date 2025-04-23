import urllib.parse


def gamma_link(text: str) -> str:
    """
    Generate a link to Gamma.app with the provided text.

    Args:
        text (str): The text to be included in the Gamma link.

    Returns:
        str: The Gamma link containing the provided text.
    """
    base_url = "https://gamma.app"
    encoded_text = urllib.parse.quote(text)
    return f"{base_url}/create?content={encoded_text}"
