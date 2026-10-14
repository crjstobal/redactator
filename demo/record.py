"""Records the demo video.

The real interface runs in headless Chromium. The Python bridge is replaced by
a scripted one, but everything it returns (findings, boxes, previews, exported
files) comes from real runs of the engine on the sample files. A fake cursor
and burned-in captions are drawn on top, and frames are captured with the
Chrome DevTools screencast, then assembled with ffmpeg.

    python demo/record.py            # writes demo/redactator-demo.mp4
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pymupdf  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from redactator import engine  # noqa: E402
from redactator.app.main import Api, Item  # noqa: E402
from redactator.categories import Options  # noqa: E402
from redactator.media.video import ffmpeg_exe  # noqa: E402

OUT = REPO / "demo" / "redactator-demo.mp4"
CAPTIONS = REPO / "demo" / "captions.json"
W, H = 1440, 810
SCALE = 4 / 3  # 1920x1080 frames
FILES = ["samples/invoice.pdf", "samples/crm-screenshot.png", "samples/crm-recording.mp4"]
OPTIONS = Options(also=["9256YT"], keep=["sidequest"])
MANUAL_BOX = [16, 8, 205, 48]  # the CRM logo in the screenshot, in image pixels


def precompute(work: Path) -> dict:
    api = Api()
    api.items = [Item(str(REPO / f)) for f in FILES]
    data: dict = {"status": api.status(), "filesWaiting": api._files()}
    data["peeks"] = [api.peek(i, 0) for i in range(len(FILES))]
    data["plans"], data["images"] = [], {}
    for i, it in enumerate(api.items):
        print(f"analysing {it.path}")
        it.plan = engine.analyse(it.path, OPTIONS)
        it.status = "done"
        pj = api._plan_json(i)
        data["plans"].append(pj)
        for pg in pj["pages"]:
            data["images"][f"{i}:{pg['index']}"] = api.page_image(i, pg["index"])
        data.setdefault("lines", []).append(len({l.text for p in it.plan.pages for l in p.lines}))
    data["filesDone"] = api._files()
    data["manual"] = api.add_box(1, 0, MANUAL_BOX)

    outs = []
    for it in api.items:
        out = work / Path(engine.default_output(it.path)).name
        engine.export(it.plan, str(out))
        outs.append(out)
    data["exported"] = [str(o) for o in outs]

    with pymupdf.open(outs[0]) as doc:
        page = doc[0]
        data["pdfText"] = page.get_text().strip()
        data["pdfImage"] = "data:image/png;base64," + base64.b64encode(page.get_pixmap(dpi=100).tobytes("png")).decode()

    webm = work / "after.webm"
    subprocess.run(
        [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(outs[2]), "-c:v", "libvpx-vp9", "-b:v", "3M", "-an", str(webm)],
        check=True,
    )
    data["afterVideo"] = webm.as_uri()
    return data


BRIDGE = """
const D = window.__D;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const copy = (xs) => xs.map((x) => ({ ...x }));
window.pywebview = { api: {
  status: async () => D.status,
  peek: async (f) => D.peeks[f],
  page_image: async (f, p) => D.images[f + ":" + p],
  toggle: async () => {}, choose_files: async () => {}, reveal: async () => {},
  remove_file: async () => D.filesWaiting,
  add_box: async () => D.manual,
  remove_manual: async (f) => D.plans[f],
  analyse: async () => {
    (async () => {
      const files = copy(D.filesWaiting);
      for (let i = 0; i < files.length; i++) {
        files[i].status = "reading";
        onFiles(copy(files));
        const name = files[i].name, n = D.lines[i], pre = `${name} (${i + 1} of ${files.length}): `;
        const steps = files[i].kind === "video"
          ? ["Scanning video 30%", "Scanning video 70%", `Checking ${n} lines for personal data`, `Gemma is reading ${n} lines`]
          : ["Reading text", `Checking ${n} lines for personal data`, `Gemma is reading ${n} lines`];
        for (const s of steps) { onProgress(pre + s); await sleep(650); }
        files[i] = { ...D.filesDone[i] };
        onFiles(copy(files));
        onPlan(D.plans[i]);
        await sleep(300);
      }
      onDone(copy(D.filesDone));
    })();
  },
  export: async () => {
    (async () => {
      for (const s of ["invoice.pdf (1 of 3): Redacting page 1 of 1", "crm-screenshot.png (2 of 3): Saving", "crm-recording.mp4 (3 of 3): Rendering 35%", "crm-recording.mp4 (3 of 3): Rendering 80%"]) {
        onProgress(s); await sleep(550);
      }
      onExported(D.exported);
    })();
    return true;
  },
}};
"""

OVERLAY_CSS = """
#demo-cursor { position: fixed; left: 0; top: 0; width: 30px; height: 30px; z-index: 1000; pointer-events: none;
  transform: translate(-4px, -2px); transition-property: left, top; transition-timing-function: cubic-bezier(.45,.05,.25,1); }
