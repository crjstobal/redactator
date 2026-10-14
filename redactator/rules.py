"""Deterministic detectors for data with a fixed shape.

These never depend on the model, so an email address is always caught even if
the model has a bad day. Gemma decides which of these to switch on and handles
everything that needs judgement (names, companies, addresses...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    pattern: re.Pattern
    check: callable = None


RULES: dict[str, Rule] = {
    r.name: r
    for r in [
        Rule("email", "email addresses", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
        Rule(
            "credit card",
            "payment card numbers",
            re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
            lambda s: 13 <= len(_digits(s)) <= 19 and _luhn_ok(_digits(s)),
        ),
        Rule(
            "card expiry and cvv",
            "card expiry dates and security codes",
            re.compile(r"(?i)\b(?:exp(?:iry|ires)?|valid thru|cvv|cvc|cv2)\b[:\s]*[\d/]{3,7}"),
        ),
        Rule(
            "iban",
            "bank account numbers (IBAN)",
            re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"),
        ),
        Rule(
            "phone",
            "phone numbers",
            re.compile(r"(?<![\w.])\+?\(?\d[\d\s().-]{6,}\d(?![\w.])"),
            lambda s: 9 <= len(_digits(s)) <= 15,
        ),
        Rule("us ssn", "US social security numbers", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
        Rule("ip address", "IP addresses", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
        Rule(
            "secret",
            "API keys, tokens and passwords shown on screen",
            re.compile(
                r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}"
                r"|xox[abpr]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})"
            ),
        ),
        Rule(
            "password",
            "passwords written next to a label",
            re.compile(r"(?i)(?<=\bpassword[:\s])\s*\S+|(?<=\bpass[:\s])\s*\S+|(?<=\bpwd[:\s])\s*\S+"),
        ),
        Rule(
            "licence plate",
            "vehicle licence plates (ES, UK, FR, IT formats)",
            re.compile(
                r"\b\d{4}[ -]?[BCDFGHJKLMNPRSTVWXYZ]{3}\b"  # ES 1234 BCD
                r"|\b[A-Z]{2}\d{2} ?[A-Z]{3}\b"  # UK AB12 CDE
                r"|\b[A-Z]{2}[ -]\d{3}[ -][A-Z]{2}\b"  # FR AB-123-CD, IT AB 123 CD
            ),
        ),
        Rule(
            "url with private data",
            "links that carry tokens, ids or emails in the query string",
            re.compile(r"(?i)\bhttps?://\S+[?&](?:token|key|id|email|session|auth|code|sig)=\S+"),
        ),
    ]
}


@dataclass
class Match:
    start: int
    end: int
    label: str
    text: str


def find(text: str, enabled: list[str]) -> list[Match]:
    """All non-overlapping matches of the enabled rules, in rule order of priority."""
    taken: list[tuple[int, int]] = []
    out = []
    for name in enabled:
        rule = RULES.get(name)
        if not rule:
            continue
        for m in rule.pattern.finditer(text):
            s, e = m.start(), m.end()
            seg = m.group(0).strip()
            if not seg or (rule.check and not rule.check(seg)):
                continue
            if any(s < te and ts < e for ts, te in taken):
                continue
            # trim leading whitespace from lookbehind-style rules
            s += len(m.group(0)) - len(m.group(0).lstrip())
            taken.append((s, e))
            out.append(Match(s, e, rule.name, text[s:e]))
    return out
