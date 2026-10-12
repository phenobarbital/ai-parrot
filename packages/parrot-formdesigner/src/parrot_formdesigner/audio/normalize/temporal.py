"""DATE / TIME / DATETIME post-processors: spoken or written → ISO strings in the client's timezone (FEAT-653)."""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from ..narration.lexicon import SpokenLexicon
from .base import NormalizeContext, NormalizeResult
from .numbers import _expand, parse_numbers, tokenize

logger = logging.getLogger(__name__)

_RANK = {"accepted": 0, "confirm": 1, "rejected": 2}

_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NUMERIC_DATE_RE = re.compile(r"^(\d{1,4})[/-](\d{1,2})(?:[/-](\d{1,4}))?$")
_DAY_TOKEN_RE = re.compile(r"^(\d{1,4})(?:st|nd|rd|th|o)?$")
_CLOCK_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$")
_ISO_DATETIME_RE = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2})t(\d{1,2}:\d{2})$")
_MERIDIEM_DOTTED_RE = re.compile(r"^([ap])\.m$")
_O_CLOCK = {"o", "clock", "oclock"}
_NUMERIC_TOKEN_RE = re.compile(r"^\d+$")
# marker → direction: en "ten past/to three" (minutes first), es "tres y/menos diez" (hour first)
_REL_MARKERS = {"past": "plus", "to": "minus", "y": "plus", "menos": "minus"}
# filler words that carry no time information; anything else left over downgrades an accepted time to a confirm
_TIME_IGNORABLE = frozenset(
    {
        "at", "a", "an", "the", "it", "s", "is", "its", "about", "around", "approximately", "exactly", "sharp",
        "please", "thanks", "hours", "hrs", "hr", "h", "hs",
        "las", "la", "los", "el", "son", "es", "en", "punto", "por", "favor", "hora", "aproximadamente", "como",
    }
)


