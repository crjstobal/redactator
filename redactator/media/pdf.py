"""PDFs, with true redaction: the text under each box is deleted, not just covered."""

from __future__ import annotations

import numpy as np
import pymupdf
from PIL import Image

from .. import faces, ocr
from ..model import Line, Page, Plan, Word

EXTENSIONS = {".pdf"}
OCR_DPI = 200


def _native_lines(page: pymupdf.Page) -> list[Line]:
    groups: dict[tuple[int, int], list[Word]] = {}
    for x0, y0, x1, y1, text, block, line, _ in page.get_text("words", sort=True):
        groups.setdefault((block, line), []).append(Word(text, (x0, y0, x1, y1)))
    return [Line(ws) for ws in groups.values()]


def _render(page: pymupdf.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3]


def _image_area_ratio(page: pymupdf.Page) -> float:
    area = page.rect.width * page.rect.height or 1
    total = 0.0
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) & page.rect
        total += r.width * r.height
    return total / area


def _scale_lines(lines: list[Line], s: float) -> list[Line]:
    return [Line([Word(w.text, tuple(v * s for v in w.box)) for w in l.words]) for l in lines]


def load(path: str, want_faces: bool, progress=None) -> tuple[list[Page], dict]:
    pages = []
    with pymupdf.open(path) as doc:
        for page in doc:
            if progress:
                progress(f"Reading page {page.number + 1} of {doc.page_count}")
            lines = _native_lines(page)
            raster = None
            # Scanned pages and screenshots pasted into a PDF have no text layer: OCR them.
            if not lines or _image_area_ratio(page) > 0.2:
                raster = _render(page, OCR_DPI)
                ocr_lines = _scale_lines(ocr.read_lines(raster), 72 / OCR_DPI)
                if lines:
                    native = [w.box for l in lines for w in l.words]

                    def covered(l: Line) -> bool:
                        cx = (l.words[0].box[0] + l.words[-1].box[2]) / 2
                        cy = (l.words[0].box[1] + l.words[0].box[3]) / 2
                        return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in native)

                    ocr_lines = [l for l in ocr_lines if not covered(l)]
                lines += ocr_lines
            p = Page(page.number, page.rect.width, page.rect.height, lines)
            if want_faces:
                img = raster if raster is not None else _render(page, 110)
                s = page.rect.width / img.shape[1]
                p.faces = [tuple(v * s for v in b) for b in faces.find_faces(img)]
            pages.append(p)
    return pages, {}


def preview(plan: Plan, index: int) -> Image.Image:
    with pymupdf.open(plan.path) as doc:
        page = doc[index]
        zoom = 1400 / max(page.rect.width, page.rect.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def export(plan: Plan, out_path: str, progress=None) -> None:
    with pymupdf.open(plan.path) as doc:
        for page in doc:
            boxes = [pymupdf.Rect(b) for b in plan.boxes_on(page.number)]
            if not boxes:
                continue
            if progress:
                progress(f"Redacting page {page.number + 1} of {doc.page_count}")
            for r in boxes:
                page.add_redact_annot(r, fill=(0, 0, 0))
            # A clickable mailto: or https link under a box would still leak the data.
            for link in page.get_links():
                if any(pymupdf.Rect(link["from"]).intersects(r) for r in boxes):
                    page.delete_link(link)
            page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )
        doc.set_metadata({})
        doc.del_xml_metadata()
        doc.save(out_path, garbage=4, deflate=True, clean=True)
