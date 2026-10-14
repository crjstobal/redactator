"""Public entry points: analyse a file into a Plan, preview it, export it."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from . import brain, detect, ner
from .categories import Options
from .media import image, pdf, video
from .model import ALL_PAGES, Box, Finding, Plan

HANDLERS = {"image": image, "pdf": pdf, "video": video}


def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    for kind, mod in HANDLERS.items():
        if ext in mod.EXTENSIONS:
            return kind
    raise ValueError(f"Unsupported file type: {ext or path}")


def default_output(path: str) -> str:
    p = Path(path)
    ext = ".mp4" if kind_of(path) == "video" else p.suffix
    return str(p.with_name(f"{p.stem}.redacted{ext}"))


def analyse(path: str, options: Options | None = None, progress=None) -> Plan:
    options = options or Options()
    kind = kind_of(path)
    t0 = time.time()
    pages, meta = HANDLERS[kind].load(path, options.faces, progress)
    findings = detect.find(pages, options, kind, progress)
    meta.update(
        options=options.__dict__,
        model=brain.MODEL if brain.available() else None,
        pii_model=ner.MODEL if ner.available() else None,
        seconds=round(time.time() - t0, 1),
    )
    return Plan(str(path), kind, json.dumps(options.__dict__), pages, findings, meta)


def preview(plan: Plan, index: int = 0) -> Image.Image:
    return HANDLERS[plan.kind].preview(plan, index)


def add_manual_box(plan: Plan, page: int, box: Box) -> Finding:
    """A box drawn by hand. On videos it covers the same spot on every frame."""
    n = sum(1 for f in plan.findings if f.source == "manual") + 1
    f = Finding(f"manual{n}", "manual", f"box {n}", "manual")
    f.add(ALL_PAGES if plan.kind == "video" else page, box)
    plan.findings.insert(0, f)
    return f


def export(plan: Plan, out_path: str | None = None, progress=None) -> str:
    out = out_path or default_output(plan.path)
    if Path(out).resolve() == Path(plan.path).resolve():
        raise ValueError("Refusing to overwrite the original file")
    HANDLERS[plan.kind].export(plan, out, progress)
    return out


def peek(path: str, index: int = 0) -> tuple[Image.Image, int]:
    """A page or the first frame of a file that has not been analysed yet, plus its page count."""
    kind = kind_of(path)
    if kind == "image":
        return image.open_rgb(path), 1
    if kind == "pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            page = doc[max(0, min(index, doc.page_count - 1))]
            zoom = 1400 / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples), doc.page_count
    import cv2

    cap = cv2.VideoCapture(path)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise ValueError("Cannot read video")
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), 1
