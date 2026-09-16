from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
from mido import MidiFile, MidiTrack, Message, MetaMessage, bpm2tempo


@dataclass
class NoteEvent:
    pitch: int
    start: float
    end: float
    velocity: int = 100
    hand: str = "unknown"  # "left" (blue), "right" (green), or "unknown"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class DetectorConfig:
    keyboard_line_y: int = 628
    c4_center_x: float = 830.0
    octave_width_px: float = 400.0
    pitch_min: int = 36       # C2
    pitch_max: int = 88       # E6
    roll_top_y: int = 90
    onset_margin_px: int = 7
    min_component_area: int = 250
    min_component_width: int = 15
    max_component_width: int = 90
    min_component_height: int = 8
    max_pitch_distance_px: float = 18.0
    release_tolerance_frames: int = 2
    min_note_duration: float = 0.035
    max_note_duration: float = 30.0


ProgressCallback = Callable[[float, str], None]


def x_to_midi(x: float, config: DetectorConfig) -> Optional[int]:
    """Map the horizontal center of a falling note to a MIDI pitch.

    For the supplied video, C4 is approximately at x=830 and one octave
    occupies approximately 400 pixels, so one semitone is ~33.33 pixels.
    """
    semitone_px = config.octave_width_px / 12.0
    pitch = int(round(60 + (x - config.c4_center_x) / semitone_px))
    if not (config.pitch_min <= pitch <= config.pitch_max):
        return None

    expected_x = config.c4_center_x + (pitch - 60) * semitone_px
    if abs(expected_x - x) > config.max_pitch_distance_px:
        return None
    return pitch


def _make_color_masks(frame: np.ndarray, config: DetectorConfig) -> dict[str, np.ndarray]:
    """Return independent masks for the blue (left) and green (right) notes."""
    roi = frame[config.roll_top_y:config.keyboard_line_y]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # OpenCV hue range is 0..179. These ranges are intentionally tolerant of
    # compression and screen-recording colour shifts.
    blue = (
        (hsv[:, :, 0] >= 95)
        & (hsv[:, :, 0] <= 135)
        & (hsv[:, :, 1] >= 70)
        & (hsv[:, :, 2] >= 60)
    )
    green = (
        (hsv[:, :, 0] >= 30)
        & (hsv[:, :, 0] <= 75)
        & (hsv[:, :, 1] >= 65)
        & (hsv[:, :, 2] >= 60)
    )

    kernel = np.ones((3, 3), np.uint8)
    masks = {}
    for hand, raw in (("left", blue), ("right", green)):
        mask = raw.astype(np.uint8) * 255
        masks[hand] = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return masks


# Backward-compatible helper for callers that only need a combined mask.
def _make_color_mask(frame: np.ndarray, config: DetectorConfig) -> np.ndarray:
    masks = _make_color_masks(frame, config)
    return cv2.bitwise_or(masks["left"], masks["right"])

