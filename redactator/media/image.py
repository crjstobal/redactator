"""Photos and screenshots."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .. import faces, ocr
from ..model import Page, Plan

EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def open_rgb(path: str) -> Image.Image:
    with Image.open(path) as im:
        return ImageOps.exif_transpose(im).convert("RGB")


def load(path: str, want_faces: bool, progress=None) -> tuple[list[Page], dict]:
    im = open_rgb(path)
    rgb = np.asarray(im)
    if progress:
        progress("Reading text")
    page = Page(0, im.width, im.height, ocr.read_lines(rgb))
    if want_faces:
        if progress:
            progress("Looking for faces")
        page.faces = faces.find_faces(rgb)
    return [page], {}


def preview(plan: Plan, index: int) -> Image.Image:
    return open_rgb(plan.path)


def export(plan: Plan, out_path: str, progress=None) -> None:
    im = open_rgb(plan.path)
    draw = ImageDraw.Draw(im)
    for box in plan.boxes_on(0):
        draw.rectangle([round(v) for v in box], fill=(0, 0, 0))
    # Rebuild from raw pixels so no EXIF, GPS, XMP or text chunks survive.
    clean = Image.fromarray(np.asarray(im))
    fmt = {".jpg": "JPEG", ".jpeg": "JPEG"}.get(out_path.lower()[out_path.rfind(".") :], None)
    if fmt == "JPEG":
        clean.save(out_path, "JPEG", quality=95)
    else:
        clean.save(out_path)
