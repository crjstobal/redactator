"""GLiNER2-PII: a 0.2B open model (Apache 2.0) trained only to find personal data.

It has very high recall on names, which is exactly where a general LLM like
Gemma sometimes skips a line. Weights are downloaded once from Hugging Face and
then run offline on CPU.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

MODEL = os.environ.get("REDACTATOR_NER", "fastino/gliner2-privacy-filter-PII-multi")
THRESHOLD = 0.5
# names are where the model over-predicts ("Customer", product names), so ask for more confidence
STRICT = {"person": 0.8}

_cache: dict[tuple, list[tuple[int, int, str]]] = {}


@lru_cache(maxsize=1)
def _model():
    try:
        logging.getLogger("transformers").setLevel(logging.ERROR)
        from gliner2 import GLiNER2

        return GLiNER2.from_pretrained(MODEL)
    except Exception:
        return None


def available() -> bool:
    return _model() is not None


def find(text: str, labels: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, label) spans in `text` for the requested GLiNER labels."""
    if not labels or not text.strip():
        return []
    key = (text, tuple(sorted(labels)))
    if key in _cache:
        return _cache[key]
    model = _model()
    out: list[tuple[int, int, str]] = []
    if model is not None:
        try:
            result = model.extract_entities(
                text, labels, threshold=THRESHOLD, include_confidence=True, include_spans=True
            )
            for label, items in (result.get("entities") or {}).items():
                for it in items:
                    if it.get("confidence", 1.0) < STRICT.get(label, THRESHOLD):
                        continue
                    s, e = it.get("start"), it.get("end")
                    if s is None or e is None or e <= s:
                        continue
                    out.append((s, e, label))
        except Exception:
            out = []
    _cache[key] = out
    return out
