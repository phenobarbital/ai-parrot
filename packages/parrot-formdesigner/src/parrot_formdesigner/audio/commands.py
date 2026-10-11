"""Hands-free voice command classification (FEAT-649, Module 4)."""

from __future__ import annotations

import difflib
from enum import Enum

from .models import Phase
from .narration.lexicon import Lexicon, normalize

_FUZZY_MIN = 0.9


class VoiceCommand(str, Enum):
    """Spoken commands recognised during an audio session."""

    REPEAT = "repeat"
    BACK = "back"
    SKIP = "skip"
    HELP = "help"
    STOP = "stop"
    NEXT = "next"
    SEND = "send"
    CHANGE = "change"
    YES = "yes"
    NO = "no"


_CONFIRM_ONLY = frozenset({VoiceCommand.YES, VoiceCommand.NO, VoiceCommand.SEND, VoiceCommand.CHANGE})
_CONFIRM_PHASES = frozenset({Phase.CONFIRMING, Phase.REVIEW})
_DEAD_PHASES = frozenset({Phase.SUBMITTING, Phase.COMPLETE, Phase.ABORTED})
# Tie-break order: YES/NO win over SEND for shared phrases such as "sí".
_PRIORITY = (
    VoiceCommand.REPEAT,
    VoiceCommand.BACK,
    VoiceCommand.SKIP,
    VoiceCommand.HELP,
    VoiceCommand.STOP,
    VoiceCommand.NEXT,
    VoiceCommand.YES,
    VoiceCommand.NO,
    VoiceCommand.SEND,
    VoiceCommand.CHANGE,
)


def _phrases(cmd: VoiceCommand, lexicon: Lexicon) -> list[str]:
    """Every lexicon phrase that triggers ``cmd`` (already in lexicon form; normalised by the caller)."""
    if cmd is VoiceCommand.YES:
        return list(lexicon.yes)
    if cmd is VoiceCommand.NO:
        return list(lexicon.no)
    phrases = list(lexicon.commands.get(cmd.value, []))
    if cmd is VoiceCommand.SEND:
        phrases += list(lexicon.review_confirm)
    if cmd is VoiceCommand.CHANGE:
        phrases += list(lexicon.review_change)
    return phrases


def classify_command(transcript: str, *, lexicon: Lexicon, phase: Phase, max_tokens: int = 4) -> VoiceCommand | None:
    """Whole-utterance match (<= max_tokens after normalize); fuzzy >= 0.9; YES/NO/SEND/CHANGE only in CONFIRMING/REVIEW.

    Args:
        transcript: Raw transcript.
        lexicon: Locale lexicon.
        phase: Current engine phase (gates which commands are allowed).
        max_tokens: Maximum normalised token count for a command utterance.

    Returns:
        The matched command, or ``None``.
    """
    if phase in _DEAD_PHASES:
        return None
    text = normalize(transcript, lexicon)
    if not text or len(text.split()) > max_tokens:
        return None
    best: tuple[float, VoiceCommand] | None = None
    for cmd in _PRIORITY:
        if cmd in _CONFIRM_ONLY and phase not in _CONFIRM_PHASES:
            continue
        for phrase in _phrases(cmd, lexicon):
            norm = normalize(phrase, lexicon)
            if not norm:
                continue
            if text == norm:
                return cmd  # exact; first in priority order wins
            if cmd is VoiceCommand.CHANGE and text.startswith(norm + " "):
                return cmd
            ratio = difflib.SequenceMatcher(None, text, norm).ratio()
            # strict ">" keeps the earlier priority member on ties
            if ratio >= _FUZZY_MIN and (best is None or ratio > best[0]):
                best = (ratio, cmd)
    return best[1] if best else None


def command_option_collisions(options: list[dict], lexicon: Lexicon) -> list[tuple[str, VoiceCommand]]:
    """Option labels that normalise to a command phrase — used by tests and the optimiser self-test."""
    collisions: list[tuple[str, VoiceCommand]] = []
    for opt in options:
        label = str(opt.get("label", opt.get("value", "")))
        norm = normalize(label, lexicon)
        for cmd in VoiceCommand:
            if any(norm == normalize(p, lexicon) for p in _phrases(cmd, lexicon)):
                collisions.append((label, cmd))
    return collisions
