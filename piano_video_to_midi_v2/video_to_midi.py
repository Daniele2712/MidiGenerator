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
    hand: str = "unknown"  # Mano assegnata dal profilo colore rilevato.

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
    release_tolerance_frames: int = 3
    min_note_duration: float = 0.035
    max_note_duration: float = 30.0
    auto_detect_colors: bool = True  # Se True, rileva automaticamente i due colori delle note.
    left_hue: float | None = None  # Hue manuale per la mano sinistra, se impostata.
    right_hue: float | None = None  # Hue manuale per la mano destra, se impostata.
    hue_tolerance: float = 14.0  # Tolleranza circolare del colore in gradi OpenCV.
    min_color_saturation: int = 65  # Saturazione minima per considerare un pixel colorato.


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


def _circular_hue_distance(hue: np.ndarray, center: float) -> np.ndarray:
    """Calcola la distanza circolare tra hue e un centro colore."""
    distance = np.abs(hue.astype(np.float32) - float(center))  # Calcola la distanza assoluta.
    return np.minimum(distance, 180.0 - distance)  # Gestisce il passaggio circolare 179->0.


def _hue_mask(hsv: np.ndarray, center: float, tolerance: float, min_saturation: int) -> np.ndarray:
    """Crea una maschera per un colore HSV con tolleranza circolare."""
    hue_distance = _circular_hue_distance(hsv[:, :, 0], center)  # Misura la distanza dal colore richiesto.
    saturation_ok = hsv[:, :, 1] >= min_saturation  # Elimina le aree poco colorate.
    value_ok = hsv[:, :, 2] >= 45  # Elimina le aree troppo scure.
    return (hue_distance <= tolerance) & saturation_ok & value_ok  # Restituisce i pixel compatibili.


def _find_two_color_centers(frame_samples: list[np.ndarray], config: DetectorConfig) -> tuple[float, float]:
    """Trova due colori dominanti nell'area delle note usando un istogramma HSV."""
    histogram = np.zeros(180, dtype=np.float64)  # Crea l'istogramma dei 180 valori hue possibili.
    for frame in frame_samples:  # Analizza ogni fotogramma campionato.
        roi = frame[config.roll_top_y:config.keyboard_line_y]  # Isola l'area sopra la tastiera.
        roi = roi[min(80, max(0, roi.shape[0] - 1)):]  # Esclude la barra di avanzamento superiore quando presente.
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)  # Converte il fotogramma da BGR a HSV.
        valid = (hsv[:, :, 1] >= config.min_color_saturation) & (hsv[:, :, 2] >= 45)  # Seleziona pixel colorati.
        histogram += np.bincount(hsv[:, :, 0][valid].ravel(), minlength=180)  # Conta le tonalità presenti.
    if histogram.sum() == 0:  # Controlla se non sono stati trovati pixel colorati.
        return 110.0, 50.0  # Usa un fallback blu/verde compatibile con la versione precedente.
    smooth = np.convolve(np.r_[histogram[-4:], histogram, histogram[:4]], np.ones(9), mode="same")[4:-4]  # Smussa l'istogramma.
    first = int(np.argmax(smooth))  # Seleziona il primo picco dominante.
    circular_distance = np.minimum(np.abs(np.arange(180) - first), 180 - np.abs(np.arange(180) - first))  # Calcola le distanze circolari.
    second_scores = smooth.copy()  # Copia i punteggi del secondo picco.
    second_scores[circular_distance < 18] = 0  # Evita di scegliere due picchi dello stesso colore.
    second = int(np.argmax(second_scores))  # Seleziona il secondo picco.
    return float(first), float(second)  # Restituisce i due centri hue rilevati.


def _assign_hues_to_hands(frame_samples: list[np.ndarray], centers: tuple[float, float], config: DetectorConfig) -> tuple[float, float]:
    """Assegna il colore con posizione media più bassa alla mano sinistra."""
    x_values: list[list[float]] = [[], []]  # Prepara le coordinate X per i due colori.
    for frame in frame_samples:  # Analizza i fotogrammi campionati.
        roi = frame[config.roll_top_y:config.keyboard_line_y]  # Isola l'area delle note.
        roi = roi[min(80, max(0, roi.shape[0] - 1)):]  # Esclude la barra di avanzamento superiore quando presente.
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)  # Converte il frame in HSV.
        for index, center in enumerate(centers):  # Analizza ciascun centro colore.
            mask = _hue_mask(hsv, center, config.hue_tolerance, config.min_color_saturation)  # Crea la maschera del colore.
            ys, xs = np.where(mask)  # Estrae le coordinate dei pixel colorati.
            if len(xs):  # Verifica che il colore sia presente.
                x_values[index].extend(xs.astype(float).tolist())  # Memorizza le coordinate X.
    medians = [float(np.median(values)) if values else float("inf") for values in x_values]  # Calcola la posizione media di ogni colore.
    if medians[0] <= medians[1]:  # Verifica quale colore è più a sinistra.
        return centers[0], centers[1]  # Primo colore a sinistra, secondo a destra.
    return centers[1], centers[0]  # Inverte i colori se il secondo è più a sinistra.


