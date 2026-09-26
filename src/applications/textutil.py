"""Text cleanup shared by screening and drafting."""

import html
import re

_TAG = re.compile(r"(?is)<(script|style)\b.*?>.*?</\1>")
_MARKUP = re.compile(r"(?s)<[^>]+>")
_SPACE = re.compile(r"\s+")


def normalize(value: str) -> str:
    text = html.unescape(value or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    text = _SPACE.sub(" ", text).strip()
    for source, dest in (
        ("fullstack", "full stack"),
        ("backend", "back end"),
        ("frontend", "front end"),
    ):
        text = re.sub(rf"\b{source}\b", dest, text)
    return _SPACE.sub(" ", text).strip()


def has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None


def strip_html(value: str) -> str:
    text = _TAG.sub(" ", value or "")
    text = _MARKUP.sub(" ", text)
    text = html.unescape(text).replace("\xa0", " ")
    return _SPACE.sub(" ", text).strip()


def snippet(text: str, start: int, end: int, pad: int = 70) -> str:
    chunk = text[max(0, start - pad) : min(len(text), end + pad)]
    return _SPACE.sub(" ", chunk).strip()


def trim_posting(value: str, limit: int = 7000) -> str:
    text = strip_html(value)
    if len(text) <= limit:
        return text
    head = text[:2000]
    lower = text.lower()
    index = -1
    for needle in (
        "minimum qualifications",
        "requirements",
        "qualifications",
        "what you'll need",
        "what you will need",
    ):
        found = lower.find(needle)
        if found != -1:
            index = found
            break
    if index == -1:
        return text[:limit]
    tail_budget = max(0, limit - len(head) - 2)
    return f"{head}\n\n{text[index : index + tail_budget]}"
