"""Shared fixtures for Rust-backed splitter tests."""
import pytest

AUTOPAY_FAQ = (
    "Q: How do I access my AT&T Prepaid account?\n\n"
    "A: You can access and manage your AT&T Prepaid account by logging "
    "into your AT&T Prepaid account. Your AT&T Prepaid account allows "
    "you to see your data usage, change your plan, check your balance, "
    "enroll & set up AutoPay."
)

NON_ASCII_TEXT = (
    "Café — naïve résumé. ✨ "
    "El niño jugó en la peña con su mamá. "
    "東京で寿司を食べた。 " * 10
)


def _no_mid_word(chunk: str, full_text: str) -> bool:
    """A chunk respects word boundaries when its first and last
    characters are either at the start/end of the source text or are
    bordered by whitespace in the source.
    """
    start = full_text.find(chunk)
    if start == -1:
        return False
    end = start + len(chunk)
    starts_clean = start == 0 or full_text[start - 1].isspace()
    ends_clean = (
        end == len(full_text)
        or full_text[end].isspace()
        or chunk[-1] in ".!?,;:"
    )
    return starts_clean and ends_clean


@pytest.fixture
def autopay_text() -> str:
    return AUTOPAY_FAQ


@pytest.fixture
def non_ascii_text() -> str:
    return NON_ASCII_TEXT


@pytest.fixture
def no_mid_word():
    return _no_mid_word
