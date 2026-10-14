from redactator import brain, detect, ner
from redactator.categories import Options, split_list
from redactator.model import Line, Page, Word


def page_of(*texts):
    lines = []
    for y, t in enumerate(texts):
        words, x = [], 0
        for w in t.split():
            words.append(Word(w, (x, y * 20, x + 10 * len(w), y * 20 + 16)))
            x += 10 * len(w) + 10
        lines.append(Line(words))
    return Page(0, 1000, 1000, lines)


def run(page, options, monkeypatch):
    monkeypatch.setattr(brain, "available", lambda: False)
    monkeypatch.setattr(ner, "find", lambda text, labels: [])
    return detect.find([page], options, "image")


def test_your_list_survives_ocr_slips(monkeypatch):
    page = page_of("Matricula 9256 YT aparcado", "otro coche 9256VT", "nada aqui 1234AB")
    found = run(page, Options(hide=[], also=["9256YT"]), monkeypatch)
    texts = sorted(f.text for f in found)
    assert texts == ["9256 YT", "9256VT"]


def test_keep_wins_over_rules(monkeypatch):
    page = page_of("Write to hello@sidequest.studio or d.okafor@brightlane.io")
    found = run(page, Options(hide=["emails"], keep=["sidequest"]), monkeypatch)
    assert [f.text for f in found] == ["d.okafor@brightlane.io"]


def test_unticked_category_is_ignored(monkeypatch):
    page = page_of("Call +34 612 345 678 or mail a@b.co")
    found = run(page, Options(hide=["emails"]), monkeypatch)
    assert [f.label for f in found] == ["Emails"]


def test_split_list():
    assert split_list('9256YT, "Acme Corp"\nmy client\'s company') == ["9256YT", "Acme Corp", "my client's company"]


def test_unticking_a_long_finding_keeps_the_short_one_hidden(monkeypatch):
    page = page_of("Bill to Daniel Okafor, Brightlane Ltd", "Daniel Okafor called again")
    found = run(page, Options(hide=[], also=["Daniel Okafor, Brightlane", "Daniel Okafor"]), monkeypatch)
    long = next(f for f in found if "Brightlane" in f.text)
    short = next(f for f in found if f.text == "Daniel Okafor")
    long.enabled = False
    first_line = [b for b in short.boxes[0] if b[1] < 16]
    assert first_line, "the name inside the long finding lost its own box"
