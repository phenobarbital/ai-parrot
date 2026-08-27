"""Unit tests for regex-first `as_of` extraction (FEAT-449 TASK-2496)."""

from datetime import date

import pytest
from parrot_tools.legal.librarian.as_of import (
    AsOfExtraction,
    extract_as_of,
    regex_dates,
)


class Spy:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result

    async def __call__(self, prompt, *, structured_output):
        self.calls += 1
        return AsOfExtraction(as_of=self.result)


@pytest.mark.parametrize(
    "q,expected",
    [
        ("vigente a 2021-06-01", date(2021, 6, 1)),
        ("el 15/03/2020 qué decía", date(2020, 3, 15)),
        ("a 3 de Marzo de 2019", date(2019, 3, 3)),
        ("¿qué decía el art. 5 el 3 de marzo de 2019?", date(2019, 3, 3)),
    ],
)
async def test_extract_as_of_regex_first(q, expected):
    spy = Spy()
    assert await extract_as_of(q, spy) == expected
    assert spy.calls == 0


async def test_falls_back_to_llm_when_ambiguous():
    spy = Spy(result=date(2020, 1, 1))
    assert await extract_as_of("entre 2019-01-01 y 2020-01-01", spy) == date(2020, 1, 1)
    assert spy.calls == 1


async def test_falls_back_to_llm_when_no_date_found():
    spy = Spy(result=None)
    assert await extract_as_of("que dice la ley sobre despidos", spy) is None
    assert spy.calls == 1


def test_invalid_calendar_date_ignored():
    assert regex_dates("31/02/2020") == []


def test_regex_dates_iso():
    assert regex_dates("vigente a 2021-06-01") == [date(2021, 6, 1)]


def test_regex_dates_numeric_es_day_first():
    assert regex_dates("el 15/03/2020") == [date(2020, 3, 15)]


def test_regex_dates_long_es_case_insensitive():
    assert regex_dates("a 3 de MARZO de 2019") == [date(2019, 3, 3)]
    assert regex_dates("a 3 de marzo de 2019") == [date(2019, 3, 3)]
