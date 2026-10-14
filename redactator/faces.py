"""Face detection with OpenCV's YuNet (a tiny open model, ~230 KB, runs on CPU)."""

from __future__ import annotations

import urllib.request
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .model import Box

cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)

MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
    "face_detection_yunet_2023mar.onnx"
)
CACHE = Path.home() / ".cache" / "redactator"


def _model_path() -> Path:
    path = CACHE / "face_detection_yunet_2023mar.onnx"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, path)  # one-time download of the weights
    return path


@lru_cache(maxsize=1)
def _detector():
    return cv2.FaceDetectorYN.create(str(_model_path()), "", (320, 320), 0.7, 0.3, 5000)


def find_faces(rgb: np.ndarray) -> list[Box]:
    h, w = rgb.shape[:2]
    det = _detector()
    det.setInputSize((w, h))
    _, faces = det.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    out = []
    for f in faces if faces is not None else []:
        x, y, fw, fh = (float(v) for v in f[:4])
        # grow the box: YuNet hugs the face, hair and ears still identify people
        gx, gy = fw * 0.2, fh * 0.25
        out.append((max(0, x - gx), max(0, y - gy), min(w, x + fw + gx), min(h, y + fh + gy)))
    return out
