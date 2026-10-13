"""Image preparation for OCR: orientation, deskew, scale, contrast, threshold."""

from __future__ import annotations

import cv2
import numpy as np

MAX_SKEW_DEGREES = 10.0
TARGET_TEXT_HEIGHT = 30.0   # px; Tesseract is most accurate around 20-40 px


def to_gray(image) -> np.ndarray:
    """PIL image or ndarray -> 2-D uint8 array."""
    array = np.asarray(image)
    if array.dtype != np.uint8:
        array = array.astype(np.uint8)
    if array.ndim == 2:
        return array
    if array.shape[2] == 4:
        # Composite transparency onto white so transparent text backgrounds work.
        alpha = array[:, :, 3:4].astype(np.float32) / 255.0
        rgb = array[:, :, :3].astype(np.float32) * alpha + 255.0 * (1 - alpha)
        array = rgb.astype(np.uint8)
    return cv2.cvtColor(array[:, :, :3], cv2.COLOR_RGB2GRAY)


def rotate_quadrant(gray: np.ndarray, clockwise_degrees: int) -> np.ndarray:
    codes = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    code = codes.get(clockwise_degrees % 360)
    return gray if code is None else cv2.rotate(gray, code)


def binarize(gray: np.ndarray) -> np.ndarray:
    """Otsu threshold: black text (0) on white (255)."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def binarize_adaptive(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)


def ink_ratio(gray: np.ndarray) -> float:
    """Fraction of dark pixels (0 for a blank page)."""
    if gray.size == 0:
        return 0.0
    if int(gray.max()) - int(gray.min()) < 40:   # flat image: no text-like contrast
        return 0.0
    return float(np.count_nonzero(binarize(gray) == 0)) / gray.size


def skew_angle(gray: np.ndarray) -> float:
    """Small-angle skew (degrees, counter-clockwise positive) via projection profiles.

    The page is rotated by candidate angles; the angle whose horizontal
    projection has the sharpest peaks (text lines aligned with rows) wins.
    """
    small = gray
    scale = 1000.0 / max(gray.shape)
    if scale < 1.0:
        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ink = (binarize(small) == 0).astype(np.float32)
    if ink.sum() < 50:
        return 0.0

    def sharpness(angle: float) -> float:
        rotated = _rotate(ink, angle, border=0.0)
        profile = rotated.sum(axis=1)
        return float(np.var(profile))

    best = max(np.arange(-MAX_SKEW_DEGREES, MAX_SKEW_DEGREES + 0.01, 0.5), key=sharpness)
    fine = np.arange(best - 0.5, best + 0.51, 0.1)
    best = max(fine, key=sharpness)
    return float(best) if abs(best) >= 0.3 else 0.0


def _rotate(image: np.ndarray, angle: float, border: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = int(h * sin + w * cos), int(h * cos + w * sin)
    matrix[0, 2] += new_w / 2 - w / 2
    matrix[1, 2] += new_h / 2 - h / 2
    return cv2.warpAffine(image, matrix, (new_w, new_h), flags=cv2.INTER_LINEAR, borderValue=border)


def deskew(gray: np.ndarray, angle: float) -> np.ndarray:
    return gray if not angle else _rotate(gray, angle, border=255)


def text_height(gray: np.ndarray) -> float | None:
    """Median height of character-like connected components, in px."""
    inverted = 255 - binarize(gray)
    count, _, stats, _ = cv2.connectedComponentsWithStats(inverted, connectivity=8)
    heights = [
        stats[i, cv2.CC_STAT_HEIGHT] for i in range(1, count)
        if stats[i, cv2.CC_STAT_AREA] >= 4 and 3 <= stats[i, cv2.CC_STAT_HEIGHT] < gray.shape[0] * 0.2
    ]
    return float(np.median(heights)) if len(heights) >= 3 else None


def upscale_factor(gray: np.ndarray) -> float:
    height = text_height(gray)
    if height is None or height >= TARGET_TEXT_HEIGHT * 0.6:
        return 1.0
    return min(4.0, TARGET_TEXT_HEIGHT / height)


def enhance(gray: np.ndarray) -> np.ndarray:
    """Contrast normalization (CLAHE) and light denoising."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return cv2.medianBlur(clahe.apply(gray), 3)
