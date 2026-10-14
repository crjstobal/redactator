"""Runs every detector the user's choices call for and merges them into Findings."""

from __future__ import annotations

import hashlib
import re

from . import brain, ner, rules
from .categories import CATEGORIES, Options
from .model import Finding, Line, Page, pad

YOUR_LIST = "Your list"

# GLiNER sometimes tags a column header ("Email", "Phone") as the data itself.
_SHAPE = {
    "email": lambda t: "@" in t,
    "ip_address": lambda t: sum(c.isdigit() for c in t) >= 4,
}
for _label in ("phone_number", "card_number", "card_cvv", "bank_account", "iban", "routing_number",
               "national_id_number", "passport_number", "drivers_license_number", "tax_id", "government_id",
               "date_of_birth", "street_address"):
    _SHAPE[_label] = lambda t: any(c.isdigit() for c in t)


def _fid(*parts: str) -> str:
    return hashlib.sha1("\x00".join(parts).encode()).hexdigest()[:10]


def _locate(line_text: str, needle: str) -> list[tuple[int, int]]:
    """Every occurrence of needle in the line, tolerant to case and spacing."""
    if not needle:
        return []
    spans = [(m.start(), m.end()) for m in re.finditer(re.escape(needle), line_text, re.I)]
    if spans:
        return spans
    loose = r"\s*".join(re.escape(c) for c in needle if not c.isspace())
    return [(m.start(), m.end()) for m in re.finditer(loose, line_text, re.I)] if loose else []


def _edit_distance(a: str, b: str, cap: int = 2) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _locate_fuzzy(line_text: str, needle: str) -> list[tuple[int, int]]:
    """Like _locate, but also accepts one OCR slip (9256YT read as 9256VT) for 5+ characters."""
    spans = _locate(line_text, needle)
    target = "".join(needle.lower().split())
    if spans or len(target) < 5:
        return spans
    chars = [(c.lower(), i) for i, c in enumerate(line_text) if not c.isspace()]
    compact = "".join(c for c, _ in chars)
    out: list[tuple[int, int]] = []
    n = len(target)
    i = 0
    while i < len(compact):
        hit = None
        for size in (n, n - 1, n + 1):
            seg = compact[i : i + size]
            if len(seg) == size and _edit_distance(seg, target, 1) <= 1:
                hit = size
                break
        if hit:
            out.append((chars[i][1], chars[i + hit - 1][1] + 1))
            i += hit
        else:
            i += 1
    return out


def find(pages: list[Page], options: Options, kind: str, progress=None) -> list[Finding]:
    findings: dict[str, Finding] = {}
    # moving text in videos needs a wider margin than a still page
    margin = 0.3 if kind == "video" else 0.15
    keep = [k.lower() for k in options.keep if k.strip()]
    cats = options.selected

    taken: dict[int, list[tuple[int, int]]] = {}  # id(line) -> spans already hidden

    def add(label: str, text: str, source: str, page: Page, line: Line, start: int, end: int):
        low = text.lower().strip()
        if not low or any(k in low or low in k for k in keep):
            return
        spans = taken.setdefault(id(line), [])
        if any(s <= start and end <= e for s, e in spans):
            return  # already hidden by an earlier detector, don't count it twice
        spans.append((start, end))
        key = _fid(label, low)
        f = findings.get(key)
        if f is None:
            f = findings[key] = Finding(key, label, text.strip(), source)
        f.hits += 1
        for box in line.boxes_for_span(start, end):
            amount = max(1.0, (box[3] - box[1]) * margin)
            f.add(page.index, pad(box, amount, page.width, page.height))

    flat: list[tuple[Page, Line]] = [(p, l) for p in pages for l in p.lines]
    unique = list(dict.fromkeys(l.text for _, l in flat))

    # 1. fixed patterns and the user's own list: cheap, run on every line
    rule_owner = {r: c.title for c in cats for r in c.rules}
    for page, line in flat:
        for m in rules.find(line.text, list(rule_owner)):
            add(rule_owner[m.label], m.text, "rules", page, line, m.start, m.end)
        for item in options.also:
            for s, e in _locate_fuzzy(line.text, item):
                add(YOUR_LIST, line.text[s:e], "you", page, line, s, e)

    # 2. the small PII model and Gemma both propose strings; anything either of
    # them recognises is then hidden everywhere it appears in the file
    proposals: dict[str, tuple[str, str]] = {}  # text -> (category title, source)

    gliner_owner = {g: c.title for c in cats for g in c.gliner}
    if gliner_owner and unique:
        if progress:
            progress(f"Checking {len(unique)} lines for personal data")
        for text in unique:
            for s, e, label in ner.find(text, list(gliner_owner)):
                if _SHAPE.get(label, lambda t: True)(text[s:e]):
                    proposals.setdefault(text[s:e], (gliner_owner[label], "pii model"))

    gemma_owner = {c.gemma: c.title for c in cats if c.gemma}
    gemma_owner.update({d: YOUR_LIST for d in options.descriptions})
    if gemma_owner and unique and brain.available():
        if progress:
            progress(f"Gemma is reading {len(unique)} lines")
        for _, sub, label in brain.classify(unique, list(gemma_owner), options.keep):
            title = gemma_owner.get(label) or next(
                (t for d, t in gemma_owner.items() if d.lower() in label.lower() or label.lower() in d.lower()), None
            )
            if title:
                proposals.setdefault(sub, (title, "gemma"))

    ordered = sorted(proposals.items(), key=lambda kv: -len(kv[0]))
    for page, line in flat:
        for sub, (title, source) in ordered:
            if len(sub.strip()) < 3:  # a stray "a" must not black out every line
                continue
            for s, e in _locate(line.text, sub):
                add(title, line.text[s:e], source, page, line, s, e)

    # 3. faces
    if options.faces:
        if kind == "video":
            f = Finding(_fid("faces"), "Faces", "Every face in the video", "faces")
            for p in pages:
                for b in p.faces:
                    f.add(p.index, b)
                    f.hits += 1
            if f.count:
                findings[f.id] = f
        else:
            n = 0
            for p in pages:
                for b in p.faces:
                    n += 1
                    f = Finding(_fid("face", str(p.index), str(n)), "Faces", f"Face {n}", "faces", hits=1)
                    f.add(p.index, b)
                    findings[f.id] = f

    _drop_contained(findings)
    order = {c.title: i for i, c in enumerate(CATEGORIES.values())}
    order[YOUR_LIST] = -1
    return sorted(findings.values(), key=lambda f: (order.get(f.label, 99), f.text.lower()))


def _drop_contained(findings: dict[str, Finding]) -> None:
    """'Daniel Okafor' and 'Daniel Okafor, Brightlane' both found: keep the list readable.

    Only drops a finding of the same category whose every box already sits
    inside a box of the longer one, so nothing becomes visible.
    """

    def inside(a, b):
        return a[0] >= b[0] - 1 and a[1] >= b[1] - 1 and a[2] <= b[2] + 1 and a[3] <= b[3] + 1

    items = list(findings.values())
    for f in items:
        for g in items:
            if f is g or f.label != g.label or f.id not in findings or g.id not in findings:
                continue
            if len(f.text) < len(g.text) and f.text.lower() in g.text.lower():
                if all(any(inside(b, gb) for gb in g.boxes.get(p, [])) for p, bs in f.boxes.items() for b in bs):
                    del findings[f.id]
