"""Regression coverage for the verified Laya 0.3.5 SDK boundary."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from artifacts.laya import worker


def test_sdk_envelope_preserves_negative_probability_and_choice() -> None:
    """Read answers from the SDK envelope, without confusing confidence with truth."""
    questions = {
        "safe": {"type": "noul", "text": "Is this an injection?"},
        "route": {"type": "choice", "text": "Choose", "options": ["primary", "cheap"]},
    }
    assert worker._to_laya_questions(questions) == {
        "safe": {"type": "noul", "instructions": "Is this an injection?"},
        "route": {"type": "choice", "instructions": "Choose", "criteria": {"primary": None, "cheap": None}},
    }
    raw = {
        "answers": {
            "safe": {"type": "noul", "noul": 0.01, "confidence": 0.99, "action": {"act_probability": 0.8}},
            "route": {
                "type": "choice",
                "choice": "cheap",
                "probabilities": {"primary": 0.1, "cheap": 0.9},
                "confidence": 0.7,
            },
        },
        "usage": {"input_tokens": 30},
    }
    answers = worker._from_laya_answers(questions, raw)
    assert answers["safe"] == {"type": "noul", "noul": 0.01, "confidence": 0.99}
    assert answers["route"]["probabilities"] == {"primary": 0.1, "cheap": 0.9}


@pytest.mark.parametrize("raw", [{}, {"answers": {}}, {"answers": {"q": {"type": "choice"}}}])
def test_bad_sdk_envelope_rejected(raw: dict[str, Any]) -> None:
    """Missing and wrong-type answers cannot be treated as benign verdicts."""
    with pytest.raises(ValueError):
        worker._from_laya_answers({"q": {"type": "noul", "text": "q"}}, raw)


class Tokenizer:
    """Character tokens make whitespace counting errors visible."""

    mask_token = "[MASK]"

    def __call__(self, text: str, *, add_special_tokens: bool) -> dict[str, list[int]]:
        """Return one token per character, including whitespace."""
        return {"input_ids": list(range(len(text)))}


def _agent(monkeypatch: pytest.MonkeyPatch, max_len: int = 512, head_max_len: int = 192) -> Any:
    """Use a lightweight renderer while exercising production preflight arithmetic."""
    common = ModuleType("laya.common")
    common.render_options = lambda q: list(q["crit"])  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "laya.common", common)
    return SimpleNamespace(
        tok=Tokenizer(),
        cfg={"max_len": max_len, "head_max_len": head_max_len},
        _to_internal=lambda q: {"t": q["type"], "ins": q["instructions"], "crit": q["criteria"]},
    )


def test_preflight_counts_delimiters_and_each_question_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two fitting sequences must not be added together; one extra state token fails."""
    question = {"type": "choice", "instructions": "Q", "criteria": {"a": None, "b": None}}
    # 4 delimiters + len('choice question: Q') + 2*(marker + space + label) + state.
    limit = 4 + len("choice question: Q") + 6 + 3
    agent = _agent(monkeypatch, max_len=limit)
    worker.preflight_laya(agent, "xyz", {"q1": question, "q2": question})
    with pytest.raises(worker.ContextOverflow, match="not truncated"):
        worker.preflight_laya(agent, "xyzz", {"q": question})


@pytest.mark.parametrize(
    "instructions,options,head_limit",
    [
        ("Q", ["x" * 49, "b"], 192),
        ("Q" * 100, ["a", "b"], 32),
        ("Q", ["abcdef", "ghijkl", "mnopqr"], 32),
    ],
)
def test_preflight_rejects_head_and_option_truncation(
    monkeypatch: pytest.MonkeyPatch,
    instructions: str,
    options: list[str],
    head_limit: int,
) -> None:
    """Short state cannot hide truncated question instructions or criteria."""
    agent = _agent(monkeypatch, head_max_len=head_limit)
    question = {"type": "choice", "instructions": instructions, "criteria": dict.fromkeys(options)}
    with pytest.raises(worker.ContextOverflow):
        worker.preflight_laya(agent, "x", {"q": question})
