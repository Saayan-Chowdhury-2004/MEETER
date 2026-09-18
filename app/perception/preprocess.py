"""Frame preprocessing helpers for OCR robustness."""
from __future__ import annotations

import numpy as np


def upscale_small(image: np.ndarray, min_height: int = 480) -> np.ndarray:
    import cv2

    h, w = image.shape[:2]
    if h >= min_height:
        return image
    scale = min_height / h
    return cv2.resize(image, (int(w * scale), min_height), interpolation=cv2.INTER_CUBIC)


def grayscale(image: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image


def denoise(image: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.fastNlMeansDenoising(image, h=7)


def binarize(image_gray: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.adaptiveThreshold(
        image_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )


def preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
    """Upscale → grayscale → binarize. Keep conservative; PaddleOCR handles raw well."""
    img = upscale_small(image)
    g = grayscale(img)
    return binarize(g)
