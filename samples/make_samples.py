"""Generate fictional sample files to try Redactator on. All data here is made up."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent

ROWS = [
    ("Order", "Customer", "Email", "Phone"),
    ("#48213", "Maria Lopez Garcia", "maria.lopez@acme-corp.com", "+34 612 345 678"),
    ("#48214", "Daniel Okafor", "d.okafor@brightlane.io", "+44 7700 900123"),
    ("#48215", "Sofia Papadopoulou", "sofia.p@olivegrove.gr", "+30 694 123 4567"),
    ("#48216", "James Whitfield", "jwhitfield@harbourfreight.co", "(415) 555-0142"),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("Arial.ttf", "Helvetica.ttc", "DejaVuSans.ttf", "arial.ttf"):
        for base in ("/System/Library/Fonts/Supplemental/", "/System/Library/Fonts/", "/usr/share/fonts/truetype/dejavu/", "C:/Windows/Fonts/"):
            try:
                return ImageFont.truetype(base + name, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def dashboard(width=1280, height=800, offset=0) -> Image.Image:
    """A fake CRM screen, the kind freelancers record for tutorials."""
    im = Image.new("RGB", (width, height), "#f4f5f7")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, width, 56], fill="#1f2937")
    d.text((24, 16), "BrightDesk CRM   >   Orders", fill="white", font=_font(22))
    d.text((width - 330, 18), "Signed in as anna.berg@brightdesk.app", fill="#cbd5e1", font=_font(16))
    y = 100 - offset
    big, small = _font(20), _font(18)
    for r, row in enumerate(ROWS * 3):
        if r and row[0] == "Order":
            continue
        if 56 < y < height - 40:
            if r == 0:
                d.rectangle([40, y - 8, width - 40, y + 30], fill="#e5e7eb")
            xs = [56, 190, 470, 860]
            for x, cell in zip(xs, row):
                d.text((x, y), cell, fill="#111827", font=big if r == 0 else small)
        y += 56
    d.rectangle([40, height - 120 - offset // 3, 760, height - 40 - offset // 3], fill="white", outline="#d1d5db")
    d.text((60, height - 108 - offset // 3), "Payment on file: VISA 4111 1111 1111 1111  exp 09/28", fill="#111827", font=small)
    d.text((60, height - 76 - offset // 3), "Billing: 221B Baker Street, London NW1 6XE", fill="#111827", font=small)
    return im


def make_png():
    im = dashboard()
    im.save(HERE / "crm-screenshot.png")


def make_pdf():
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    lines = [
        "INVOICE 2026-0117",
        "",
        "Bill to: Daniel Okafor, Brightlane Studio Ltd.",
        "14 Canal Road, Leeds LS12 2PJ, United Kingdom",
        "Email: d.okafor@brightlane.io   Phone: +44 7700 900123",
        "",
        "Video editing, 3 tutorial episodes ............ 1,350.00 EUR",
        "On-site shoot, courtesy car plate 9256 YT",
        "",
        "Pay to IBAN: ES91 2100 0418 4502 0005 1332",
        "Questions? Write to hello@sidequest.studio",
    ]
    for text in lines:
        page.insert_text((72, y), text, fontsize=12)
        y += 22
    link_rect = pymupdf.Rect(72, y - 34, 360, y - 18)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": link_rect, "uri": "mailto:hello@sidequest.studio"})
    # A pasted screenshot: text that only exists as pixels
    png = HERE / "crm-screenshot.png"
    page.insert_image(pymupdf.Rect(72, y + 10, 540, y + 10 + 468 * 800 / 1280), filename=str(png))
    doc.set_metadata({"author": "Javier Sample", "title": "Invoice for Daniel Okafor"})
    doc.save(HERE / "invoice.pdf")


def make_video(seconds=6, fps=30):
    out = HERE / "crm-recording.mp4"
    w, h = 1280, 800
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = seconds * fps
    for i in range(n):
        # still for 2 s, scroll for 2 s, still for 2 s
        t = i / fps
        offset = 0 if t < 2 else int(min(1.0, (t - 2) / 2) * 220)
        proc.stdin.write(np.asarray(dashboard(w, h, offset)).tobytes())
    proc.stdin.close()
    proc.wait()


if __name__ == "__main__":
    make_png()
    make_pdf()
    if "--no-video" not in sys.argv:
        make_video()
    print("samples written to", HERE)
