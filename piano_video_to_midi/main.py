#!/usr/bin/env python3
"""
Convert Synthesia-style falling-note videos to MIDI.

Tested conceptually on the supplied .MOV example:
- 1920x1080
- falling colored notes
- red hit line above the keyboard
- piano-roll octave grid about 400 px wide
- C2 starts at x=0 in the supplied example

Usage:
    python main.py clip_ex.mov output.mid --bpm 102

For videos with a different layout, tune:
    --c2-x
    --octave-width
    --c2-midi
    --hit-y
"""

import argparse
import math
from collections import defaultdict
from pathlib import Path

import cv2
import mido
import numpy as np


# MIDI pitch class offsets from C for semitones 0..11.
# We map the center of each falling note to the nearest semitone.
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F",
              "F#", "G", "G#", "A", "A#", "B"]


def find_hit_line(frame):
    """Find the horizontal red strike line automatically."""
    b, g, r = cv2.split(frame)
    red = (r > 130) & (r > g * 1.35) & (r > b * 1.35)

    # The strike line is usually the strongest long horizontal red line
    # in the lower half of the image.
    h, w = red.shape
    scores = red[int(h * 0.45):int(h * 0.9)].sum(axis=1)
    if len(scores) == 0 or scores.max() < w * 0.20:
        return None

    y = int(h * 0.45 + np.argmax(scores))
    return y


def color_mask_band(frame, y0, y1):
    """Fast colored-note mask for a thin horizontal band."""
    crop = frame[y0:y1, :]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, sat, val = cv2.split(hsv)

    # The example uses saturated blue and green note bars.
    blue = (h >= 85) & (h <= 135)
    green = (h >= 35) & (h <= 85)
    mask = (sat > 90) & (val > 80) & (blue | green)

    # A tiny horizontal close removes anti-aliasing gaps without
    # joining neighboring piano keys.
    mask = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)


def x_to_midi(x, c2_x, octave_width, c2_midi):
    """Map piano-roll x coordinate to the nearest MIDI semitone."""
    semitone_width = octave_width / 12.0
    pitch = c2_midi + int(round((x - c2_x) / semitone_width))
    return max(0, min(127, pitch))