def _weekday_after(today: date, weekday: int) -> date:
    """Nearest occurrence of ``weekday`` strictly after ``today`` (spec §8 Q1)."""
    delta = (weekday - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def _weekday_before(today: date, weekday: int) -> date:
    """Nearest occurrence of ``weekday`` strictly before ``today``."""
    delta = (today.weekday() - weekday) % 7
    return today - timedelta(days=delta or 7)


def _find_phrase(tokens: list[str], phrases: dict[str, object] | list[str]) -> tuple[int, int, str] | None:
    """Locate the first (longest-first) phrase in ``tokens``; returns ``(start, length, phrase)``."""
    for phrase in sorted(phrases, key=lambda p: -len(p.split())):
        words = phrase.split()
        size = len(words)
        if size == 0:
            continue
        for start in range(len(tokens) - size + 1):
            if tokens[start : start + size] == words:
                return start, size, phrase
    return None


def _ordinal_value(token: str, ctx: NormalizeContext) -> int | None:
    """Positive ordinal value of a word (table first, then regular ``-teenth``/``-tieth`` forms)."""
    value = ctx.lexicon.ordinals.get(token)
    if value is not None:
        return value if value > 0 else None
    spoken = ctx.lexicon.spoken
    if token.endswith("ieth") and token[:-4] + "y" in spoken.tens:
        return spoken.tens[token[:-4] + "y"]
    if token.endswith("fth") and token[:-3] + "ve" in spoken.units:
        return spoken.units[token[:-3] + "ve"]
    if token.endswith("th") and token[:-2] in spoken.units:
        return spoken.units[token[:-2]]
    return None


def _is_number_word(token: str, spoken: SpokenLexicon) -> bool:
    return token in spoken.units or token in spoken.tens or token in spoken.scales


def _is_pure_ordinal(token: str, ctx: NormalizeContext) -> bool:
    """An ordinal word that is not also a cardinal ('fifth', 'thirtieth'; not 'twenty')."""
    return not _is_number_word(token, ctx.lexicon.spoken) and _ordinal_value(token, ctx) is not None


def _split_years(nums: list[int]) -> tuple[list[int], list[int]]:
    """Split a spoken number run into ``(days, years)``.

    Spoken years arrive as two groups ('twenty twenty five' → 20, 25; 'twenty oh five' → 20, 0, 5) or as one
    large number ('two thousand twenty six' → 2026); everything else in 1..31 is a day.
    """
    days: list[int] = []
    years: list[int] = []
    i = 0
    while i < len(nums):
        v = nums[i]
        nxt = nums[i + 1] if i + 1 < len(nums) else None
        if v in (19, 20) and nxt is not None and nxt >= 10:
            years.append(v * 100 + nxt)
            i += 2
        elif v in (19, 20) and nxt == 0 and i + 2 < len(nums) and 1 <= nums[i + 2] <= 9:
            years.append(v * 100 + nums[i + 2])
            i += 3
        elif v > 31:
            years.append(v)
            i += 1
        else:
            if 1 <= v <= 31:
                days.append(v)
            i += 1
    return days, years


def _date_items(tokens: list[str], ctx: NormalizeContext) -> tuple[list[int], list[int]]:
    """Day and year candidates: digit tokens (with ordinal suffix), ordinal words and number-word runs."""
    spoken = ctx.lexicon.spoken
    days: list[int] = []
    years: list[int] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        m = _DAY_TOKEN_RE.match(tok)
        if m:
            d, y = _split_years([int(m.group(1))])
            days.extend(d)
            years.extend(y)
            i += 1
        elif _is_number_word(tok, spoken):
            j = i
            while j < n and _is_number_word(tokens[j], spoken):
                j += 1
            nums = [int(x) for x in parse_numbers(tokens[i:j], spoken)]
            tail: int | None = None
            if j < n and _is_pure_ordinal(tokens[j], ctx):
                tail = _ordinal_value(tokens[j], ctx)
                j += 1
            ordinal_day: int | None = None
            if tail is not None:
                if nums and nums[-1] >= 20 and nums[-1] % 10 == 0 and tail < 10:
                    ordinal_day = nums.pop() + tail  # 'twenty' + 'first'
                else:
                    ordinal_day = tail
            d, y = _split_years(nums)
            days.extend(d)
            years.extend(y)
            if ordinal_day is not None and 1 <= ordinal_day <= 31:
                days.append(ordinal_day)
            i = j
        elif _is_pure_ordinal(tok, ctx):
            value = _ordinal_value(tok, ctx)
            if value is not None and 1 <= value <= 31:
                days.append(value)
            i += 1
        else:
            i += 1
    return days, years


def _build_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _year(value: int) -> int:
    return 2000 + value if value < 100 else value


def _numeric_date(a: int, b: int, y: int | None, ctx: NormalizeContext) -> NormalizeResult:
    """Interpret ``A/B[/Y]`` per ``date_order``; both-valid and different → confirm."""
    year = ctx.now.year if y is None else _year(y)
    mdy = _build_date(year, a, b)
    dmy = _build_date(year, b, a)
    if mdy is None and dmy is None:
        return NormalizeResult.rejected("out_of_range")
    if mdy is not None and dmy is not None and a != b:
        candidate = mdy if ctx.lexicon.spoken.date_order == "MDY" else dmy
        return NormalizeResult.confirm(candidate, "ambiguous_order")
    return NormalizeResult.accepted(mdy or dmy)


def _mask_day_period(tokens: list[str]) -> list[str]:
    """Hide 'la mañana' (the morning) so it is not read as the relative day 'mañana' (tomorrow)."""
    return ["_" if tok == "manana" and i > 0 and tokens[i - 1] == "la" else tok for i, tok in enumerate(tokens)]


def _parse_date(tokens: list[str], ctx: NormalizeContext) -> NormalizeResult:
    """Date grammar over already-tokenized input; value is a ``date`` (formatted by the caller)."""
    tokens = _expand(tokens)
    spoken = ctx.lexicon.spoken
    today = ctx.now.date()

    def relative(value: date) -> NormalizeResult:
        if ctx.timezone_known:
            return NormalizeResult.accepted(value)
        return NormalizeResult.confirm(value, "needs_timezone")

    for tok in tokens:
        iso = _ISO_RE.match(tok)
        if iso:
            parsed = _build_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            return NormalizeResult.accepted(parsed) if parsed else NormalizeResult.rejected("out_of_range")
        num = _NUMERIC_DATE_RE.match(tok)
        if num:
            first, second, third = int(num.group(1)), int(num.group(2)), num.group(3)
            if third is not None and len(num.group(1)) == 4:  # Y/M/D
                parsed = _build_date(first, second, int(third))
                return NormalizeResult.accepted(parsed) if parsed else NormalizeResult.rejected("out_of_range")
            if len(num.group(1)) > 2:
                return NormalizeResult.rejected("no_parse")
            return _numeric_date(first, second, int(third) if third is not None else None, ctx)

    month_at = next((i for i, t in enumerate(tokens) if t in spoken.months), None)
    if month_at is not None:
        month = spoken.months[tokens[month_at]]
        days, years = _date_items(tokens[:month_at] + tokens[month_at + 1 :], ctx)
        if not days:  # "March twenty twenty six": a year with no day is never read as the day
            return NormalizeResult.rejected("no_parse")
        year = _year(years[0]) if years else ctx.now.year
        built = _build_date(year, month, days[0])
        if built is None:
            return NormalizeResult.rejected("out_of_range")
        if len(set(days)) > 1:  # "March 5 25": which number is the day?
            return NormalizeResult.confirm(built, "ambiguous_order")
        return NormalizeResult.accepted(built)

    hit = _find_phrase(_mask_day_period(tokens), spoken.relative_days)
    if hit is not None:
        return relative(today + timedelta(days=spoken.relative_days[hit[2]]))

    day_at = next((i for i, t in enumerate(tokens) if t in spoken.weekdays), None)
    if day_at is not None:
        weekday = spoken.weekdays[tokens[day_at]]
        before = tokens[day_at - 1] if day_at > 0 else ""
        after = tokens[day_at + 1 :]
        is_last = before in spoken.last_words or any(after[: len(p.split())] == p.split() for p in spoken.last_words)
        if is_last:
            return relative(_weekday_before(today, weekday))
        return relative(_weekday_after(today, weekday))
    return NormalizeResult.rejected("no_parse")


def _parse_time(tokens: list[str], ctx: NormalizeContext) -> NormalizeResult:
    """Time grammar; value is a ``(hour, minute)`` tuple (formatted by the caller)."""
    spoken = ctx.lexicon.spoken
    toks = [("am" if m.group(1) == "a" else "pm") if (m := _MERIDIEM_DOTTED_RE.match(t)) else t for t in tokens]
    toks = [t for t in toks if t not in _O_CLOCK]

    meridiem: str | None = None
    special: tuple[int, int] | None = None
    half = False
    for phrases, kind in (
        (spoken.pm_words, "pm"),
        (spoken.am_words, "am"),
        (spoken.noon_words, "noon"),
        (spoken.midnight_words, "midnight"),
        (spoken.half_words, "half"),
    ):
        hit = _find_phrase(toks, phrases)
        if hit is None:
            continue
        toks = toks[: hit[0]] + toks[hit[0] + hit[1] :]
        if kind in ("am", "pm"):
            meridiem = meridiem or kind
        elif kind == "noon":
            special = (12, 0)
        elif kind == "midnight":
            special = (0, 0)
        else:
            half = True
    if special is not None:
        return NormalizeResult.accepted(special)

    def known(token: str, *, numbers: bool = True) -> bool:
        if token in _TIME_IGNORABLE:
            return True
        if not numbers:
            return False
        return bool(_NUMERIC_TOKEN_RE.match(token)) or _is_number_word(token, spoken) or token in spoken.number_joiners

    def finish(hour: int, minute: int, leading_zero: bool, rest: list[str], *, numbers: bool = True) -> NormalizeResult:
        res = _finish_time(hour, minute, meridiem, leading_zero)
        if res.status == "accepted" and not all(known(t, numbers=numbers) for t in rest):
            return NormalizeResult.confirm(res.value, "unrecognized_words")
        return res

    hour: int | None = None
    minute = 0
    clock_at = next(
        (i for i, t in enumerate(toks) if (m := _CLOCK_RE.match(t)) and (m.group(2) is not None or m.group(3) is not None)),
        None,
    )
    if clock_at is not None:  # "15:30", "3:30pm", "3pm"
        m = _CLOCK_RE.match(toks[clock_at])
        assert m is not None
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) is not None else 0
        if m.group(3):
            meridiem = meridiem or m.group(3)
        leading_zero = len(m.group(1)) == 2 and m.group(1).startswith("0") and m.group(2) is not None
        if minute > 59 or hour > 23:
            return NormalizeResult.rejected("out_of_range")
        return finish(hour, minute, leading_zero, toks[:clock_at] + toks[clock_at + 1 :], numbers=False)

    marker = next((i for i, t in enumerate(toks) if t in _REL_MARKERS), None)
    if marker is not None:  # "quarter past three", "ten to four", "las cinco y cuarto", "las cinco menos diez"
        word = toks[marker]
        before = [t for t in toks[:marker] if t not in _TIME_IGNORABLE]
        after = [t for t in toks[marker + 1 :] if t not in _TIME_IGNORABLE]
        minutes_first = word in ("past", "to")
        minute_part, hour_part = (before, after) if minutes_first else (after, before)
        rel_minute = _small_number(minute_part, spoken, allow_quarter=True)
        rel_hour = _small_number(hour_part, spoken, allow_quarter=False)
        if rel_minute is None or rel_hour is None or not 1 <= rel_minute <= 59 or not 0 <= rel_hour <= 23:
            return NormalizeResult.rejected("no_parse")
        if _REL_MARKERS[word] == "minus":
            if rel_hour == 0:
                return NormalizeResult.rejected("no_parse")
            minute = 60 - rel_minute
            hour = 12 if rel_hour == 1 else rel_hour - 1
            if rel_hour == 12 and meridiem is not None:  # "ten to twelve pm" flips the half of the day: never guess
                return NormalizeResult.confirm((11 if meridiem == "pm" else 23, minute), "ambiguous_meridiem")
        else:
            hour, minute = rel_hour, rel_minute
        return finish(hour, minute, False, [])

    nums = [x for x in parse_numbers(toks, spoken)]
    if not nums or any(not float(x).is_integer() for x in nums):
        return NormalizeResult.rejected("no_parse")
    nums = [int(x) for x in nums]
    hour = nums[0]
    if len(nums) == 1 and 100 <= hour <= 2359 and hour % 100 < 60:
        hour, minute = hour // 100, hour % 100
    elif len(nums) == 2:
        minute = nums[1]
    elif len(nums) == 3 and nums[1] == 0 and nums[2] < 10:
        minute = nums[2]
    elif len(nums) > 1:
        return NormalizeResult.rejected("no_parse")
    if half:
        minute = 30
    if minute > 59 or hour > 23:
        return NormalizeResult.rejected("out_of_range")
    return finish(hour, minute, False, toks)


