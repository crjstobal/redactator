"""Local OCR with RapidOCR (PaddleOCR models on ONNX Runtime). No network, no GPU needed."""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from .model import Line, Word

MIN_SCORE = 0.5


@lru_cache(maxsize=1)
def _engine():
    from rapidocr import RapidOCR

    engine = RapidOCR()
    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    return engine


def _axis_box(points) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _split_evenly(text: str, box) -> list[Word]:
    """Fallback when the engine gives no word boxes: share the line box by character count."""
    parts = text.split()
    if not parts:
        return []
    x0, y0, x1, y1 = box
    total = len(text)
    words, pos = [], 0
    for p in parts:
        start = text.index(p, pos)
        end = start + len(p)
        words.append(Word(p, (x0 + (x1 - x0) * start / total, y0, x0 + (x1 - x0) * end / total, y1)))
        pos = end
    return words


def read_lines(image: np.ndarray) -> list[Line]:
    """OCR an RGB image into lines of words with pixel boxes."""
    result = _engine()(image, return_word_box=True)
    if result is None or result.txts is None:
        return []
    word_results = result.word_results or [()] * len(result.txts)
    lines = []
    for text, score, box, words in zip(result.txts, result.scores, result.boxes, word_results):
        if score < MIN_SCORE or not text.strip():
            continue
        parsed = [Word(w[0], _axis_box(w[2])) for w in words if w and w[0].strip()]
        if not parsed or " ".join(w.text for w in parsed).replace(" ", "") != text.replace(" ", ""):
            parsed = _split_evenly(text, _axis_box(box))
        if parsed:
            lines.append(Line(parsed))
    return lines
