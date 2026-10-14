"""End-to-end checks that need no model: rules only, real files."""

import numpy as np
import pymupdf
from PIL import Image

from redactator import brain, engine, ner
from redactator.categories import Options

OPTS = Options(hide=["emails", "phones", "money"])


def _no_model(monkeypatch):
    """Rules only: these tests must pass without Ollama or the PII model."""
    monkeypatch.setattr(brain, "available", lambda: False)
    monkeypatch.setattr(ner, "find", lambda text, labels: [])


def test_pdf_text_is_really_removed(tmp_path, monkeypatch):
    _no_model(monkeypatch)
    src = tmp_path / "in.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Write to d.okafor@brightlane.io or call +44 7700 900123", fontsize=12)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 60, 400, 76), "uri": "mailto:d.okafor@brightlane.io"})
    doc.set_metadata({"author": "Someone Private"})
    doc.save(src)

    plan = engine.analyse(str(src), OPTS)
    out = engine.export(plan, str(tmp_path / "out.pdf"))

    with pymupdf.open(out) as red:
        text = red[0].get_text()
        assert "okafor" not in text and "7700" not in text
        assert "Write to" in text  # the rest of the line survives
        assert red[0].get_links() == []
        assert not red.metadata.get("author")


def test_image_boxes_are_opaque_and_metadata_dropped(tmp_path, monkeypatch):
    _no_model(monkeypatch)
    from samples.make_samples import dashboard

    src = tmp_path / "in.png"
    dashboard().save(src)
    plan = engine.analyse(str(src), OPTS)
    assert any(f.label == "Emails" for f in plan.findings)
    out = engine.export(plan, str(tmp_path / "out.png"))

    im = np.asarray(Image.open(out).convert("RGB"))
    x0, y0, x1, y1 = (int(v) for v in plan.boxes_on(0)[0])
    assert im[y0 + 2 : y1 - 2, x0 + 2 : x1 - 2].max() == 0  # solid black, no blur
    assert not Image.open(out).info.get("exif")


def test_never_overwrites_original(tmp_path, monkeypatch):
    _no_model(monkeypatch)
    src = tmp_path / "in.png"
    Image.new("RGB", (50, 50), "white").save(src)
    plan = engine.analyse(str(src), OPTS)
    try:
        engine.export(plan, str(src))
    except ValueError:
        return
    raise AssertionError("export overwrote the original")