def _small_number(tokens: list[str], spoken: SpokenLexicon, *, allow_quarter: bool) -> int | None:
    """A single integer made of ``tokens`` only (digits or words); 'quarter'/'cuarto' = 15 when allowed."""
    if not tokens:
        return None
    if allow_quarter and tokens in (["quarter"], ["cuarto"]):
        return 15
    nums = parse_numbers(tokens, spoken)
    if len(nums) != 1 or not float(nums[0]).is_integer():
        return None
    if not all(
        _NUMERIC_TOKEN_RE.match(t) or _is_number_word(t, spoken) or t in spoken.number_joiners for t in tokens
    ):
        return None
    return int(nums[0])


def _finish_time(hour: int, minute: int, meridiem: str | None, leading_zero: bool) -> NormalizeResult:
    """Apply the meridiem; an hour with no meridiem that could be either half of the day is a confirm."""
    if meridiem is not None:
        if not 1 <= hour <= 12:
            return NormalizeResult.rejected("out_of_range")
        if meridiem == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = hour if hour == 12 else hour + 12
        return NormalizeResult.accepted((hour, minute))
    if hour == 0 or hour >= 13 or leading_zero:
        return NormalizeResult.accepted((hour, minute))
    return NormalizeResult.confirm((hour, minute), "ambiguous_meridiem")


