"""Estimate text line height and upscale images whose text is too small to read.

Tesseract's LSTM models expect roughly 20-50 px per text line; below ~20 px
they return nothing at all. Downscaled crops, phone photos of whole pages and
screenshots routinely fall below that, so small text is enlarged first.

Shared verbatim with the app (app/ocrapp/textscale.py) so that the benchmark
measures what the app actually does.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

TARGET_LINE_PX = 48
MIN_LINE_PX = 28
MAX_FACTOR = 4.0


def _otsu(arr: np.ndarray) -> int:
    hist = np.bincount(arr.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 128
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma = (mu_t * omega - mu) ** 2 / (omega * (1 - omega))
    sigma = np.nan_to_num(sigma)
    return int(np.argmax(sigma))


def line_height(gray: Image.Image) -> float | None:
    """Median height of text rows from a horizontal ink profile, or None."""
    small = gray
    if max(gray.size) > 2400:  # profile only needs a coarse look
        s = 2400 / max(gray.size)
        small = gray.resize((max(1, int(gray.width * s)), max(1, int(gray.height * s))))
    else:
        s = 1.0
    arr = np.asarray(small, dtype=np.uint8)
    t = _otsu(arr)
    ink = arr < t
    if ink.mean() > 0.5:          # light text on a dark background
        ink = ~ink
    rows = ink.mean(axis=1) > 0.005
    runs, n = [], 0
    for r in rows:
        if r:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    runs = [r for r in runs if r >= 2]
    if not runs:
        return None
    return float(np.median(runs)) / s


MIN_SIDE_PX = 120


def upscale_factor(gray: Image.Image) -> float:
    """Enlarge when text lines are small, or when the whole image is tiny.

    The size rule catches what the profile misses: in a two-line Devanagari
    crop the headlines touch, so the profile sees one tall "line".
    """
    factor = 1.0
    h = line_height(gray)
    if h and h < MIN_LINE_PX:
        factor = TARGET_LINE_PX / h
    side = min(gray.size)
    if side < MIN_SIDE_PX:
        factor = max(factor, MIN_SIDE_PX / side)
    return min(MAX_FACTOR, factor)


def upscale(img: Image.Image, factor: float) -> Image.Image:
    if factor <= 1.0:
        return img
    return img.resize((int(img.width * factor), int(img.height * factor)), Image.LANCZOS)
