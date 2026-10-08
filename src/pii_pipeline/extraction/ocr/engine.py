"""Local Tesseract OCR: image -> positioned words with confidence.

Tesseract is located from, in order: the ``TESSERACT_CMD`` environment
variable, ``PATH``, then the default Windows install folder. OCR never falls
back to any remote service; if Tesseract is missing, ``OCRUnavailableError``
is raised instead of silently skipping text.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pytesseract

from ..base import BBox, OCRUnavailableError

LANG = os.environ.get("PII_OCR_LANG", "eng")
_WINDOWS_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


@lru_cache(maxsize=1)
def tesseract_cmd() -> str:
    candidates = [os.environ.get("TESSERACT_CMD"), shutil.which("tesseract"), _WINDOWS_DEFAULT]
    for cmd in candidates:
        if cmd and (os.path.isfile(cmd) or shutil.which(cmd)):
            return cmd
    raise OCRUnavailableError(
        "OCR is required but Tesseract was not found. Install it locally and/or set TESSERACT_CMD."
    )


def ocr_available() -> bool:
    try:
        tesseract_cmd()
        return True
    except OCRUnavailableError:
        return False


def _configure() -> None:
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd()


@dataclass
class Word:
    text: str
    bbox: BBox          # pixels in the image that was OCR'd
    conf: float | None  # 0..1
    block: int
    par: int
    line: int


def ocr_words(image: np.ndarray, psm: int = 3) -> list[Word]:
    """Run Tesseract on a grayscale/binary uint8 image and return its words."""
    _configure()
    config = f"--oem 1 --psm {psm} -c preserve_interword_spaces=1"
    data = pytesseract.image_to_data(image, lang=LANG, config=config, output_type=pytesseract.Output.DICT)
    words: list[Word] = []
    for i, level in enumerate(data["level"]):
        if int(level) != 5:
            continue
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        conf = float(data["conf"][i])
        left, top = float(data["left"][i]), float(data["top"][i])
        words.append(
            Word(
                text=text,
                bbox=(left, top, left + float(data["width"][i]), top + float(data["height"][i])),
                conf=None if conf < 0 else min(conf, 100.0) / 100.0,
                block=int(data["block_num"][i]),
                par=int(data["par_num"][i]),
                line=int(data["line_num"][i]),
            )
        )
    return words


def detect_orientation(image: np.ndarray) -> int:
    """Clockwise rotation (0/90/180/270) Tesseract OSD thinks the page has.

    Returns 0 when OSD is unavailable or unsure (too little text).
    """
    _configure()
    try:
        osd = pytesseract.image_to_osd(image, config="--psm 0", output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError:
        return 0
    if float(osd.get("orientation_conf", 0)) < 1.0:
        return 0
    return int(osd.get("rotate", 0)) % 360


def score(words: list[Word]) -> float:
    """Quality of an OCR pass: sum of word confidences (more confident words win)."""
    return sum(w.conf or 0.0 for w in words)


def mean_conf(words: list[Word]) -> float | None:
    confs = [w.conf for w in words if w.conf is not None]
    return sum(confs) / len(confs) if confs else None