def _sample_frames(video_path: str | Path, config: DetectorConfig, limit: int = 24) -> list[np.ndarray]:
    """Campiona alcuni fotogrammi per stimare automaticamente i colori."""
    cap = cv2.VideoCapture(str(video_path))  # Apre il video per la fase di calibrazione colore.
    samples: list[np.ndarray] = []  # Crea l'elenco dei fotogrammi campionati.
    if not cap.isOpened():  # Verifica l'apertura del video.
        return samples  # Restituisce una lista vuota se il video non è leggibile.
    total = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))  # Recupera il numero totale di fotogrammi.
    indices = np.linspace(0, total - 1, min(limit, total), dtype=int)  # Distribuisce i campioni lungo il video.
    for index in np.unique(indices):  # Visita ogni indice senza duplicati.
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(index))  # Sposta la lettura al fotogramma richiesto.
        ok, frame = cap.read()  # Legge il fotogramma.
        if ok:  # Controlla la lettura.
            samples.append(frame)  # Salva il fotogramma valido.
    cap.release()  # Chiude il video di calibrazione.
    return samples  # Restituisce i campioni disponibili.


def _make_color_masks(frame: np.ndarray, config: DetectorConfig, color_centers: tuple[float, float] | None = None) -> dict[str, np.ndarray]:
    """Crea due maschere colore e le associa genericamente a sinistra/destra."""
    roi = frame[config.roll_top_y:config.keyboard_line_y]  # Isola l'area del piano roll.
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)  # Converte l'area in HSV.
    if color_centers is None:  # Controlla se non sono stati forniti centri colore.
        color_centers = (110.0, 50.0)  # Usa un fallback generico per compatibilità.
    left_hue, right_hue = color_centers  # Estrae i due colori assegnati alle mani.
    left = _hue_mask(hsv, left_hue, config.hue_tolerance, config.min_color_saturation)  # Maschera della mano sinistra.
    right = _hue_mask(hsv, right_hue, config.hue_tolerance, config.min_color_saturation)  # Maschera della mano destra.
    masks: dict[str, np.ndarray] = {}  # Prepara il dizionario delle maschere.
    for hand, raw in (("left", left), ("right", right)):  # Elabora separatamente i due colori.
        # Non applicare MORPH_CLOSE: potrebbe chiudere i vuoti tra due note consecutive.
        masks[hand] = (raw.astype(np.uint8) * 255)  # Converte la maschera booleana in immagine binaria senza unire le note.
    return masks  # Restituisce le maschere finali mantenendo le separazioni verticali.


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

    Notes are assigned to left/right hands using the two detected or manual
    color profiles. Tracking is independent for each (pitch, hand) pair, and
    neighbouring events are never merged automatically.
    """
    config = config or DetectorConfig()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Impossibile aprire il video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    if fps < 1:
        fps = 30.0
    total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))

    frame_samples = _sample_frames(video_path, config) if config.auto_detect_colors else []  # Campiona frame per i colori.
    if config.left_hue is not None and config.right_hue is not None:  # Controlla se i colori sono impostati manualmente.
        color_centers = (float(config.left_hue), float(config.right_hue))  # Usa i colori manuali.
    elif frame_samples:  # Controlla se esistono campioni validi.
        detected_centers = _find_two_color_centers(frame_samples, config)  # Rileva i due colori dominanti.
        color_centers = _assign_hues_to_hands(frame_samples, detected_centers, config)  # Associa i colori alle mani tramite posizione.
    else:  # Gestisce l'assenza di campioni.
        color_centers = (110.0, 50.0)  # Usa il fallback precedente.
    hands = ("left", "right")  # Mantiene due mani indipendenti.
    keys = [(p, h) for p in range(config.pitch_min, config.pitch_max + 1) for h in hands]  # Crea tutte le coppie pitch/mano.
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

        masks = _make_color_masks(frame, config, color_centers)
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

            # Non utilizziamo più una fascia di continuità: una nota resta attiva
            # soltanto se una barra valida viene rilevata nel fotogramma corrente.
            # In questo modo uno spazio reale tra due barre genera un rilascio.

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
    # Do not merge neighbouring events automatically. In Synthesia-style
    # videos, repeated notes of the same pitch can be separated by a very
    # short visual gap; merging them would incorrectly turn several notes
    # into one long note. Fragment prevention is handled by the continuation
    # band and release tolerance during tracking instead.
    events = [e for e in events if config.min_note_duration <= e.duration <= config.max_note_duration]
    events.sort(key=lambda e: (e.start, e.pitch, e.hand))
    return events, fps

def _merge_short_gaps(events: list[NoteEvent], max_gap_frames: int, fps: float) -> list[NoteEvent]:
    """Legacy helper retained for compatibility; it is not used by detection."""
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

    track.append(MetaMessage("track_name", name="Midi Generator v2.3.2", time=0))
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
    try:
        from visual_compare import create_comparison_report
        report_path = Path(output_path).with_name(Path(output_path).stem + "_comparison.png")
        create_comparison_report(video_path, events, report_path)
    except Exception:
        pass

    if progress_callback:
        progress_callback(1.0, f"Completato: {len(events)} note rilevate")
    return events