def detect_notes(
    video_path: str | Path,
    config: DetectorConfig | None = None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: Callable[[], bool] | None = None,
) -> tuple[list[NoteEvent], float]:
    """Detect coloured notes and estimate their real visual duration.

    Blue notes are assigned to the left hand and green notes to the right
    hand. Tracking is independent for each (pitch, hand) pair, so the hand
    separation is retained in the resulting MIDI channels.
    """
    config = config or DetectorConfig()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Impossibile aprire il video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    if fps < 1:
        fps = 30.0
    total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))

    hands = ("left", "right")
    keys = [(p, h) for p in range(config.pitch_min, config.pitch_max + 1) for h in hands]
    active = {key: False for key in keys}
    starts: dict[tuple[int, str], int] = {}
    missing = {key: 0 for key in keys}
    events: list[NoteEvent] = []

    frame_index = 0
    while True:
        if stop_callback and stop_callback():
            cap.release()
            raise InterruptedError("Conversione annullata dall'utente.")

        ok, frame = cap.read()
        if not ok:
            break

        masks = _make_color_masks(frame, config)
        present: set[tuple[int, str]] = set()

        for hand, mask in masks.items():
            n, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
            for i in range(1, n):
                x, y, w, h, area = stats[i]
                if area < config.min_component_area:
                    continue
                if not (config.min_component_width <= w <= config.max_component_width):
                    continue
                # Once a bar reaches the trigger line, its visible height can
                # become small because the lower part is clipped by the ROI.
                if h < max(3, min(config.min_component_height, 5)):
                    continue

                bottom = y + config.roll_top_y + h
                if bottom < config.keyboard_line_y - config.onset_margin_px:
                    continue

                center_x = x + w / 2.0
                pitch = x_to_midi(center_x, config)
                if pitch is not None:
                    present.add((pitch, hand))

            # For notes already active, use a narrow band immediately above
            # the keyboard as a low-cost continuation test. This prevents a
            # note-off from being detected too early when its visible bar
            # becomes small near the end of its travel.
            band_start = max(0, mask.shape[0] - 40)
            for pitch, active_hand in keys:
                if active_hand != hand or not active[(pitch, active_hand)] or (pitch, hand) in present:
                    continue
                expected_x = int(round(config.c4_center_x + (pitch - 60) * config.octave_width_px / 12.0))
                x1 = max(0, expected_x - 16)
                x2 = min(mask.shape[1], expected_x + 17)
                if x1 < x2 and np.any(mask[band_start:, x1:x2] > 0):
                    present.add((pitch, hand))

        for key in keys:
            pitch, hand = key
            if key in present:
                missing[key] = 0
                if not active[key]:
                    active[key] = True
                    starts[key] = frame_index
            elif active[key]:
                missing[key] += 1
                if missing[key] > config.release_tolerance_frames:
                    start_frame = starts.pop(key, frame_index)
                    end_frame = frame_index - config.release_tolerance_frames
                    start = start_frame / fps
                    end = end_frame / fps
                    if end > start:
                        events.append(NoteEvent(pitch=pitch, start=start, end=end, hand=hand))
                    active[key] = False
                    missing[key] = 0

        frame_index += 1
        if progress_callback and frame_index % 2 == 0:
            p = 0.35 + 0.60 * min(1.0, frame_index / total_frames)
            progress_callback(p, f"Analisi frame {frame_index}/{total_frames}")

    last_time = max(0.0, (frame_index - 1) / fps)
    for (pitch, hand), is_active in active.items():
        if is_active:
            start_frame = starts.pop((pitch, hand), frame_index)
            if frame_index - 1 > start_frame:
                events.append(NoteEvent(pitch=pitch, start=start_frame / fps, end=last_time, hand=hand))

    cap.release()
    events = _merge_short_gaps(events, max_gap_frames=config.release_tolerance_frames, fps=fps)
    events = [e for e in events if config.min_note_duration <= e.duration <= config.max_note_duration]
    events.sort(key=lambda e: (e.start, e.pitch, e.hand))
    return events, fps

def _merge_short_gaps(events: list[NoteEvent], max_gap_frames: int, fps: float) -> list[NoteEvent]:
    """Merge fragments of the same pitch and hand separated by a short gap."""
    if not events:
        return []
    gap_limit = max(0, max_gap_frames) / max(fps, 1.0)
    grouped: dict[tuple[int, str], list[NoteEvent]] = {}
    for event in sorted(events, key=lambda e: (e.pitch, e.hand, e.start)):
        grouped.setdefault((event.pitch, event.hand), []).append(event)

    merged: list[NoteEvent] = []
    for (pitch, hand), items in grouped.items():
        current = items[0]
        for nxt in items[1:]:
            if nxt.start - current.end <= gap_limit:
                current = NoteEvent(pitch, current.start, max(current.end, nxt.end), current.velocity, hand)
            else:
                merged.append(current)
                current = nxt
        merged.append(current)
    return merged

def normalize_events(events: list[NoteEvent], remove_initial_silence: bool = True) -> list[NoteEvent]:
    if not events:
        return []
    events = [e for e in events if e.duration >= 0.02]
    if not events:
        return []
    if remove_initial_silence:
        offset = min(e.start for e in events)
    else:
        offset = 0.0
    return [
        NoteEvent(e.pitch, max(0.0, e.start - offset), max(0.0, e.end - offset), e.velocity, e.hand)
        for e in events
    ]


