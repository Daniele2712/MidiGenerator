#!/usr/bin/env python3
"""MidiGeneratorBetav1.0: ricostruisce un'immagine verticale della sequenza di note."""
import argparse
import os
from pathlib import Path
import cv2
import numpy as np


def detect_horizontal_lines(frame, min_y, max_y, threshold=180):
    """Rileva le linee orizzontali tramite trasformata di Hough."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    roi = edges[min_y:max_y, :]
    lines = cv2.HoughLinesP(roi, 1, np.pi / 180, threshold=threshold,
                            minLineLength=max(80, frame.shape[1] // 5), maxLineGap=12)
    ys = []
    if lines is not None:
        # Normalizza l'output di Hough in una sequenza di segmenti, evitando
        # di trattare accidentalmente un singolo numpy.int32 come iterabile.
        for raw_line in np.asarray(lines).reshape(-1, 4):
            x1, y1, x2, y2 = (int(value) for value in raw_line)
            if abs(y2 - y1) <= 3:
                ys.append(min_y + (y1 + y2) // 2)
    ys.sort()
    merged = []
    for y in ys:
        if not merged or abs(y - merged[-1]) > 8:
            merged.append(y)
        else:
            merged[-1] = int((merged[-1] + y) / 2)
    return merged


def choose_reference_frame(cap, sample_count=24):
    """Sceglie un frame rappresentativo con molte informazioni cromatiche."""
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    candidates = np.linspace(0, max(0, total - 1), sample_count).astype(int)
    best_frame, best_score = None, -1
    for index in candidates:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, frame = cap.read()
        if not ok:
            continue
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        score = int(np.count_nonzero(saturation > 90))
        if score > best_score:
            best_score, best_frame = score, frame.copy()
    return best_frame


def crop_note_region(frame, left_ratio=0.12, right_ratio=0.98, top_ratio=0.20, bottom_ratio=0.85):
    """Ritaglia la zona centrale dove sono normalmente presenti le note."""
    h, w = frame.shape[:2]
    x1, x2 = int(w * left_ratio), int(w * right_ratio)
    y1, y2 = int(h * top_ratio), int(h * bottom_ratio)
    return frame[y1:y2, x1:x2].copy()


def build_image(video_path, output_path, line_min_ratio=0.15, line_max_ratio=0.90,
                crop_left=0.12, crop_right=0.98, crop_top=0.20, crop_bottom=0.85,
                line_threshold=180):
    """Costruisce l'immagine concatenando le fasce tra linee consecutive."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Impossibile aprire il video: {video_path}")
    ok, first = cap.read()
    if not ok:
        raise RuntimeError("Impossibile leggere il primo frame.")
    h, w = first.shape[:2]
    min_y, max_y = int(h * line_min_ratio), int(h * line_max_ratio)
    reference = choose_reference_frame(cap)
    if reference is None:
        reference = first
    lines = detect_horizontal_lines(reference, min_y, max_y, line_threshold)
    if len(lines) < 2:
        raise RuntimeError("Non sono state rilevate abbastanza linee orizzontali. Regola i parametri.")

    # Mantiene solo intervalli ragionevoli e ordina le linee.
    # Converte esplicitamente le coordinate in interi Python per evitare
    # problemi di iterabilità con scalari NumPy.
    lines = sorted({int(value) for value in lines})
    strips = []
    for a, b in zip(lines, lines[1:]):
        if 8 <= b - a <= int(h * 0.25):
            strip = reference[a:b, int(w * crop_left):int(w * crop_right)]
            if strip.size:
                strips.append(strip)
    if not strips:
        raise RuntimeError("Nessuna fascia valida trovata tra le linee rilevate.")

    # Uniforma la larghezza e concatena le fasce dal basso verso l'alto.
    target_width = min(s.shape[1] for s in strips)
    normalized = [s[:, :target_width] for s in strips]
    result = np.vstack(list(reversed(normalized)))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), result)
    return lines, result.shape


def main():
    """Gestisce gli argomenti da terminale."""
    parser = argparse.ArgumentParser(description="Crea un'immagine verticale dalle fasce tra linee orizzontali.")
    parser.add_argument("video", help="Percorso del video sorgente")
    parser.add_argument("-o", "--output", default="midi_image.png", help="Immagine di output")
    parser.add_argument("--line-min", type=float, default=0.15, help="Limite superiore relativo per le linee")
    parser.add_argument("--line-max", type=float, default=0.90, help="Limite inferiore relativo per le linee")
    parser.add_argument("--threshold", type=int, default=180, help="Soglia Hough")
    args = parser.parse_args()
    lines, shape = build_image(Path(args.video), Path(args.output), args.line_min, args.line_max, line_threshold=args.threshold)
    print(f"Linee rilevate: {len(lines)}")
    print(f"Immagine generata: {args.output} | dimensioni: {shape[1]}x{shape[0]}")


if __name__ == "__main__":
    main()
