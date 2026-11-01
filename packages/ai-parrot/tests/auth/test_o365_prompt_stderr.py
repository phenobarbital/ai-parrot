"""The O365 device-code prompt never touches stdout (AC-13)."""

from parrot.auth.oauth2.o365_devicecode_provider import _default_prompt_callback


def test_o365_prompt_goes_to_stderr(capsys) -> None:
    """Prompt output stays on stderr so stdout remains JSON-RPC-safe."""
    _default_prompt_callback({"message": "visit https://microsoft.com/devicelogin code ABC"})

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ABC" in captured.err
