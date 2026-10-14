"""Core data model shared by every media type.

A file is turned into a list of Pages (an image, a PDF page or a sampled video
frame). Each page holds text Lines made of Words with boxes in page coordinates
(pixels for images and video, PDF points for PDF pages). Detectors produce
Findings, and every Finding owns the boxes that will be painted solid black.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

Box = tuple[float, float, float, float]  # x0, y0, x1, y1
ALL_PAGES = -1  # boxes stored under this key apply to every page or frame


def union(boxes: list[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def pad(box: Box, amount: float, width: float, height: float) -> Box:
    return (
        max(0.0, box[0] - amount),
        max(0.0, box[1] - amount),
        min(width, box[2] + amount),
        min(height, box[3] + amount),
    )


@dataclass
class Word:
    text: str
    box: Box


@dataclass
class Line:
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    def word_spans(self) -> list[tuple[int, int]]:
        """Character span of each word inside `self.text`."""
        spans, pos = [], 0
        for w in self.words:
            spans.append((pos, pos + len(w.text)))
            pos += len(w.text) + 1
        return spans

    def boxes_for_span(self, start: int, end: int) -> list[Box]:
        """Boxes covering the characters [start, end) of the line text.

        Words that are only partly covered get a proportional sub-box, so
        "Email:john@x.com" read as one word still only hides the address.
        """
        out = []
        for w, (ws, we) in zip(self.words, self.word_spans()):
            s, e = max(start, ws), min(end, we)
            if s >= e:
                continue
            x0, y0, x1, y1 = w.box
            n = max(1, we - ws)
            fx0 = x0 + (x1 - x0) * (s - ws) / n
            fx1 = x0 + (x1 - x0) * (e - ws) / n
            out.append((fx0, y0, fx1, y1))
        # One solid bar per span: gaps between words would hint at word lengths.
        return [union(out)] if out else []


@dataclass
class Page:
    index: int
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)
    faces: list[Box] = field(default_factory=list)
    time: Optional[float] = None  # seconds, video frames only


@dataclass
class Finding:
    id: str
    label: str  # e.g. "email", "person name", "face", "manual"
    text: str  # what was found ("" for faces and manual boxes)
    source: str  # "rules", "gemma", "faces", "manual"
    boxes: dict[int, list[Box]] = field(default_factory=dict)  # page index -> boxes
    enabled: bool = True
    hits: int = 0  # occurrences; one occurrence can span several word boxes

    def add(self, page: int, box: Box) -> None:
        self.boxes.setdefault(page, []).append(box)

    @property
    def count(self) -> int:
        return self.hits or sum(len(v) for v in self.boxes.values())


@dataclass
class Plan:
    """Everything needed to preview and export a redaction."""

    path: str
    kind: str  # "image", "pdf", "video"
    instruction: str
    pages: list[Page]
    findings: list[Finding]
    meta: dict = field(default_factory=dict)

    def boxes_on(self, page: int) -> list[Box]:
        out = []
        for f in self.findings:
            if f.enabled:
                out.extend(f.boxes.get(page, []))
                out.extend(f.boxes.get(ALL_PAGES, []))
        return out

    def summary(self) -> list[dict]:
        return [
            {
                "id": f.id,
                "label": f.label,
                "text": f.text,
                "source": f.source,
                "count": f.count,
                "enabled": f.enabled,
            }
            for f in self.findings
        ]

    def to_dict(self) -> dict:
        return asdict(self)