#demo-cursor.press::after { content: ""; position: absolute; left: -10px; top: -10px; width: 28px; height: 28px; border-radius: 50%;
  background: rgba(255, 225, 77, .55); animation: press .35s ease-out forwards; }
@keyframes press { from { transform: scale(.4); opacity: 1; } to { transform: scale(1.4); opacity: 0; } }
#demo-caption { position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%); z-index: 999; pointer-events: none;
  max-width: 980px; padding: 12px 22px; border-radius: 16px; background: rgba(35, 38, 74, .94); color: #fff;
  font: 600 24px/1.3 "Bricolage", sans-serif; text-align: center; opacity: 0; transition: opacity .25s; }
#demo-caption.on { opacity: 1; }
.demo-layer { position: fixed; inset: 0; z-index: 998; display: flex; align-items: center; justify-content: center;
  background: var(--fog); opacity: 0; pointer-events: none; transition: opacity .45s; }
.demo-layer.on { opacity: 1; }
#demo-card { flex-direction: column; text-align: center; gap: 6px; }
#demo-card img { width: 300px; }
#demo-card h1 { font: 800 74px/1 "Bricolage", sans-serif; font-stretch: 80%; letter-spacing: -0.02em; margin: 8px 0 6px; color: var(--navy); }
#demo-card p { font: 500 28px/1.35 "Bricolage", sans-serif; color: var(--navy-soft); margin: 0; max-width: 900px; }
#demo-card .small { font-size: 21px; margin-top: 18px; }
#demo-proof { gap: 40px; padding: 40px 60px 120px; }
#demo-proof img { height: 600px; box-shadow: 0 0 0 2px var(--line), 0 20px 50px -20px rgba(35,38,74,.4); background: #fff; }
#demo-proof .copy { width: 560px; }
#demo-proof h2 { font: 750 24px/1.2 "Bricolage", sans-serif; color: var(--navy); margin: 0 0 12px; }
#demo-proof pre { margin: 0; padding: 18px 20px; background: #fff; border: 2px solid var(--line); border-radius: 14px;
  font: 15px/1.5 ui-monospace, Menlo, monospace; color: var(--navy); white-space: pre-wrap; max-height: 520px; overflow: hidden; }
#demo-after { padding: 30px 60px 110px; }
#demo-after video { max-height: 640px; border-radius: 10px; box-shadow: 0 20px 50px -20px rgba(35,38,74,.5); }
.demo-file { position: fixed; z-index: 997; width: 150px; padding: 14px 12px; border-radius: 14px; background: #fff;
  border: 2px solid var(--navy); box-shadow: 0 14px 30px -12px rgba(35,38,74,.45); font: 600 14px "Bricolage", sans-serif;
  color: var(--navy); text-align: center; transition-property: left, top, transform, opacity; transition-timing-function: cubic-bezier(.45,.05,.25,1); }
