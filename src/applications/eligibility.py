"""Deterministic checks. Years, dates, and stated deal-breakers stay out of jev."""

import re

from applications.textutil import snippet, strip_html

_YEAR = re.compile(r"\b(\d+)\s*\+?\s*(?:years|yrs)\b", re.IGNORECASE)
_PREFERRED = re.compile(
    r"preferred|nice to have|bonus|ideally|or equivalent|may substitute|ms substitutions?",
    re.IGNORECASE,
)
_EXPERIENCE = re.compile(r"experience|software|engineer|develop", re.IGNORECASE)
_MORE_THAN_TWO = re.compile(r"(?:more than|over|greater than)\s+(?:2|two)\s+(?:years|yrs)", re.IGNORECASE)


def eligibility_reason(description: str) -> str | None:
    text = strip_html(description)
    if not text:
        return None
    for checker in (
        _graduation,
        _years,
        _phd,
        _citizenship,
        _clearance,
        _sponsorship,
        _unpaid,
        _outside_us,
    ):
        reason = checker(text)
        if reason:
            return reason
    return None


def _graduation(text: str) -> str | None:
    for match in re.finditer(r"2027", text):
        window = text[max(0, match.start() - 80) : match.end() + 40]
        if not re.search(r"graduat|class of", window, re.IGNORECASE):
            continue
        wider = text[max(0, match.start() - 120) : match.end() + 80]
        if "2026" in wider:
            continue
        if re.search(r"must|required|only|class of", window, re.IGNORECASE):
            return f"graduation exclude: window cannot include December 2026 ({snippet(text, match.start(), match.end())!r})"
    return None


def _years(text: str) -> str | None:
    more = _MORE_THAN_TWO.search(text)
    if more and not _PREFERRED.search(text[max(0, more.start() - 80) : more.end() + 40]):
        return (
            "years exclude: more than 2 years strictly required "
            f"({snippet(text, more.start(), more.end())!r}). "
            "Accenture network-security time is not AI or SWE experience."
        )
    for match in _YEAR.finditer(text):
        years = int(match.group(1))
        prefix = text[max(0, match.start() - 16) : match.start()]
        if years == 2 and re.search(r"more than|over|greater than", prefix, re.IGNORECASE):
            years = 3
        if years <= 2:
            continue
        window = text[max(0, match.start() - 100) : match.end() + 60]
        if not _EXPERIENCE.search(window) or _PREFERRED.search(window):
            continue
        return (
            f"years exclude: {years}+ years strictly required ({snippet(text, match.start(), match.end())!r}). "
            "Accenture network-security time is not AI or SWE experience."
        )
    return None


def _phd(text: str) -> str | None:
    for match in re.finditer(r"ph\.?\s*d|doctoral degree", text, re.IGNORECASE):
        window = text[max(0, match.start() - 60) : match.end() + 40]
        if _PREFERRED.search(window) or re.search(r"\bor\b.{0,20}\b(?:ms|master)", window, re.IGNORECASE):
            continue
        if re.search(r"required|must|only", window, re.IGNORECASE):
            return f"degree exclude: PhD strictly required ({snippet(text, match.start(), match.end())!r})"
    return None


def _citizenship(text: str) -> str | None:
    pattern = re.compile(
        r"u\.?s\.? citizen|united states citizen|permanent resident|green card",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        window = text[max(0, match.start() - 70) : match.end() + 70]
        if re.search(r"or (?:those )?(?:authorized|sponsorship|visa)", window, re.IGNORECASE):
            continue
        if re.search(r"required|must|only|need to be", window, re.IGNORECASE):
            return f"authorization exclude: citizenship or permanent residence required ({snippet(text, match.start(), match.end())!r})"
    return None


def _clearance(text: str) -> str | None:
    pattern = re.compile(r"security clearance|ts/sci|top secret", re.IGNORECASE)
    for match in pattern.finditer(text):
        window = text[max(0, match.start() - 70) : match.end() + 70]
        if re.search(r"not required|no clearance", window, re.IGNORECASE):
            continue
        if re.search(r"required|must|active|eligib|ability to obtain", window, re.IGNORECASE):
            return f"authorization exclude: clearance required ({snippet(text, match.start(), match.end())!r})"
    return None


def _sponsorship(text: str) -> str | None:
    opt = re.search(r"opt (?:is |candidates )?(?:not |in)eligible|no opt candidates|opt ineligible", text, re.IGNORECASE)
    if opt:
        return f"authorization exclude: OPT ineligible ({snippet(text, opt.start(), opt.end())!r})"
    for match in re.finditer(r"sponsor\w*", text, re.IGNORECASE):
        start = text.rfind(".", 0, match.start()) + 1
        end = text.find(".", match.end())
        if end == -1:
            end = len(text)
        sentence = text[start:end]
        negative = re.search(
            r"(?:do not|don't|cannot|can't|unable to|will not|won't|not able to|not offer|not provide)"
            r"(?:\s+\w+){0,4}\s+sponsor|"
            r"\bno\s+sponsorship\b|sponsorship is not|"
            r"without (?:the need for |requiring )?sponsorship",
            sentence,
            re.IGNORECASE,
        )
        if not negative:
            continue
        now_only = re.search(r"at this time|currently|right now|at present|for now", sentence, re.IGNORECASE)
        if now_only and not re.search(r"future", sentence, re.IGNORECASE):
            continue
        return f"authorization exclude: no sponsorship ({snippet(text, start, end)!r})"
    return None


def _unpaid(text: str) -> str | None:
    match = re.search(r"unpaid (?:position|role|internship|job|opportunity)", text, re.IGNORECASE)
    if match:
        return f"listing exclude: unpaid ({snippet(text, match.start(), match.end())!r})"
    return None


def _outside_us(text: str) -> str | None:
    match = re.search(
        r"must (?:be |currently )?(?:located|based|reside|live) in [^.]{0,40}|"
        r"(?:uk|united kingdom|europe|india|canada) only|"
        r"(?:no|not) (?:open to )?(?:us|u\.s\.|united states) (?:residents|candidates)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    fragment = match.group(0)
    from applications.keywords import location_decision
    place = re.sub(r"^must (?:be |currently )?(?:located|based|reside|live) in ", "", fragment, flags=re.IGNORECASE).strip()
    if place != fragment:
        decision = location_decision(place)
        if decision.action != "reject":
            # An unknown city is not proof of a non-US requirement. Let Jev
            # evaluate it rather than creating a deterministic false negative.
            return None
    if re.search(r"united states|u\.s\.|usa|\bus\b", fragment, re.IGNORECASE) and not re.search(
        r"no|not|outside", fragment, re.IGNORECASE
    ):
        return None
    return f"location exclude: work outside the United States ({snippet(text, match.start(), match.end())!r})"