def detect_notes(video_path, c2_x=0.0, octave_width=400.0,
                 c2_midi=36, hit_y=None, sample_every=1,
                 min_width=5, max_width=100):
    """
    Detect note ON/OFF events by looking at colored pixels crossing the hit line.

    A falling note first appears just above the hit line => NOTE ON.
    When its tail passes the hit line => NOTE OFF.

    Returns [(midi_note, start_seconds, end_seconds), ...].
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 30.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Detect the red strike line from the first usable frame.
    first = None
    if hit_y is None:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            first = frame
            y = find_hit_line(frame)
            if y is not None:
                hit_y = y
                break
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    if hit_y is None:
        # Fallback for layouts without a red line.
        hit_y = int(height * 0.68)

    # We sample a thin horizontal band immediately above the line.
    # This avoids depending on the exact shape of the rounded note head.
    band_top = max(0, int(hit_y) - 30)
    band_bottom = int(hit_y) - 1

    # Active notes are keyed by MIDI pitch. Each entry contains start time
    # and a smoothed state.
    active = {}
    completed = []

    # A note's x lane can be recovered from colored pixels near the strike line.
    # We use connected components to get the center of each colored region.
    last_time = 0.0
    frame_index = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_index % sample_every != 0:
            frame_index += 1
            continue

        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t <= 0:
            t = frame_index / fps
        last_time = t

        band = color_mask_band(frame, band_top, band_bottom + 1)

        # Collapse the band vertically: x columns containing note pixels.
        x_presence = (band > 0).sum(axis=0)
        present = x_presence >= max(1, band.shape[0] // 3)

        # Convert adjacent present x columns into note candidates.
        runs = []
        start = None
        for x, value in enumerate(present):
            if value and start is None:
                start = x
            elif not value and start is not None:
                if x - start >= min_width:
                    runs.append((start, x - 1))
                start = None
        if start is not None and width - start >= min_width:
            runs.append((start, width - 1))

        # Filter improbable full-screen/UI regions.
        candidates = []
        for x1, x2 in runs:
            w = x2 - x1 + 1
            if min_width <= w <= max_width:
                x_center = (x1 + x2) / 2.0
                midi_note = x_to_midi(
                    x_center, c2_x, octave_width, c2_midi
                )
                candidates.append((midi_note, x_center))

        current = defaultdict(list)
        for note, x in candidates:
            current[note].append(x)

        # NOTE ON
        for note in current:
            if note not in active:
                active[note] = t

        # NOTE OFF
        for note in list(active):
            if note not in current:
                start_t = active.pop(note)
                if t - start_t >= 1.0 / fps * max(1, sample_every):
                    completed.append((note, start_t, t))

        frame_index += 1

    # Close notes that are still active at EOF.
    for note, start_t in active.items():
        if last_time - start_t > 0:
            completed.append((note, start_t, last_time))

    cap.release()

    # Sort by time, then pitch.
    completed.sort(key=lambda n: (n[1], n[0]))
    return completed, fps, width, height, hit_y


def write_midi(notes, output_path, bpm=102.0, ticks_per_beat=480,
               quantize=None, velocity=90):
    """
    Write detected notes to a type-1 MIDI file.

    Timing is derived from the video's real timestamps. The tempo is stored
    in the MIDI so DAWs and players interpret the tick positions correctly.
    """
    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    tempo = mido.bpm2tempo(bpm)
    track.append(mido.MetaMessage("track_name", name="Piano"))
    track.append(mido.MetaMessage("set_tempo", tempo=tempo))
    track.append(mido.Message("program_change", program=0, time=0))

    # Optional quantization to musical subdivisions.
    # quantize=0.25 means quarter-beat grid, 0.5 means eighth-note, etc.
    def qtime(seconds):
        if not quantize or quantize <= 0:
            return seconds
        beat = 60.0 / bpm
        grid = beat * quantize
        return round(seconds / grid) * grid

    events = []
    for note, start, end in notes:
        start = qtime(start)
        end = max(start + 0.001, qtime(end))
        events.append((start, 1, note))
        events.append((end, 0, note))

    # At equal timestamps, NOTE OFF comes before NOTE ON for the same pitch.
    events.sort(key=lambda e: (e[0], e[1]))

    last_seconds = 0.0
    for seconds, kind, note in events:
        delta_seconds = max(0.0, seconds - last_seconds)
        delta_ticks = int(round(
            mido.second2tick(delta_seconds, ticks_per_beat, tempo)
        ))
        msg_type = "note_on" if kind else "note_off"
        vel = velocity if kind else 0
        track.append(mido.Message(
            msg_type, note=int(note), velocity=vel, time=delta_ticks
        ))
        last_seconds = seconds

    track.append(mido.MetaMessage("end_of_track", time=0))
    mid.save(str(output_path))


def main():
    parser = argparse.ArgumentParser(
        description="Convert Synthesia-style falling-note video to MIDI."
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)

    parser.add_argument("--bpm", type=float, default=102.0,
                        help="Tempo used in the MIDI (default: 102)")
    parser.add_argument("--c2-x", type=float, default=0.0,
                        help="X coordinate of C2 in the piano roll")
    parser.add_argument("--octave-width", type=float, default=400.0,
                        help="Pixel width of one octave in the roll")
    parser.add_argument("--c2-midi", type=int, default=36,
                        help="MIDI number assigned to C2 (default: 36)")
    parser.add_argument("--hit-y", type=int, default=None,
                        help="Strike-line Y coordinate; auto-detected by default")
    parser.add_argument("--sample-every", type=int, default=1,
                        help="Process every Nth frame")
    parser.add_argument("--quantize", type=float, default=None,
                        help="Optional grid in beats: 1=quarter, 0.5=eighth, 0.25=16th")
    parser.add_argument("--velocity", type=int, default=90)

    args = parser.parse_args()

    notes, fps, width, height, hit_y = detect_notes(
        args.video,
        c2_x=args.c2_x,
        octave_width=args.octave_width,
        c2_midi=args.c2_midi,
        hit_y=args.hit_y,
        sample_every=max(1, args.sample_every),
    )

    write_midi(
        notes,
        args.output,
        bpm=args.bpm,
        quantize=args.quantize,
        velocity=max(1, min(127, args.velocity)),
    )

    print(f"Video:       {width}x{height} @ {fps:.3f} fps")
    print(f"Hit line:    y={hit_y}")
    print(f"Notes found: {len(notes)}")
    print(f"MIDI saved:  {args.output}")

    if notes:
        print("\nFirst detected notes:")
        for note, start, end in notes[:20]:
            name = NOTE_NAMES[note % 12] + str(note // 12 - 1)
            print(f"  {name:4s} MIDI {note:3d}  {start:8.3f}s -> {end:8.3f}s")


if __name__ == "__main__":
    main()
