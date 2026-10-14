"""Videos and screen recordings.

Frames are sampled a few times per second. A sample that barely differs from the
previous one reuses its results, so a mostly static screen recording costs a
handful of OCR passes instead of thousands. On export, every frame between two
samples is covered by the boxes of both, which follows text while it scrolls.
"""

from __future__ import annotations

import bisect
import shutil
import subprocess

import cv2
import numpy as np
from PIL import Image

from .. import faces, ocr
from ..model import Line, Page, Plan, Word

EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
SAMPLES_PER_SECOND = 4
STATIC_THRESHOLD = 1.2  # mean abs difference (0-255) on a small grey thumbnail
OCR_MAX_SIDE = 1920


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _thumb(frame: np.ndarray) -> np.ndarray:
    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90)).astype(np.int16)


def _ocr_frame(rgb: np.ndarray) -> list[Line]:
    h, w = rgb.shape[:2]
    s = min(1.0, OCR_MAX_SIDE / max(h, w))
    if s < 1.0:
        rgb = cv2.resize(rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    lines = ocr.read_lines(rgb)
    if s < 1.0:
        lines = [Line([Word(x.text, tuple(v / s for v in x.box)) for x in l.words]) for l in lines]
    return lines


def load(path: str, want_faces: bool, progress=None) -> tuple[list[Page], dict]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, round(fps / SAMPLES_PER_SECOND))

    pages: list[Page] = []
    frames: list[int] = []
    last_thumb, last_page = None, None
    analysed = 0
    i = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            thumb = _thumb(frame)
            page = Page(len(pages), w, h, time=i / fps)
            if last_page is not None and np.abs(thumb - last_thumb).mean() < STATIC_THRESHOLD:
                page.lines, page.faces = last_page.lines, last_page.faces
            else:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                page.lines = _ocr_frame(rgb)
                if want_faces:
                    page.faces = faces.find_faces(rgb)
                last_thumb, last_page = thumb, page
                analysed += 1
            pages.append(page)
            frames.append(i)
            if progress and len(pages) % 8 == 0:
                pct = 100 * i / max(1, total)
                progress(f"Scanning video {pct:.0f}% ({analysed} frames read, {len(pages) - analysed} unchanged)")
        i += 1
    cap.release()
    return pages, {"fps": fps, "frames": frames, "total_frames": i, "width": w, "height": h}


def preview(plan: Plan, index: int) -> Image.Image:
    cap = cv2.VideoCapture(plan.path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, plan.meta["frames"][index])
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise ValueError("Cannot read frame")
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def export(plan: Plan, out_path: str, progress=None) -> None:
    meta = plan.meta
    frames: list[int] = meta["frames"]
    w, h, fps = meta["width"], meta["height"], meta["fps"]
    per_sample = [plan.boxes_on(p.index) for p in plan.pages]

    cmd = [
        ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-",
        "-i", plan.path,
        "-map", "0:v", "-map", "1:a?",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-map_metadata", "-1", "-movflags", "+faststart",
        out_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cap = cv2.VideoCapture(plan.path)
    total = meta["total_frames"]
    i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            k = max(0, bisect.bisect_right(frames, i) - 1)
            boxes = per_sample[k] + (per_sample[k + 1] if k + 1 < len(per_sample) else [])
            for x0, y0, x1, y1 in boxes:
                cv2.rectangle(frame, (int(x0), int(y0)), (int(x1 + 0.999), int(y1 + 0.999)), (0, 0, 0), -1)
            proc.stdin.write(frame.tobytes())
            i += 1
            if progress and i % 30 == 0:
                progress(f"Rendering {100 * i / max(1, total):.0f}%")
    finally:
        cap.release()
        proc.stdin.close()
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed with code {code}")