def _fmt_time(value: tuple[int, int]) -> str:
    return f"{value[0]:02d}:{value[1]:02d}"


def normalize_date(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Spoken/written date → 'YYYY-MM-DD'."""
    try:
        res = _parse_date(tokenize(text), ctx)
    except Exception as exc:  # noqa: BLE001 — normalizers never raise
        logger.debug("normalize_date failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    if res.status != "rejected" and isinstance(res.value, date):
        return res.model_copy(update={"value": res.value.isoformat()})
    return res


def normalize_time(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Spoken/written time → 'HH:MM' (24 h)."""
    try:
        res = _parse_time(tokenize(text), ctx)
    except Exception as exc:  # noqa: BLE001 — normalizers never raise
        logger.debug("normalize_time failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
    if res.status != "rejected" and isinstance(res.value, tuple):
        return res.model_copy(update={"value": _fmt_time(res.value)})
    return res


def _split_datetime(tokens: list[str]) -> list[tuple[list[str], list[str]]]:
    """Candidate (date tokens, time tokens) splits: explicit connector first, then every cut point."""
    candidates: list[tuple[list[str], list[str]]] = []
    for k, tok in enumerate(tokens):
        if tok in ("at", "@") and 0 < k < len(tokens) - 1:
            candidates.append((tokens[:k], tokens[k + 1 :]))
            break
        if tok == "a" and k + 1 < len(tokens) - 1 and tokens[k + 1] in ("las", "la") and k > 0:
            candidates.append((tokens[:k], tokens[k + 2 :]))
            break
    if not candidates:
        candidates = [(tokens[:k], tokens[k:]) for k in range(1, len(tokens))]
    return candidates


def _datetime(tokens: list[str], ctx: NormalizeContext) -> NormalizeResult:
    if len(tokens) == 1:
        joined = _ISO_DATETIME_RE.match(tokens[0])
        if joined:
            tokens = [joined.group(1), joined.group(2)]
    best: NormalizeResult | None = None
    for date_tokens, time_tokens in _split_datetime(tokens):
        d = _parse_date(date_tokens, ctx)
        t = _parse_time(time_tokens, ctx)
        if d.status == "rejected" or t.status == "rejected":
            if best is None or (d.reason != "no_parse" and t.reason != "no_parse"):
                worst = d if d.status == "rejected" else t
                best = NormalizeResult.rejected(worst.reason or "no_parse")
            if d.reason == "no_parse" or t.reason == "no_parse":
                continue
            return best
        status = max((d.status, t.status), key=lambda s: _RANK[s])
        reason = d.reason if _RANK[d.status] >= _RANK[t.status] and d.reason else t.reason
        value = f"{d.value.isoformat()}T{_fmt_time(t.value)}"
        if status == "accepted":
            return NormalizeResult.accepted(value)
        return NormalizeResult.confirm(value, reason or "ambiguous_meridiem")
    return best or NormalizeResult.rejected("no_parse")


def normalize_datetime(text: str, ctx: NormalizeContext) -> NormalizeResult:
    """Split into a date phrase and a time phrase ('tomorrow at three pm'); worst status of the two parts wins."""
    try:
        return _datetime(tokenize(text), ctx)
    except Exception as exc:  # noqa: BLE001 — normalizers never raise
        logger.debug("normalize_datetime failed: %s", type(exc).__name__)
        return NormalizeResult.rejected("no_parse")