.demo-file b { display: block; font-size: 30px; margin-bottom: 6px; }
"""

OVERLAY_JS = """
window.addEventListener("DOMContentLoaded", () => {
  const style = document.createElement("style");
  style.textContent = %s;
  document.head.append(style);
  document.body.insertAdjacentHTML("beforeend", `
    <div id="demo-caption"></div>
    <div class="demo-layer" id="demo-card"></div>
    <div class="demo-layer" id="demo-proof"></div>
    <div class="demo-layer" id="demo-after"></div>
    <svg id="demo-cursor" viewBox="0 0 24 24"><path d="M3 2l7.5 19 2.6-7.9L21 10.5z" fill="#23264A" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`);
});
""" % json.dumps(OVERLAY_CSS)


class Director:
    def __init__(self, page):
        self.page = page
        self.x, self.y = W * 0.62, H * 0.55
        self.captions: list[dict] = []
        self.t0 = None

    def wait(self, ms):
        self.page.wait_for_timeout(ms)

    def caption(self, text: str | None, hold: int = 0):
        if text:
            self.page.evaluate("t => { const c = document.getElementById('demo-caption'); c.textContent = t; c.classList.add('on'); }", text)
            self.captions.append({"text": text})
        else:
            self.page.evaluate("() => document.getElementById('demo-caption').classList.remove('on')")
        if hold:
            self.wait(hold)

    def move(self, x: float, y: float, ms: int = 700):
        self.page.evaluate(
            "([x, y, ms]) => { const c = document.getElementById('demo-cursor'); c.style.transitionDuration = ms + 'ms'; c.style.left = x + 'px'; c.style.top = y + 'px'; }",
            [x, y, ms],
        )
        self.x, self.y = x, y
        self.wait(ms + 60)

    def center(self, locator):
        b = locator.bounding_box()
        return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2

    def press(self):
        self.page.evaluate("() => { const c = document.getElementById('demo-cursor'); c.classList.remove('press'); void c.offsetWidth; c.classList.add('press'); }")

    def click(self, locator, ms: int = 700, pause: int = 250):
        x, y = self.center(locator)
        self.move(x, y, ms)
        self.press()
        self.page.mouse.click(x, y)
        self.wait(pause)

    def type(self, locator, text: str):
        self.click(locator)
        self.page.keyboard.type(text, delay=110)

    def layer(self, name: str, on: bool, html: str | None = None):
        if html is not None:
            self.page.evaluate("([n, h]) => { document.getElementById(n).innerHTML = h; }", [name, html])
        self.page.evaluate(
            "([n, on]) => { document.getElementById(n).classList.toggle('on', on); document.getElementById('demo-cursor').style.opacity = on ? 0 : 1; }",
            [name, on],
        )


def run_script(d: Director, data: dict):
    page = d.page
    q = page.locator

    # title
    d.layer("demo-card", True, """<img src="logo.svg" alt=""><h1>Redactator</h1>
      <p>Hide private data in photos, PDFs and videos, without uploading them anywhere.</p>""")
    d.move(W * 0.62, H * 0.55, 10)
    d.wait(3200)
    d.layer("demo-card", False)
    d.wait(500)

    d.caption("Client files are full of private data. Sending them to a cloud tool to clean them defeats the point.", 3600)

    # drop three files
    d.caption("Drop photos, PDFs and screen recordings. Several at once.")
    page.evaluate("""() => {
      const files = [["PDF", "invoice.pdf"], ["PNG", "crm-screenshot.png"], ["MP4", "crm-recording.mp4"]];
      files.forEach(([k, n], i) => {
        const el = document.createElement("div");
        el.className = "demo-file"; el.id = "demo-file-" + i;
        el.innerHTML = `<b>${k}</b>${n}`;
        el.style.left = (-200 - i * 30) + "px"; el.style.top = (300 + i * 70) + "px";
        el.style.transform = `rotate(${(i - 1) * 6}deg)`;
        document.body.append(el);
      });
    }""")
    d.move(60, 420, 500)
    page.evaluate("""() => {
      for (let i = 0; i < 3; i++) {
        const el = document.getElementById("demo-file-" + i);
        el.style.transitionDuration = "1300ms";
        el.style.left = (720 + i * 26) + "px"; el.style.top = (330 + i * 22) + "px";
      }
      document.getElementById("drop").classList.add("over");
    }""")
    d.move(820, 420, 1300)
    page.evaluate("""() => {
      for (let i = 0; i < 3; i++) { const el = document.getElementById("demo-file-" + i); el.style.transitionDuration = "250ms"; el.style.opacity = 0; el.style.transform = "scale(.6)"; }
      document.getElementById("drop").classList.remove("over");
    }""")
    d.wait(250)
    page.evaluate("files => onFiles(files)", data["filesWaiting"])
    d.wait(1800)

    # choose what to hide
    d.caption("Tick what to hide: names, faces, emails, addresses, IDs, cards, licence plates...")
    d.click(q(".cat").filter(has_text="Company names"), 900)
    d.wait(500)
    d.click(q(".cat").filter(has_text="Company names"), 400)
    d.wait(900)

    d.caption("Add things only you know about, like your car's plate.")
    d.type(q("#also"), "9256YT")
    d.wait(900)
    d.caption("And keep your own details visible.")
    d.type(q("#keep"), "sidequest")
    d.wait(900)

    # analyse
    d.caption("Three open models read every line on this laptop: fixed patterns, GLiNER2-PII and Gemma 4.")
    d.click(q("#findBtn"), 700, 0)
    d.move(W * 0.55, H * 0.45, 900)
    d.wait(9200)

    d.caption("Everything found gets a solid black box. Not blur: blur can be undone.", 3400)

    # review
    d.caption("Review the list. Untick anything that should stay visible.")
    item = q(".item").filter(has_text="Maria Lopez Garcia").first
    d.move(*d.center(item), 900)
    d.wait(900)
    d.click(item.locator("input"), 300)
    d.wait(1500)
    d.click(item.locator("input"), 300)
    d.wait(900)
    d.click(q(".group").filter(has_text="Phone numbers").locator("input"), 800)
    d.wait(1300)
    d.click(q(".group").filter(has_text="Phone numbers").locator("input"), 300)
    d.wait(1000)

    # manual box on the screenshot
    d.caption("Missed something? Draw a box by hand.")
    d.click(q(".tab").filter(has_text="crm-screenshot.png"), 800)
    d.wait(1100)
    d.click(q("#drawBtn"), 700)
    img = q("#pageImg").bounding_box()
    sx = img["width"] / data["plans"][1]["pages"][0]["width"]
    x0, y0 = img["x"] + MANUAL_BOX[0] * sx, img["y"] + MANUAL_BOX[1] * sx
    x1, y1 = img["x"] + MANUAL_BOX[2] * sx, img["y"] + MANUAL_BOX[3] * sx
    d.move(x0, y0, 800)
    page.mouse.move(x0, y0)
    page.mouse.down()
    steps = 14
    for k in range(1, steps + 1):
        x, y = x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps
        d.move(x, y, 45)
        page.mouse.move(x, y)
    page.mouse.up()
    d.wait(1600)

    # video
    d.caption("In screen recordings the boxes follow the text while it scrolls.")
    d.click(q(".tab").filter(has_text="crm-recording.mp4"), 800)
    d.wait(1000)
    d.move(*d.center(q("#nextBtn")), 700)
    for _ in range(len(data["plans"][2]["pages"]) - 1):
        d.press()
        page.keyboard.press("ArrowRight")
        d.wait(170)
    d.wait(800)

    # export
    d.caption("Export clean copies. Your originals are never touched.")
    d.click(q("#exportBtn"), 900)
    d.wait(3400)

    # proof
    d.caption("PDFs are redacted for real: the hidden text is deleted from the file, not covered.")
    d.layer("demo-proof", True, f"""<img src="{data['pdfImage']}" alt="">
      <div class="copy"><h2>Text copied from the exported PDF</h2><pre>{_escape(data['pdfText'])}</pre></div>""")
    d.wait(5200)
    d.layer("demo-proof", False)

    d.caption("The exported screen recording, ready to share.")
    d.layer("demo-after", True, f"""<video src="{data['afterVideo']}" autoplay muted playsinline></video>""")
    d.wait(6300)
    d.layer("demo-after", False)

    # end card
    d.caption(None)
    d.layer("demo-card", True, """<img src="logo.svg" alt=""><h1>Redactator</h1>
      <p>No upload. No account. No per-file bill.</p>
      <p class="small">Open source. Gemma 4, GLiNER2-PII and RapidOCR running locally.</p>""")
    d.wait(4500)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def record(data: dict, frames_dir: Path) -> list[tuple[float, Path]]:
    frames: list[tuple[float, Path]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--allow-file-access-from-files"])
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=SCALE)
        page = ctx.new_page()
        page.add_init_script(f"window.__D = {json.dumps(data)};\n{BRIDGE}\n{OVERLAY_JS}")
        page.goto((REPO / "redactator/app/web/index.html").as_uri())
        page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        page.wait_for_timeout(800)

        cdp = ctx.new_cdp_session(page)

        def on_frame(params):
            path = frames_dir / f"{len(frames):06d}.jpg"
            path.write_bytes(base64.b64decode(params["data"]))
            frames.append((params["metadata"]["timestamp"], path))
            cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

        cdp.on("Page.screencastFrame", on_frame)
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
        d = Director(page)
        run_script(d, data)
        # the screencast only sends frames when something changes: remember when the last scene ended
        frames.append((time.time(), None))
        cdp.send("Page.stopScreencast")
        CAPTIONS.write_text(json.dumps(d.captions, indent=2))
        browser.close()
    return frames


def assemble(frames: list[tuple[float, Path]], work: Path) -> None:
    lines = []
    for (t, path), nxt in zip(frames, frames[1:]):
        if path is not None:
            lines += [f"file '{path}'", f"duration {max(nxt[0] - t, 0.001):.4f}"]
    lines.append(f"file '{frames[-2][1]}'")
    listing = work / "frames.txt"
    listing.write_text("\n".join(lines))
    subprocess.run(
        [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-crf", "18",
         "-preset", "slow", "-movflags", "+faststart", str(OUT)],
        check=True,
    )


def main():
    work = Path(tempfile.mkdtemp(prefix="redactator-demo-"))
    try:
        data = precompute(work)
        frames_dir = work / "frames"
        frames_dir.mkdir()
        frames = record(data, frames_dir)
        print(f"{len(frames) - 1} frames captured")
        assemble(frames, work)
        print(f"wrote {OUT}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
