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


def _make_color_mask(frame: np.ndarray, config: DetectorConfig) -> np.ndarray:
    roi = frame[config.roll_top_y:config.keyboard_line_y]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # Blue notes: hue ~108. Green notes: hue ~44.
    blue = (
        (hsv[:, :, 0] >= 100)
        & (hsv[:, :, 0] <= 120)
        & (hsv[:, :, 1] >= 100)
        & (hsv[:, :, 2] >= 75)
    )
    green = (
        (hsv[:, :, 0] >= 35)
        & (hsv[:, :, 0] <= 60)
        & (hsv[:, :, 1] >= 100)
        & (hsv[:, :, 2] >= 75)
    )

    mask = (blue | green).astype(np.uint8) * 255
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return mask


def detect_notes(
    video_path: str | Path,
    config: DetectorConfig | None = None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: Callable[[], bool] | None = None,
) -> tuple[list[NoteEvent], float]:
    """Detect notes from falling-note piano-roll video.

    Returns (events, fps). Event timing is relative to the beginning of the
    video. The first detected note can be shifted to t=0 by the caller.
    """
    config = config or DetectorConfig()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Impossibile aprire il video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps < 1:
        fps = 30.0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        total_frames = 1

    active = {p: False for p in range(config.pitch_min, config.pitch_max + 1)}
    starts: dict[int, int] = {}
    missing: dict[int, int] = {p: 0 for p in active}
    events: list[NoteEvent] = []

    frame_index = 0
    while True:
        if stop_callback and stop_callback():
            cap.release()
            raise InterruptedError("Conversione annullata dall'utente.")

        ok, frame = cap.read()
        if not ok:
            break

        mask = _make_color_mask(frame, config)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

        present: set[int] = set()

        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < config.min_component_area:
                continue
            if w < config.min_component_width or w > config.max_component_width:
                continue
            if h < config.min_component_height:
                continue
            # Ignore the small progress/status strip immediately below the top UI.
            if y < 20 and h < 25:
                continue

            bottom = y + config.roll_top_y + h
            if bottom < config.keyboard_line_y - config.onset_margin_px:
                continue

            center_x = x + w / 2.0
            pitch = x_to_midi(center_x, config)
            if pitch is not None:
                present.add(pitch)

        for pitch in active:
            if pitch in present:
                missing[pitch] = 0
                if not active[pitch]:
                    active[pitch] = True
                    starts[pitch] = frame_index
            elif active[pitch]:
                missing[pitch] += 1
                if missing[pitch] > config.release_tolerance_frames:
                    start_frame = starts.pop(pitch, frame_index)
                    end_frame = frame_index - config.release_tolerance_frames
                    if end_frame > start_frame:
                        events.append(
                            NoteEvent(
                                pitch=pitch,
                                start=start_frame / fps,
                                end=end_frame / fps,
                            )
                        )
                    active[pitch] = False
                    missing[pitch] = 0

        frame_index += 1

        if progress_callback and frame_index % 2 == 0:
            percent = min(1.0, frame_index / total_frames)
            progress_callback(percent, f"Analisi frame {frame_index}/{total_frames}")

    # Close notes still held at the end.
    last_time = max(0.0, (frame_index - 1) / fps)
    for pitch, is_active in active.items():
        if is_active:
            start_frame = starts.pop(pitch, frame_index)
            if frame_index - 1 > start_frame:
                events.append(
                    NoteEvent(
                        pitch=pitch,
                        start=start_frame / fps,
                        end=last_time,
                    )
                )

    cap.release()
    events.sort(key=lambda n: (n.start, n.pitch))
    return events, fps


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
        NoteEvent(e.pitch, max(0.0, e.start - offset), max(0.0, e.end - offset), e.velocity)
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
        qe = round(e.end / grid) * grid
        start = e.start + (qs - e.start) * strength
        end = e.end + (qe - e.end) * strength
        if end <= start:
            end = start + max(grid * 0.5, 0.02)
        out.append(NoteEvent(e.pitch, start, end, e.velocity))
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

    track.append(MetaMessage("track_name", name="Piano Video MIDI", time=0))
    track.append(MetaMessage("set_tempo", tempo=bpm2tempo(bpm), time=0))
    track.append(MetaMessage("time_signature", numerator=4, denominator=4, clocks_per_click=24, notated_32nd_notes_per_beat=8, time=0))
    track.append(Message("program_change", program=0, channel=0, time=0))

    # MIDI ticks are absolute during sorting, then converted to delta times.
    messages: list[tuple[int, int, int, int]] = []
    # tuple(abs_tick, order, pitch, velocity); order 0=off, 1=on
    for e in events:
        start_tick = max(0, round(e.start * bpm / 60.0 * ticks_per_beat))
        end_tick = max(start_tick + 1, round(e.end * bpm / 60.0 * ticks_per_beat))
        vel = max(1, min(127, velocity if e.velocity == 100 else e.velocity))
        messages.append((start_tick, 1, e.pitch, vel))
        messages.append((end_tick, 0, e.pitch, 0))

    messages.sort(key=lambda m: (m[0], m[1]))
    previous_tick = 0
    for tick, order, pitch, vel in messages:
        delta = tick - previous_tick
        previous_tick = tick
        if order == 1:
            track.append(Message("note_on", note=pitch, velocity=vel, channel=0, time=delta))
        else:
            track.append(Message("note_off", note=pitch, velocity=0, channel=0, time=delta))

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
