"""Confronto visivo video/MIDI per Midi Generator v2.4."""
from pathlib import Path
import cv2
import numpy as np
try:
    from .video_to_midi import NoteEvent
except ImportError:
    from video_to_midi import NoteEvent


def _hand_color(hand: str):
    return (70, 130, 240) if hand == 'left' else (80, 200, 90) if hand == 'right' else (180, 180, 180)


def render_midi_preview(events, width=1000, height_per_second=90, pitch_min=36, pitch_max=88, pitch_width=None, note_gap=2):
    """Disegna un pianoroll verticale con colori e durate degli eventi MIDI."""
    max_time = max((e.end for e in events), default=1.0)
    image = np.zeros((max(200, int(max_time * height_per_second) + 40), width, 3), dtype=np.uint8)
    image[:] = (24, 24, 24)
    pitch_width = pitch_width or max(3, (width - 80) / max(1, pitch_max - pitch_min + 1))
    for pitch in range(pitch_min, pitch_max + 1):
        x = int(50 + (pitch - pitch_min) * pitch_width)
        cv2.line(image, (x, 20), (x, image.shape[0]), (45, 45, 45), 1)
    for second in range(int(max_time) + 1):
        y = int(image.shape[0] - 20 - second * height_per_second)
        cv2.line(image, (45, y), (width, y), (55, 55, 55), 1)
        cv2.putText(image, f'{second}s', (5, y + 4), cv2.FONT_HERSHEY_SIMPLEX, .35, (180, 180, 180), 1)
    baseline = image.shape[0] - 20
    for event in events:
        x1 = int(50 + (event.pitch - pitch_min) * pitch_width + note_gap / 2)
        x2 = int(x1 + max(2, pitch_width - note_gap))
        y1 = int(baseline - event.end * height_per_second)
        y2 = int(baseline - event.start * height_per_second)
        cv2.rectangle(image, (x1, min(y1, y2)), (x2, max(y1, y2)), _hand_color(event.hand), -1)
    return image


def create_comparison_report(video_path, events, output_path, sample_every_seconds=1.0):
    """Crea un report diagnostico con frame campionati e anteprima MIDI."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return False
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    frames = []
    index = 0
    sample_every_frames = max(1, round(fps * sample_every_seconds))
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % max(1, sample_every_frames) == 0:
            frame = cv2.resize(frame, (500, 280))
            cv2.putText(frame, f'Video t={index / fps:.2f}s', (10, 22), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,255,255), 1)
            frames.append(frame)
            if len(frames) >= 12:
                break
        index += 1
    cap.release()
    preview = render_midi_preview(events, width=500, height_per_second=70)
    preview = cv2.resize(preview, (500, 280))
    cv2.putText(preview, 'MIDI preview (sample)', (10, 22), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,255,255), 1)
    if not frames:
        return False
    rows = []
    for frame in frames:
        rows.append(np.hstack([frame, preview.copy()]))
    report = np.vstack(rows)
    cv2.imwrite(str(output_path), report)
    return True
