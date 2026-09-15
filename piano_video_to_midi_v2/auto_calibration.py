from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


@dataclass
class AutoCalibration:
    keyboard_line_y: int
    c4_center_x: float
    octave_width_px: float
    roll_top_y: int
    confidence: float
    details: str


def _detect_red_line(frame: np.ndarray) -> int | None:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    red = (((hsv[:, :, 0] <= 8) | (hsv[:, :, 0] >= 172)) &
           (hsv[:, :, 1] >= 120) & (hsv[:, :, 2] >= 100))
    h = frame.shape[0]
    y0, y1 = int(h * 0.50), int(h * 0.90)
    counts = red[y0:y1].sum(axis=1)
    if len(counts) == 0:
        return None
    idx = int(np.argmax(counts)) + y0
    if counts[idx - y0] < frame.shape[1] * 0.25:
        return None
    # Use the center of the contiguous red band around the strongest row.
    lo = idx
    hi = idx
    while lo > y0 and red[lo - 1].sum() > frame.shape[1] * 0.15:
        lo -= 1
    while hi + 1 < y1 and red[hi + 1].sum() > frame.shape[1] * 0.15:
        hi += 1
    return int(round((lo + hi) / 2))


def _black_key_centers(frame: np.ndarray, line_y: int) -> list[float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    y0 = min(h - 1, line_y + 18)
    y1 = min(h, line_y + 115)
    if y1 <= y0 + 10:
        return []

    roi = gray[y0:y1]
    # Black piano keys occupy most of this vertical band and are much darker
    # than the white keys. Count dark pixels per column.
    dark = roi < 75
    counts = dark.sum(axis=0)
    threshold = max(25, int((y1 - y0) * 0.55))
    binary = (counts >= threshold).astype(np.uint8) * 255
    kernel = np.ones((5, 1), np.uint8)
    binary = cv2.morphologyEx(binary.reshape(1, -1), cv2.MORPH_CLOSE, kernel).reshape(-1)

    centers: list[float] = []
    in_region = False
    start = 0
    for x, value in enumerate(binary):
        if value and not in_region:
            start = x
            in_region = True
        elif in_region and not value:
            end = x - 1
            if 18 <= end - start + 1 <= 70:
                centers.append((start + end) / 2.0)
            in_region = False
    if in_region:
        end = w - 1
        if 18 <= end - start + 1 <= 70:
            centers.append((start + end) / 2.0)
    return centers


def _estimate_from_black_keys(centers: list[float], width: int) -> tuple[float, float, float] | None:
    if len(centers) < 10:
        return None
    c = np.asarray(centers, dtype=float)
    d = np.diff(c)
    # The black-key pattern is C#, D#, F#, G#, A#, then repeats.
    # Within an octave: small, large, small, small, large.
    best = None
    for i in range(len(d) - 4):
        ds = d[i:i + 4]
        base = np.median(ds[[0, 2, 3]])
        if base <= 0:
            continue
        expected = np.array([base, 1.5 * base, base, base])
        err = float(np.mean(np.abs(ds - expected)) / base)
        # Require the two large gaps to really be larger than the small ones.
        if ds[1] < 1.25 * base:
            continue
        if err < 0.18:
            # C# center is ~half a white-key width right of C center.
            # White-key width ~= base, so C center is C# - base/2.
            octave = 6.0 * base  # 6 semitone-sized white-key steps across C#→next C#
            # More directly, the black-key pattern spans approximately six
            # small intervals (the two 1.5 gaps are included in the pattern).
            octave = float(np.sum(np.array([base, 1.5*base, base, base, 1.5*base])))
            c_center = c[i] - 0.5 * base
            score = err
            candidate = (c_center, octave, score)
            if best is None or score < best[2]:
                best = candidate
    if best is None:
        return None

    # The leftmost visible C is assumed to be C2 in this piano layout.
    # Move from that C to C4 by two octaves. Use the nearest valid C4 position
    # that lies in/near the visible keyboard.
    c0, octave, err = best
    # Find all possible C positions implied by the detected C# sequence.
    possible_c = []
    for x in c:
        possible_c.append(x - 0.5 * (octave / 7.0))
    # Choose the C whose octave index is closest to the center of the keyboard,
    # then label it C4 using the common C2..E6 52-white-key layout.
    left_c = min(possible_c)
    c4 = left_c + 2.0 * octave

    # If the inferred C4 is clearly outside the visible keyboard, fall back to
    # the C nearest the center and choose its octave consistently.
    if not (-0.5 * octave <= c4 <= width + 0.5 * octave):
        target = width * 0.5
        k = round((target - left_c) / octave)
        c4 = left_c + (k - 0) * octave

    confidence = max(0.0, min(1.0, 1.0 - err * 3.0))
    return float(c4), float(octave), confidence


def auto_calibrate(video_path: str | Path, progress_callback: Callable[[float, str], None] | None = None) -> AutoCalibration:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Impossibile aprire il video: {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        total = 1

    indices = sorted(set([max(0, int(total * f)) for f in (0.03, 0.15, 0.35, 0.55, 0.75, 0.92)]))
    line_candidates = []
    frames = []
    for j, idx in enumerate(indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        line = _detect_red_line(frame)
        if line is not None:
            line_candidates.append(line)
            frames.append((frame, line))
        if progress_callback:
            progress_callback(0.05 + 0.25 * (j + 1) / len(indices), f"Calibrazione: ricerca tastiera ({j+1}/{len(indices)})")
    cap.release()

    if not line_candidates:
        raise RuntimeError("Non riesco a rilevare automaticamente la linea rossa della tastiera.")
    # The red separator is a few pixels below the actual bottom edge of the
    # colored falling-note bars. Use a small inset so notes touching the
    # keyboard are still detected.
    red_line_y = int(round(float(np.median(line_candidates))))
    line_y = max(0, red_line_y - 10)

    key_sets = []
    for frame, _ in frames:
        centers = _black_key_centers(frame, line_y)
        if len(centers) >= 10:
            key_sets.append(centers)

    estimates = []
    for centers in key_sets:
        est = _estimate_from_black_keys(centers, width)
        if est:
            estimates.append(est)

    if estimates:
        c4 = float(np.median([e[0] for e in estimates]))
        octave = float(np.median([e[1] for e in estimates]))
        conf = float(np.median([e[2] for e in estimates]))
        detail = f"Linea rossa Y={red_line_y}; limite note Y={line_y}; C4 X={c4:.1f}; ottava={octave:.1f}px"
    else:
        # Conservative fallback for videos where black keys are occluded.
        # Estimate octave from the regular piano-roll grid in the upper area.
        frame = frames[len(frames)//2][0] if frames else None
        if frame is None:
            raise RuntimeError("Nessun frame disponibile per la calibrazione.")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        roi = gray[100:max(110, line_y - 20)]
        grad = np.abs(np.diff(roi.astype(np.float32), axis=1)).mean(axis=0)
        # Search periodicity between 300 and 500 px.
        best_period, best_score = None, -1.0
        for period in np.arange(300, 501, 1):
            a = grad[:-int(period)]
            b = grad[int(period):]
            if len(a) < 100:
                continue
            score = float(np.corrcoef(a, b)[0, 1])
            if np.isfinite(score) and score > best_score:
                best_score, best_period = score, period
        octave = float(best_period or 400.0)
        # Use the visible keyboard center as a weak fallback for C4.
        c4 = width * 0.5
        conf = 0.35
        detail = f"Linea Y rilevata; geometria tasti non affidabile, fallback ottava={octave:.1f}px"

    # The roll begins below the application header; keep a small margin above
    # the first note region while avoiding the toolbar.
    roll_top_y = 90
    confidence = max(0.0, min(1.0, conf))
    if progress_callback:
        progress_callback(0.35, "Calibrazione automatica completata")
    return AutoCalibration(
        keyboard_line_y=line_y,
        c4_center_x=c4,
        octave_width_px=octave,
        roll_top_y=roll_top_y,
        confidence=confidence,
        details=detail,
    )
