"""Desktop app: a native window (pywebview) around a local HTML interface."""

from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import webview
from webview.dom import DOMEventHandler

from .. import brain, engine, ner
from ..categories import CATEGORIES, Options, split_list
from ..model import Plan

WEB = Path(__file__).parent / "web"
FILE_TYPES = (
    "Photos, PDFs and videos (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tif;*.tiff;*.pdf;*.mp4;*.mov;*.m4v;*.mkv;*.webm;*.avi)",
)


@dataclass
class Item:
    path: str
    status: str = "waiting"  # waiting, reading, done, error
    plan: Plan | None = None
    error: str = ""

    def summary(self) -> dict:
        return {
            "path": self.path,
            "name": Path(self.path).name,
            "kind": engine.kind_of(self.path),
            "status": self.status,
            "error": self.error,
            "found": len(self.plan.findings) if self.plan else 0,
        }


class Api:
    def __init__(self):
        self.window: webview.Window | None = None
        self.items: list[Item] = []
        self._lock = threading.Lock()

    # -- helpers -----------------------------------------------------------
    def _js(self, fn: str, *args) -> None:
        if self.window:
            self.window.evaluate_js(f"{fn}({','.join(json.dumps(a) for a in args)})")

    def _files(self) -> list[dict]:
        return [it.summary() for it in self.items]

    def _plan(self, i: int) -> Plan:
        return self.items[i].plan

    def _plan_json(self, i: int) -> dict:
        p = self._plan(i)
        return {
            "file": i,
            "name": Path(p.path).name,
            "kind": p.kind,
            "model": p.meta.get("model"),
            "seconds": p.meta.get("seconds"),
            "pages": [{"index": pg.index, "width": pg.width, "height": pg.height, "time": pg.time} for pg in p.pages],
            "findings": [
                {**s, "boxes": {str(k): v for k, v in f.boxes.items()}} for s, f in zip(p.summary(), p.findings)
            ],
        }

    # -- called from JavaScript ---------------------------------------------
    def status(self) -> dict:
        return {
            "model": brain.MODEL,
            "ready": brain.available(),
            "categories": [{"id": c.id, "title": c.title, "default": c.default} for c in CATEGORIES.values()],
        }

    def choose_files(self) -> None:
        picked = self.window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=FILE_TYPES)
        if picked:
            self.add_files(list(picked))

    def add_files(self, paths: list[str]) -> None:
        known = {it.path for it in self.items}
        skipped = []
        for p in paths:
            try:
                engine.kind_of(p)
            except ValueError:
                skipped.append(Path(p).name)
                continue
            if p not in known:
                self.items.append(Item(p))
                known.add(p)
        self._js("onFiles", self._files())
        if skipped:
            self._js("onError", f"Skipped {', '.join(skipped)}: only photos, PDFs and videos can be redacted.")

    def remove_file(self, i: int) -> list[dict]:
        if 0 <= i < len(self.items) and not self._lock.locked():
            del self.items[i]
        return self._files()

    def analyse(self, settings: dict) -> None:
        options = Options(
            hide=list(settings.get("hide", [])),
            also=split_list(settings.get("also", "")),
            keep=split_list(settings.get("keep", "")),
        )

        def run():
            with self._lock:
                total = len(self.items)
                for i, it in enumerate(self.items):
                    it.status, it.error = "reading", ""
                    self._js("onFiles", self._files())
                    prefix = f"{Path(it.path).name} ({i + 1} of {total}): " if total > 1 else ""
                    try:
                        it.plan = engine.analyse(it.path, options, lambda m: self._js("onProgress", prefix + m))
                        it.status = "done"
                        self._js("onFiles", self._files())
                        self._js("onPlan", self._plan_json(i))
                    except Exception as e:
                        it.status, it.error, it.plan = "error", str(e), None
                        self._js("onFiles", self._files())
                self._js("onDone", self._files())

        threading.Thread(target=run, daemon=True).start()

    def plan(self, i: int) -> dict | None:
        return self._plan_json(i) if self.items[i].plan else None

    def page_image(self, i: int, page: int) -> str:
        im = engine.preview(self._plan(i), page)
        im.thumbnail((1600, 1600))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    def toggle(self, i: int, finding_id: str, enabled: bool) -> None:
        for f in self._plan(i).findings:
            if f.id == finding_id:
                f.enabled = enabled

    def add_box(self, i: int, page: int, box: list[float]) -> dict:
        engine.add_manual_box(self._plan(i), page, tuple(box))
        return self._plan_json(i)

    def remove_manual(self, i: int, finding_id: str) -> dict:
        p = self._plan(i)
        p.findings = [f for f in p.findings if not (f.id == finding_id and f.source == "manual")]
        return self._plan_json(i)

    def export(self) -> bool:
        ready = [it for it in self.items if it.plan]
        if not ready:
            return False
        if len(ready) == 1:
            default = Path(engine.default_output(ready[0].path))
            picked = self.window.create_file_dialog(
                webview.FileDialog.SAVE, directory=str(default.parent), save_filename=default.name
            )
            if not picked:
                return False
            targets = [(ready[0], picked if isinstance(picked, str) else picked[0])]
        else:
            picked = self.window.create_file_dialog(webview.FileDialog.FOLDER, directory=str(Path(ready[0].path).parent))
            if not picked:
                return False
            folder = Path(picked if isinstance(picked, str) else picked[0])
            targets = [(it, str(folder / Path(engine.default_output(it.path)).name)) for it in ready]

        def run():
            done = []
            for n, (it, out) in enumerate(targets, 1):
                prefix = f"{Path(it.path).name} ({n} of {len(targets)}): " if len(targets) > 1 else ""
                try:
                    engine.export(it.plan, out, lambda m: self._js("onProgress", prefix + m))
                    done.append(out)
                except Exception as e:
                    self._js("onError", f"Export of {Path(it.path).name} failed: {e}")
                    return
            self._js("onExported", done)

        threading.Thread(target=run, daemon=True).start()
        return True

    def reveal(self, path: str) -> None:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path])
        elif sys.platform == "win32":
            subprocess.run(["explorer", "/select,", path])
        else:
            subprocess.run(["xdg-open", str(Path(path).parent)])


def _wire_drop(window: webview.Window, api: Api) -> None:
    def on_drop(e):
        files = e.get("dataTransfer", {}).get("files", [])
        paths = [f["pywebviewFullPath"] for f in files if f.get("pywebviewFullPath")]
        if paths:
            api.add_files(paths)

    window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
    window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)


def main() -> None:
    api = Api()
    window = webview.create_window(
        "Redactator",
        url=str(WEB / "index.html"),
        js_api=api,
        width=1320,
        height=860,
        min_size=(960, 640),
        background_color="#EDEFF5",
    )
    api.window = window
    # warm the PII model in the background so the first check is quick
    threading.Thread(target=ner.available, daemon=True).start()
    webview.start(_wire_drop, (window, api), debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