def quantize_events(
    events: list[NoteEvent],
    bpm: float,
    subdivision: int = 16,
    strength: float = 0.75,
) -> list[NoteEvent]:
    """Quantize starts/ends toward a musical grid.

    subdivision=16 means a sixteenth-note grid.
    strength=1 gives full quantization; 0 leaves timings unchanged.
    """
    if not events or bpm <= 0 or subdivision <= 0:
        return events

    beat = 60.0 / bpm
    grid = beat * 4.0 / subdivision

    out = []
    for e in events:
        qs = round(e.start / grid) * grid
        start = e.start + (qs - e.start) * strength
        # Shift the complete note by the same amount. This quantizes the
        # onset while preserving the duration measured in the video.
        shift = start - e.start
        end = e.end + shift
        if end <= start:
            end = start + max(e.duration, grid * 0.5, 0.02)
        out.append(NoteEvent(e.pitch, start, end, e.velocity, e.hand))
    return out


def write_midi(
    events: list[NoteEvent],
    output_path: str | Path,
    bpm: float = 102.0,
    velocity: int = 100,
    ticks_per_beat: int = 480,
) -> None:
    if bpm <= 0:
        raise ValueError("Il BPM deve essere maggiore di 0.")

    midi = MidiFile(ticks_per_beat=ticks_per_beat)
    track = MidiTrack()
    midi.tracks.append(track)

    track.append(MetaMessage("track_name", name="Midi Generator v2.3.1", time=0))
    track.append(MetaMessage("set_tempo", tempo=bpm2tempo(bpm), time=0))
    track.append(MetaMessage("time_signature", numerator=4, denominator=4, clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0))
    track.append(Message("program_change", program=0, channel=0, time=0))

    # MIDI ticks are absolute during sorting, then converted to delta times.
    messages: list[tuple[int, int, int, int, int]] = []
    # tuple(abs_tick, order, pitch, velocity, channel); order 0=off, 1=on
    # MIDI channel 0 = blue/left hand; channel 1 = green/right hand.
    for e in events:
        start_tick = max(0, round(e.start * bpm / 60.0 * ticks_per_beat))
        end_tick = max(start_tick + 1, round(e.end * bpm / 60.0 * ticks_per_beat))
        vel = max(1, min(127, velocity if e.velocity == 100 else e.velocity))
        channel = 0 if e.hand == "left" else 1 if e.hand == "right" else 0
        messages.append((start_tick, 1, e.pitch, vel, channel))
        messages.append((end_tick, 0, e.pitch, 0, channel))

    messages.sort(key=lambda m: (m[0], m[1], m[4], m[2]))
    previous_tick = 0
    for tick, order, pitch, vel, channel in messages:
        delta = tick - previous_tick
        previous_tick = tick
        if order == 1:
            track.append(Message("note_on", note=pitch, velocity=vel, channel=channel, time=delta))
        else:
            track.append(Message("note_off", note=pitch, velocity=0, channel=channel, time=delta))

    track.append(MetaMessage("end_of_track", time=0))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    midi.save(str(output_path))


def convert_video_to_midi(
    video_path: str | Path,
    output_path: str | Path,
    bpm: float = 102.0,
    config: DetectorConfig | None = None,
    remove_initial_silence: bool = True,
    quantize: bool = False,
    subdivision: int = 16,
    quantize_strength: float = 0.75,
    velocity: int = 100,
    progress_callback: ProgressCallback | None = None,
    stop_callback: Callable[[], bool] | None = None,
) -> list[NoteEvent]:
    events, _ = detect_notes(
        video_path,
        config=config,
        progress_callback=progress_callback,
        stop_callback=stop_callback,
    )
    if progress_callback:
        progress_callback(0.90, "Elaborazione degli eventi MIDI...")

    events = normalize_events(events, remove_initial_silence=remove_initial_silence)
    if quantize:
        events = quantize_events(events, bpm, subdivision, quantize_strength)

    write_midi(events, output_path, bpm=bpm, velocity=velocity)

    if progress_callback:
        progress_callback(1.0, f"Completato: {len(events)} note rilevate")
    return events
