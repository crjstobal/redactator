"""Gemma 4 running locally through Ollama: the detector that reads with judgement.

Given OCR'd lines and a few category descriptions ("people's names",
"my client's company"), it returns the exact substrings to hide. It covers what
fixed patterns cannot, and what the small PII model does not know about.

Nothing leaves the machine: Ollama serves the open-weight model on localhost.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

from pydantic import BaseModel

MODEL = os.environ.get("REDACTATOR_MODEL", "gemma4:e4b")
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
BATCH = 20  # lines per model call; recall drops on longer batches


class _Hit(BaseModel):
    line: int
    text: str
    label: str


class _Hits(BaseModel):
    hits: list[_Hit]


@lru_cache(maxsize=1)
def _client():
    from ollama import Client

    return Client(host=HOST, timeout=180)


def available() -> bool:
    try:
        names = [m.model for m in _client().list().models]
        return any(n == MODEL or n.split(":")[0] == MODEL for n in names)
    except Exception:
        return False


def _extract_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model reply")
    return text[start : end + 1]


def _ask(system: str, user: str, schema: type[BaseModel]) -> BaseModel:
    # Ollama's constrained decoding is not available for every model, so the
    # schema goes in the prompt and the reply is validated (one retry).
    system = f"{system}\nReply with one JSON object matching this JSON schema:\n{json.dumps(schema.model_json_schema())}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_error = None
    for _ in range(2):
        resp = _client().chat(
            model=MODEL,
            messages=messages,
            options={"temperature": 0, "num_ctx": 8192},
            think=False,
            keep_alive="10m",
        )
        try:
            return schema.model_validate_json(_extract_json(resp.message.content))
        except Exception as e:
            last_error = e
            messages += [
                {"role": "assistant", "content": resp.message.content},
                {"role": "user", "content": f"That was not valid ({e}). Reply with the JSON object only."},
            ]
    raise last_error


_SYSTEM = """You find private information in text read from a screen, photo or document.
Hide these categories: {cats}.
Emails, phone numbers, card numbers, IBANs and IP addresses are handled by another tool: skip them.
Never hide: {keep}; UI labels such as "Name:" or "Email"; generic words; software or brand names unless a category asks for them.
For each numbered line, return every exact substring (copied character for character) that belongs to a category to hide.
Return complete spans: a whole street address with number and postcode, a full name with all surnames, a full company name.
`label` is the category exactly as listed above.
If nothing matches, return an empty list. Return JSON only."""


_cache: dict[tuple, list[tuple[str, str]]] = {}


def classify(lines: list[str], categories: list[str], keep: list[str] | None = None) -> list[tuple[int, str, str]]:
    """Return (line index, exact substring, category) for every hit."""
    if not categories or not lines or not available():
        return []
    keep = keep or []
    key_base = (tuple(categories), tuple(keep))
    hits: list[tuple[int, str, str]] = []
    todo = []
    for i, text in enumerate(lines):
        cached = _cache.get(key_base + (text,))
        if cached is None:
            todo.append(i)
        else:
            hits.extend((i, t, l) for t, l in cached)
    system = _SYSTEM.format(cats="; ".join(categories), keep="; ".join(keep) or "nothing in particular")
    for start in range(0, len(todo), BATCH):
        chunk = todo[start : start + BATCH]
        user = "\n".join(f"{n}: {lines[i]}" for n, i in enumerate(chunk))
        found: dict[int, list[tuple[str, str]]] = {i: [] for i in chunk}
        try:
            out = _ask(system, user, _Hits)
            for h in out.hits:
                if 0 <= h.line < len(chunk) and h.text.strip():
                    found[chunk[h.line]].append((h.text.strip(), h.label.strip()))
        except Exception:
            pass
        for i, items in found.items():
            _cache[key_base + (lines[i],)] = items
            hits.extend((i, t, l) for t, l in items)
    return hits
