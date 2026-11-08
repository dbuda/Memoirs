import re

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

WORD_DECADES = {
    "fifties": 1950,
    "sixties": 1960,
    "seventies": 1970,
    "eighties": 1980,
    "nineties": 1990,
}

_DAYS = {
    "early": (0, 3),
    "mid": (3, 6),
    "late": (5, 9),
}

_MONTHS_PATTERN = "|".join(MONTHS)

_DAY_MONTH_YEAR = re.compile(
    r"\b(?P<day>\d{1,2})\s+(?P<month>"
    + _MONTHS_PATTERN
    + r")\s*,?\s*(?P<year>1[89]\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR = re.compile(
    r"\b(?P<month>"
    + _MONTHS_PATTERN
    + r")\s+(?P<day>\d{1,2})\s*,?\s*(?P<year>1[89]\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_MONTH_YEAR = re.compile(
    r"\b(?P<month>" + _MONTHS_PATTERN + r")\s+(?P<year>1[89]\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_SEASON_YEAR = re.compile(
    r"\b(?P<season>spring|summer|autumn|winter)\s+of\s+(?P<year>1[89]\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_NUMERIC_DECADE = re.compile(
    r"\b(?P<prefix>early|mid|late)?[\s-]*(?P<decade>(?:18|19|20)\d0)s?\b",
    re.IGNORECASE,
)
_WORD_DECADE = re.compile(
    r"\b(?P<prefix>early|mid|late)?\s*(?P<decade>fifties|sixties|seventies|eighties|nineties)\b",
    re.IGNORECASE,
)
_RELATIVE = re.compile(
    r"\b(?P<count>\w+)\s+(?P<unit>year|years|month|months|day|days)\s+(?P<direction>later|after|before)\b",
    re.IGNORECASE,
)
_PLAIN_YEAR = re.compile(r"\b(?P<year>1[89]\d{2}|20\d{2})\b")


def _decade_range(prefix: str | None, base: int) -> tuple[int, int]:
    if prefix == "early":
        return base, base + 3
    if prefix == "mid":
        return base + 3, base + 6
    if prefix == "late":
        return base + 5, base + 9
    return base, base + 9


def parse_date_expression(text: str) -> dict[str, str | bool] | None:
    """Return a structured interpretation of the earliest date expression.

    The raw expression is always preserved. Approximate and relative dates keep
    their precision so downstream code cannot mistake them for exact facts.
    """
    candidates: list[tuple[int, int, dict[str, str | bool]]] = []

    for match in _DAY_MONTH_YEAR.finditer(text):
        month = MONTHS[match.group("month").lower()]
        day = int(match.group("day"))
        year = match.group("year")
        value = f"{year}-{month:02d}-{day:02d}"
        candidates.append((match.start(), 0, _result(match, value, value, "day")))

    for match in _MONTH_DAY_YEAR.finditer(text):
        month = MONTHS[match.group("month").lower()]
        day = int(match.group("day"))
        year = match.group("year")
        value = f"{year}-{month:02d}-{day:02d}"
        candidates.append((match.start(), 0, _result(match, value, value, "day")))

    for match in _MONTH_YEAR.finditer(text):
        month = MONTHS[match.group("month").lower()]
        year = match.group("year")
        value = f"{year}-{month:02d}"
        candidates.append((match.start(), 1, _result(match, value, value, "month")))

    for match in _SEASON_YEAR.finditer(text):
        year = match.group("year")
        candidates.append((match.start(), 2, _result(match, year, year, "season")))

    for match in _NUMERIC_DECADE.finditer(text):
        prefix = match.group("prefix")
        base = int(match.group("decade").rstrip("s"))
        start, end = _decade_range(prefix.lower() if prefix else None, base)
        candidates.append((match.start(), 3, _result(match, str(start), str(end), "decade")))

    for match in _WORD_DECADE.finditer(text):
        prefix = match.group("prefix")
        base = WORD_DECADES[match.group("decade").lower()]
        start, end = _decade_range(prefix.lower() if prefix else None, base)
        candidates.append((match.start(), 3, _result(match, str(start), str(end), "decade")))

    for match in _PLAIN_YEAR.finditer(text):
        year = match.group("year")
        candidates.append((match.start(), 5, _result(match, year, year, "year")))

    relative = [(match.start(), 4, _relative_result(match)) for match in _RELATIVE.finditer(text)]

    absolute = [candidate for candidate in candidates if candidate[0] >= 0]
    pool = absolute or relative
    if not pool:
        return None
    _, _, result = min(pool, key=lambda candidate: (candidate[0], candidate[1]))
    return result


def _result(match: re.Match[str], start: str, end: str, precision: str) -> dict[str, str | bool]:
    return {
        "date_text": match.group(0).strip(),
        "date_start": start,
        "date_end": end,
        "date_precision": precision,
        "is_relative": False,
        "matched_text": match.group(0).strip(),
    }


def _relative_result(match: re.Match[str]) -> dict[str, str | bool]:
    return {
        "date_text": match.group(0).strip(),
        "date_start": None,
        "date_end": None,
        "date_precision": "relative",
        "is_relative": True,
        "matched_text": match.group(0).strip(),
    }
