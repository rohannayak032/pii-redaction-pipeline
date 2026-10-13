import cv2
import numpy as np

from pii_pipeline.extraction.ocr import preprocessing


def _page(sidebar: bool) -> np.ndarray:
    img = np.full((800, 1600), 255, np.uint8)
    if sidebar:
        img[:, :250] = 60   # solid dark UI sidebar, as in app screenshots
    for y in range(60, 760, 40):
        cv2.putText(img, "Siddharth Gaikwad 10/31/2025 Draft", (300, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2)
    return img


def test_solid_sidebar_is_not_skew():
    assert preprocessing.skew_angle(_page(sidebar=True)) == 0.0


def test_real_skew_still_detected():
    assert abs(abs(preprocessing.skew_angle(preprocessing.deskew(_page(sidebar=False), 4.0))) - 4.0) <= 0.3
