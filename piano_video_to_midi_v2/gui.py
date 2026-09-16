from __future__ import annotations

import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import cv2
import customtkinter as ctk
from PIL import Image, ImageTk

from video_to_midi import DetectorConfig, NoteEvent, convert_video_to_midi
from auto_calibration import auto_calibrate, AutoCalibration


class VideoPreview(ctk.CTkFrame):
    """Video preview with pixel-coordinate rulers around the image.

    The rulers always refer to the ORIGINAL video resolution, not the resized
    image shown on screen. A mouse crosshair and live X/Y readout make it easy
    to find coordinates to enter in the detector parameters.
    """

    RULER_SIZE = 38
    BG = "#111111"
    RULER_BG = "#1b1b1b"
    AXIS = "#777777"
    TICK = "#888888"
    TEXT = "#bdbdbd"
    CROSSHAIR = "#ffcc00"

    def __init__(self, master, on_time_changed=None):
        super().__init__(master, fg_color="transparent")
        self.on_time_changed = on_time_changed
        self.cap = None
        self.path = None
        self.fps = 30.0
        self.frame_count = 0
        self.duration = 0.0
        self.current_frame = 0
        self.video_width = 0
        self.video_height = 0
        self.playing = False
        self.photo = None
        self._after_id = None
        self._display_rect = None  # (left, top, right, bottom) in canvas coords
        self._last_frame_rgb = None
        self._mouse_x = None
        self._mouse_y = None
        self.calibration = None

        # Layout: Y ruler | image area, with X ruler above image area.
        self.y_ruler = tk.Canvas(
            self, width=self.RULER_SIZE, bg=self.RULER_BG,
            highlightthickness=0, bd=0
        )
        self.y_ruler.grid(row=0, column=0, sticky="ns", pady=(8, 4))

        self.center = tk.Frame(self, bg=self.BG, highlightthickness=0, bd=0)
        self.center.grid(row=0, column=1, sticky="nsew", padx=(0, 0), pady=(8, 4))
        self.center.grid_rowconfigure(0, weight=0)
        self.center.grid_rowconfigure(1, weight=1)
        self.center.grid_columnconfigure(0, weight=1)

        self.x_ruler = tk.Canvas(
            self.center, height=self.RULER_SIZE, bg=self.RULER_BG,
            highlightthickness=0, bd=0
        )
        self.x_ruler.grid(row=0, column=0, sticky="ew")

        self.image_canvas = tk.Canvas(
            self.center, bg=self.BG, highlightthickness=0, bd=0,
            cursor="crosshair"
        )
        self.image_canvas.grid(row=1, column=0, sticky="nsew")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.image_canvas.bind("<Motion>", self._on_mouse_move)
        self.image_canvas.bind("<Leave>", self._on_mouse_leave)
        self.image_canvas.bind("<Configure>", lambda _e: self._redraw_current_frame())
        self.x_ruler.bind("<Configure>", lambda _e: self._draw_rulers())
        self.y_ruler.bind("<Configure>", lambda _e: self._draw_rulers())

        # Coordinate readout / legend.
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 2))
        self.coordinate_label = ctk.CTkLabel(
            info,
            text="Mouse: X — px   Y — px    |    Video: — × — px",
            anchor="w",
            font=("Arial", 11),
        )
        self.coordinate_label.pack(side="left")
        ctk.CTkLabel(
            info,
            text="Gli assi indicano i pixel del video originale",
            anchor="e",
            font=("Arial", 10),
        ).pack(side="right")

        controls = ctk.CTkFrame(self)
        controls.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=4)

        self.play_btn = ctk.CTkButton(
            controls, text="▶ Riproduci", width=110, command=self.toggle_play
        )
        self.play_btn.pack(side="left", padx=5, pady=6)

        self.time_label = ctk.CTkLabel(controls, text="00:00 / 00:00")
        self.time_label.pack(side="right", padx=10)

        self.slider = ctk.CTkSlider(controls, from_=0, to=1, command=self.seek)
        self.slider.pack(side="left", fill="x", expand=True, padx=10)
        self.slider.set(0)

    def load(self, path: str):
        self.close()
        self.path = path
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise RuntimeError("Impossibile aprire il video.")

        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.video_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.video_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.duration = self.frame_count / self.fps if self.fps else 0.0
        self.slider.configure(to=max(self.duration, 0.01))
        self.coordinate_label.configure(
            text=f"Mouse: X — px   Y — px    |    Video: {self.video_width} × {self.video_height} px"
        )
        self.show_frame(0)

    def _get_display_geometry(self):
        """Return scaled image geometry and scale factor for the current canvas."""
        if self.video_width <= 0 or self.video_height <= 0:
            return None

        canvas_w = max(1, self.image_canvas.winfo_width())
        canvas_h = max(1, self.image_canvas.winfo_height())
        scale = min(canvas_w / self.video_width, canvas_h / self.video_height)
        display_w = max(1, int(round(self.video_width * scale)))
        display_h = max(1, int(round(self.video_height * scale)))
        left = (canvas_w - display_w) / 2
        top = (canvas_h - display_h) / 2
        return left, top, display_w, display_h, scale

    def _render_frame(self, rgb):
        self._last_frame_rgb = rgb
        geometry = self._get_display_geometry()
        if geometry is None:
            return

        left, top, display_w, display_h, _scale = geometry
        image = Image.fromarray(rgb).resize((display_w, display_h), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)

        self.image_canvas.delete("frame")
        self.image_canvas.create_image(
            left, top, anchor="nw", image=self.photo, tags="frame"
        )
        self._display_rect = (left, top, left + display_w, top + display_h)
        self._draw_rulers()
        self._draw_calibration()
        self._draw_crosshair()

    def _redraw_current_frame(self):
        if self._last_frame_rgb is not None:
            self._render_frame(self._last_frame_rgb)
        else:
            self._draw_rulers()
            self._draw_calibration()

    def show_frame(self, frame_number: int):
        if not self.cap:
            return
        frame_number = max(0, min(frame_number, max(0, self.frame_count - 1)))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = self.cap.read()
        if not ok:
            return
        self.current_frame = frame_number
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._render_frame(rgb)
        current_time = self.current_frame / self.fps
        self.slider.set(current_time)
        self.time_label.configure(
            text=f"{format_time(current_time)} / {format_time(self.duration)}"
        )
        if self.on_time_changed:
            self.on_time_changed(current_time)

    def seek(self, value):
        if self.cap and not self.playing:
            self.show_frame(int(float(value) * self.fps))

    def toggle_play(self):
        if not self.cap:
            return
        self.playing = not self.playing
        self.play_btn.configure(
            text="⏸ Pausa" if self.playing else "▶ Riproduci"
        )
        if self.playing:
            self._play_loop()

    def _play_loop(self):
        if not self.playing or not self.cap:
            return
        if self.current_frame >= self.frame_count - 1:
            self.playing = False
            self.play_btn.configure(text="▶ Riproduci")
            return
        self.show_frame(self.current_frame + 1)
        delay = max(1, int(1000 / self.fps))
        self._after_id = self.after(delay, self._play_loop)

    def set_calibration(self, calibration):
        self.calibration = calibration
        self._draw_calibration()

    def _draw_calibration(self):
        self.image_canvas.delete("calibration")
        if self.calibration is None or not self._display_rect or self.video_width <= 0:
            return
        left, top, right, bottom = self._display_rect
        sx = (right - left) / max(1, self.video_width)
        sy = (bottom - top) / max(1, self.video_height)
        y = top + self.calibration.keyboard_line_y * sy
        x = left + self.calibration.c4_center_x * sx
        self.image_canvas.create_line(left, y, right, y, fill="#ff4040", width=2, dash=(8, 4), tags="calibration")
        self.image_canvas.create_line(x, top, x, bottom, fill="#00e5ff", width=2, dash=(8, 4), tags="calibration")
        self.image_canvas.create_text(left + 8, max(top + 12, y - 8), anchor="sw",
                                      text=f"Tastiera Y={self.calibration.keyboard_line_y}px",
                                      fill="#ff7070", font=("Arial", 10, "bold"), tags="calibration")
        self.image_canvas.create_text(min(right - 8, x + 8), top + 8, anchor="nw",
                                      text=f"C4 X={self.calibration.c4_center_x:.1f}px",
                                      fill="#50eaff", font=("Arial", 10, "bold"), tags="calibration")

    def _on_mouse_move(self, event):
        if not self._display_rect or self.video_width <= 0:
            return
        left, top, right, bottom = self._display_rect
        if left <= event.x <= right and top <= event.y <= bottom:
            scale_x = self.video_width / max(1, right - left)
            scale_y = self.video_height / max(1, bottom - top)
            x = int(round((event.x - left) * scale_x))
            y = int(round((event.y - top) * scale_y))
            x = max(0, min(self.video_width - 1, x))
            y = max(0, min(self.video_height - 1, y))
            self._mouse_x, self._mouse_y = x, y
            self.coordinate_label.configure(
                text=f"Mouse: X {x:4d} px   Y {y:4d} px    |    Video: {self.video_width} × {self.video_height} px"
            )
            self._draw_crosshair()
        else:
            self._mouse_x = self._mouse_y = None
            self.coordinate_label.configure(
                text=f"Mouse: X — px   Y — px    |    Video: {self.video_width} × {self.video_height} px"
            )
            self._draw_crosshair()

    def _on_mouse_leave(self, _event):
        self._mouse_x = self._mouse_y = None
        if self.video_width:
            self.coordinate_label.configure(
                text=f"Mouse: X — px   Y — px    |    Video: {self.video_width} × {self.video_height} px"
            )
        self._draw_crosshair()

    def _draw_crosshair(self):
        self.image_canvas.delete("crosshair")
        if self._mouse_x is None or self._mouse_y is None or not self._display_rect:
            return
        left, top, right, bottom = self._display_rect
        scale = (right - left) / max(1, self.video_width)
        cx = left + self._mouse_x * scale
        cy = top + self._mouse_y * scale
        self.image_canvas.create_line(
            cx, top, cx, bottom, fill=self.CROSSHAIR, width=1,
            dash=(4, 4), tags="crosshair"
        )
        self.image_canvas.create_line(
            left, cy, right, cy, fill=self.CROSSHAIR, width=1,
            dash=(4, 4), tags="crosshair"
        )

    @staticmethod
    def _nice_step(span: int) -> int:
        """Choose a readable ruler interval in pixels."""
        target = max(1, span // 10)
        for step in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
            if step >= target:
                return step
        return 10000

    def _draw_rulers(self):
        self.x_ruler.delete("all")
        self.y_ruler.delete("all")
        if self.video_width <= 0 or self.video_height <= 0 or not self._display_rect:
            return

        left, top, right, bottom = self._display_rect
        display_w = right - left
        display_h = bottom - top
        x_scale = display_w / self.video_width
        y_scale = display_h / self.video_height

        # Ruler axis lines.
        self.x_ruler.create_line(left, self.RULER_SIZE - 1, right, self.RULER_SIZE - 1, fill=self.AXIS)
        self.y_ruler.create_line(self.RULER_SIZE - 1, top, self.RULER_SIZE - 1, bottom, fill=self.AXIS)

        # X ruler: 0 at left edge of video, values increase to the right.
        x_step = self._nice_step(self.video_width)
        x = 0
        while x <= self.video_width:
            px = left + x * x_scale
            tick = 12 if x % (x_step * 5) == 0 else 7
            self.x_ruler.create_line(px, self.RULER_SIZE - tick, px, self.RULER_SIZE, fill=self.TICK)
            if x % (x_step * 5) == 0 or x == 0:
                self.x_ruler.create_text(
                    px + 2, 8, text=str(x), fill=self.TEXT,
                    anchor="nw", font=("Arial", 8)
                )
            x += x_step

        # Y ruler: 0 at top edge, values increase downward as in image coordinates.
        y_step = self._nice_step(self.video_height)
        y = 0
        ruler_h = self.y_ruler.winfo_height()
        while y <= self.video_height:
            py = top + y * y_scale
            tick = 12 if y % (y_step * 5) == 0 else 7
            self.y_ruler.create_line(self.RULER_SIZE - tick, py, self.RULER_SIZE, py, fill=self.TICK)
            if y % (y_step * 5) == 0 or y == 0:
                self.y_ruler.create_text(
                    self.RULER_SIZE - 4, py + 1, text=str(y), fill=self.TEXT,
                    anchor="e", font=("Arial", 8)
                )
            y += y_step

    def close(self):
        self.playing = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self.cap:
            self.cap.release()
            self.cap = None
        self.photo = None
        self._last_frame_rgb = None
        self._display_rect = None
        self.calibration = None


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class MidiPreview(ctk.CTkFrame):
    """Anteprima MIDI con pitch sull'asse X e tempo sull'asse Y."""

    def __init__(self, master):
        super().__init__(master)
        self.events: list[NoteEvent] = []  # Memorizza gli eventi MIDI da visualizzare.
        self.pixels_per_second = 90.0  # Aumenta la scala verticale per rendere le note leggibili.
        self.pitch_width = 24.0  # Imposta la larghezza grafica di ogni semitono.
        self.left_margin = 55  # Riserva spazio alle etichette delle ottave.
        self.top_margin = 25  # Riserva spazio al titolo dell'asse X.
        self.bottom_margin = 25  # Riserva spazio inferiore al grafico.

        frame = ctk.CTkFrame(self)  # Crea il contenitore dei canvas e delle barre di scorrimento.
        frame.pack(fill="both", expand=True, padx=8, pady=8)  # Espande il contenitore nella scheda.
        frame.grid_rowconfigure(0, weight=1)  # Permette al canvas di espandersi verticalmente.
        frame.grid_columnconfigure(0, weight=1)  # Permette al canvas di espandersi orizzontalmente.

        self.canvas = tk.Canvas(frame, bg="#171717", highlightthickness=0)  # Crea l'area di disegno.
        self.v_scroll = ctk.CTkScrollbar(frame, orientation="vertical", command=self.canvas.yview)  # Crea lo scroll verticale del tempo.
        self.h_scroll = ctk.CTkScrollbar(frame, orientation="horizontal", command=self.canvas.xview)  # Crea lo scroll orizzontale delle note.
        self.canvas.configure(yscrollcommand=self.v_scroll.set, xscrollcommand=self.h_scroll.set)  # Collega gli scroll al canvas.
        self.canvas.grid(row=0, column=0, sticky="nsew")  # Posiziona il canvas nella griglia.
        self.v_scroll.grid(row=0, column=1, sticky="ns")  # Posiziona la barra verticale a destra.
        self.h_scroll.grid(row=1, column=0, sticky="ew")  # Posiziona la barra orizzontale in basso.

        self.info = ctk.CTkLabel(self, text="Converti un video per vedere l'anteprima MIDI")  # Crea l'etichetta informativa.
        self.info.pack(pady=(0, 8))  # Posiziona l'etichetta sotto il grafico.
        self.bind("<Configure>", lambda _event: self.draw())  # Ridisegna il grafico quando cambia la dimensione.

    def set_events(self, events: list[NoteEvent]):
        self.events = events  # Aggiorna gli eventi visualizzati.
        self.info.configure(text=f"Note rilevate: {len(events)} • X=pitch • Y=tempo (0 in fondo)")  # Mostra un riepilogo degli assi.
        self.draw()  # Ridisegna immediatamente il grafico.

    def draw(self):
        self.canvas.delete("all")  # Cancella il disegno precedente.
        if not self.events:  # Controlla se non ci sono eventi da visualizzare.
            self.canvas.create_text(350, 180, text="Nessuna nota", fill="white", font=("Arial", 16))  # Mostra un messaggio vuoto.
            self.canvas.configure(scrollregion=(0, 0, 700, 400))  # Imposta una regione minima scorrevole.
            return  # Interrompe il disegno quando non ci sono note.

        min_pitch = min(e.pitch for e in self.events)  # Trova il pitch più basso.
        max_pitch = max(e.pitch for e in self.events)  # Trova il pitch più alto.
        max_time = max(e.end for e in self.events) or 1.0  # Trova la durata totale del brano.
        pitch_span = max(1, max_pitch - min_pitch + 1)  # Calcola il numero di semitoni rappresentati.
        plot_w = max(700, self.left_margin + pitch_span * self.pitch_width + 30)  # Calcola la larghezza totale del grafico.
        plot_h = max(500, self.top_margin + max_time * self.pixels_per_second + self.bottom_margin)  # Calcola l'altezza in base al tempo.
        x0 = self.left_margin  # Definisce l'inizio dell'area delle note sull'asse X.
        y0 = self.top_margin  # Definisce l'inizio dell'area delle note sull'asse Y.
        baseline = plot_h - self.bottom_margin  # Posiziona il tempo zero in fondo al grafico.

        self.canvas.create_text(x0, 8, anchor="w", text="Pitch / note", fill="#dddddd", font=("Arial", 10, "bold"))  # Scrive il titolo dell'asse X.
        self.canvas.create_text(8, y0, anchor="w", text="Tempo", fill="#dddddd", font=("Arial", 10, "bold"))  # Scrive il titolo dell'asse Y.

        for pitch in range(min_pitch, max_pitch + 1):  # Disegna una colonna per ogni semitono.
            x = x0 + (pitch - min_pitch) * self.pitch_width  # Calcola la posizione orizzontale del pitch.
            if pitch % 12 in (0, 5):  # Evidenzia alcune note per facilitare la lettura.
                self.canvas.create_line(x, y0, x, plot_h - self.bottom_margin, fill="#333333")  # Disegna la griglia verticale.
            if pitch % 12 == 0:  # Etichetta soltanto le note C per evitare sovraccarico visivo.
                self.canvas.create_text(x + 2, y0 - 12, anchor="w", text=midi_name(pitch), fill="#aaaaaa", font=("Arial", 8))  # Scrive il nome dell'ottava.

        sec = 0.0  # Inizializza il tempo della griglia.
        step = 1.0 if max_time <= 60 else 5.0  # Sceglie un intervallo leggibile per la griglia temporale.
        while sec <= max_time:  # Disegna le righe temporali lungo tutto il brano.
            y = baseline - sec * self.pixels_per_second  # Converte il tempo in coordinate verticali dal basso verso l'alto.
            self.canvas.create_line(x0, y, plot_w - 15, y, fill="#292929")  # Disegna una linea orizzontale del tempo.
            self.canvas.create_text(5, y, anchor="w", text=f"{sec:g}s", fill="#aaaaaa", font=("Arial", 8))  # Scrive il tempo sulla sinistra.
            sec += step  # Passa al successivo riferimento temporale.

        for event in self.events:  # Disegna ogni evento MIDI individualmente.
            x1 = x0 + (event.pitch - min_pitch) * self.pitch_width + 1  # Calcola il bordo sinistro della nota.
            x2 = x1 + self.pitch_width - 2  # Calcola il bordo destro della nota.
            y1 = baseline - event.end * self.pixels_per_second  # Calcola il bordo superiore della nota.
            y2 = baseline - event.start * self.pixels_per_second  # Calcola il bordo inferiore della nota.
            fill = "#2f80ed" if event.hand == "left" else "#35c759" if event.hand == "right" else "#4da3ff"  # Sceglie il colore in base alla mano.
            self.canvas.create_rectangle(x1, min(y1, y2), x2, max(y1, y2, min(y1, y2) + 3), fill=fill, outline="")  # Disegna la nota mantenendo la durata.

        self.canvas.configure(scrollregion=(0, 0, plot_w, plot_h))  # Rende scorribile l'intero piano temporale.


def midi_name(pitch: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Midi Generator v2.4")
        self.geometry("1120x850")
        self.minsize(980, 760)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.video_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.bpm = tk.StringVar(value="102")
        self.keyboard_line = tk.StringVar(value="628")
        self.c4_x = tk.StringVar(value="830")
        self.octave_width = tk.StringVar(value="400")
        self.remove_silence = tk.BooleanVar(value=True)
        self.quantize = tk.BooleanVar(value=False)
        self.subdivision = tk.StringVar(value="16")
        self.quantize_strength = tk.StringVar(value="0.75")
        self.velocity = tk.StringVar(value="100")
        self.release_tolerance = tk.StringVar(value="3")
        self.min_note_duration = tk.StringVar(value="0.035")
        self.auto_detect_colors = tk.BooleanVar(value=True)
        self.left_hue = tk.StringVar(value="")
        self.right_hue = tk.StringVar(value="")
        self.hue_tolerance = tk.StringVar(value="14")
        self.stop_requested = False
        self.last_events: list[NoteEvent] = []

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build_ui()

    def build_ui(self):
        header = ctk.CTkFrame(self, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="🎹  Midi Generator v2.4", font=("Arial", 28, "bold")).pack(side="left", padx=25, pady=18)
        ctk.CTkLabel(header, text="Falling Notes Converter • Auto Calibration + Pixel rulers", font=("Arial", 13)).pack(side="left", padx=5, pady=18)

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=18, pady=18)
        video_tab = tabs.add("Video & Conversione")
        midi_tab = tabs.add("Anteprima MIDI")

        settings = ctk.CTkScrollableFrame(video_tab, width=350, label_text="Impostazioni")
        settings.pack(side="left", fill="y", padx=(10, 8), pady=10)
        preview_frame = ctk.CTkFrame(video_tab)
        preview_frame.pack(side="left", fill="both", expand=True, padx=(8, 10), pady=10)

        self.preview = VideoPreview(preview_frame)
        self.preview.pack(fill="both", expand=True)

        self.add_section(settings, "VIDEO")
        self.add_path_row(settings, self.video_path, "Seleziona video", self.select_video, "*.mov *.mp4 *.mkv *.avi")
        self.add_path_row(settings, self.output_path, "File MIDI", self.select_output, "*.mid")

        self.add_section(settings, "PARAMETRI")
        self.add_entry(settings, "BPM", self.bpm)
        self.add_entry(settings, "Linea tastiera Y", self.keyboard_line)
        self.add_entry(settings, "Centro C4 X", self.c4_x)
        self.add_entry(settings, "Larghezza ottava (px)", self.octave_width)

        self.auto_calibrate_btn = ctk.CTkButton(
            settings, text="⚙  CALIBRA PARAMETRI AUTOMATICAMENTE",
            height=38, command=self.start_auto_calibration
        )
        self.auto_calibrate_btn.pack(fill="x", padx=15, pady=(7, 6))

        self.calibration_status = ctk.CTkLabel(
            settings, text="Calibrazione: manuale", wraplength=300, justify="left",
            font=("Arial", 10)
        )
        self.calibration_status.pack(anchor="w", padx=15, pady=(0, 7))

        self.add_entry(settings, "Velocity", self.velocity)
        self.add_entry(settings, "Tolleranza rilascio (frame)", self.release_tolerance)
        self.add_entry(settings, "Durata minima (s)", self.min_note_duration)

        self.add_section(settings, "COLORI MANI")
        ctk.CTkCheckBox(settings, text="Rileva automaticamente i colori", variable=self.auto_detect_colors).pack(anchor="w", padx=15, pady=6)
        self.add_entry(settings, "Hue mano sinistra (opz.)", self.left_hue)
        self.add_entry(settings, "Hue mano destra (opz.)", self.right_hue)
        self.add_entry(settings, "Tolleranza hue", self.hue_tolerance)
        ctk.CTkLabel(settings, text="Se i campi Hue sono vuoti, il programma individua i due colori dominanti e li assegna in base alla posizione orizzontale.", wraplength=310, justify="left", font=("Arial", 10)).pack(anchor="w", padx=15, pady=(2, 8))

        ctk.CTkLabel(
            settings,
            text="Suggerimento: passa il mouse sul video per leggere X/Y in pixel.",
            wraplength=310,
            justify="left",
            font=("Arial", 10),
        ).pack(anchor="w", padx=15, pady=(3, 8))

        self.add_section(settings, "OPZIONI")
        ctk.CTkCheckBox(settings, text="Rimuovi silenzio iniziale", variable=self.remove_silence).pack(anchor="w", padx=15, pady=6)
        ctk.CTkCheckBox(settings, text="Quantizza note", variable=self.quantize).pack(anchor="w", padx=15, pady=6)
        self.add_entry(settings, "Suddivisione", self.subdivision)
        self.add_entry(settings, "Forza quantizzazione", self.quantize_strength)

        self.convert_btn = ctk.CTkButton(settings, text="▶  CONVERTI IN MIDI", height=48, font=("Arial", 15, "bold"), command=self.start_conversion)
        self.convert_btn.pack(fill="x", padx=15, pady=(25, 8))
        self.cancel_btn = ctk.CTkButton(settings, text="Annulla", height=34, fg_color="#555555", command=self.cancel_conversion, state="disabled")
        self.cancel_btn.pack(fill="x", padx=15, pady=5)

        self.progress = ctk.CTkProgressBar(settings)
        self.progress.pack(fill="x", padx=15, pady=(18, 4))
        self.progress.set(0)
        self.status = ctk.CTkLabel(settings, text="Pronto", wraplength=300)
        self.status.pack(anchor="w", padx=15, pady=5)
        self.stats = ctk.CTkLabel(settings, text="Note: —\nDurata: —")
        self.stats.pack(anchor="w", padx=15, pady=10)

        self.midi_preview = MidiPreview(midi_tab)
        self.midi_preview.pack(fill="both", expand=True, padx=10, pady=10)

    def add_section(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=("Arial", 12, "bold")).pack(anchor="w", padx=15, pady=(15, 5))

    def add_entry(self, parent, label, variable):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=3)
        ctk.CTkLabel(row, text=label, width=145, anchor="w").pack(side="left")
        ctk.CTkEntry(row, textvariable=variable, width=120).pack(side="right")

    def add_path_row(self, parent, variable, button_text, command, extension):
        entry = ctk.CTkEntry(parent, textvariable=variable, placeholder_text="Nessun file selezionato")
        entry.pack(fill="x", padx=15, pady=(3, 5))
        ctk.CTkButton(parent, text=button_text, command=command).pack(fill="x", padx=15, pady=(0, 4))

    def select_video(self):
        path = filedialog.askopenfilename(
            title="Seleziona video",
            filetypes=[("Video", "*.mov *.mp4 *.mkv *.avi"), ("Tutti i file", "*.*")],
        )
        if not path:
            return
        self.video_path.set(path)
        if not self.output_path.get():
            self.output_path.set(str(Path(path).with_suffix(".mid")))
        try:
            self.preview.load(path)
            self.status.configure(text="Video caricato. Avvio calibrazione automatica...")
            self.start_auto_calibration()
        except Exception as exc:
            messagebox.showerror("Errore video", str(exc))

    def start_auto_calibration(self):
        if not self.video_path.get():
            messagebox.showwarning("Video mancante", "Seleziona prima un video.")
            return
        self.auto_calibrate_btn.configure(state="disabled")
        self.calibration_status.configure(text="Calibrazione: analisi automatica in corso...")
        self.status.configure(text="Calibrazione automatica: ricerca linea tastiera e geometria dei tasti...")

        thread = threading.Thread(target=self._auto_calibration_worker, daemon=True)
        thread.start()

    def _auto_calibration_worker(self):
        try:
            result = auto_calibrate(
                self.video_path.get(),
                progress_callback=lambda p, s: self.after(0, self.update_progress, p, s),
            )
            self.after(0, self.apply_auto_calibration, result)
        except Exception as exc:
            self.after(0, self.auto_calibration_failed, str(exc))

    def apply_auto_calibration(self, result):
        self.keyboard_line.set(str(result.keyboard_line_y))
        self.c4_x.set(f"{result.c4_center_x:.1f}")
        self.octave_width.set(f"{result.octave_width_px:.1f}")
        self.preview.set_calibration(result)
        confidence_pct = int(round(result.confidence * 100))
        self.calibration_status.configure(
            text=f"✓ Calibrazione automatica ({confidence_pct}% confidenza)\n"
                 f"Y={result.keyboard_line_y}px   C4={result.c4_center_x:.1f}px   "
                 f"Ottava={result.octave_width_px:.1f}px"
        )
        self.status.configure(text="Parametri geometrici rilevati automaticamente. Puoi comunque modificarli manualmente.")
        self.progress.set(0)
        self.auto_calibrate_btn.configure(state="normal")

    def auto_calibration_failed(self, error):
        self.auto_calibrate_btn.configure(state="normal")
        self.calibration_status.configure(text="⚠ Calibrazione automatica non riuscita: usa i parametri manuali.")
        self.status.configure(text="Calibrazione automatica non riuscita.")
        messagebox.showwarning("Calibrazione automatica", error + "\n\nPuoi inserire i parametri manualmente usando gli assi X/Y.")

    def select_output(self):
        path = filedialog.asksaveasfilename(
            title="Salva MIDI",
            defaultextension=".mid",
            filetypes=[("MIDI", "*.mid")],
        )
        if path:
            self.output_path.set(path)

    def start_conversion(self):
        if not self.video_path.get():
            messagebox.showwarning("Video mancante", "Seleziona prima un video.")
            return
        if not self.output_path.get():
            messagebox.showwarning("Output mancante", "Scegli il file MIDI di destinazione.")
            return

        try:
            bpm = float(self.bpm.get())
            line_y = int(self.keyboard_line.get())
            c4_x = float(self.c4_x.get())
            octave_width = float(self.octave_width.get())
            velocity = int(self.velocity.get())
            subdivision = int(self.subdivision.get())
            strength = float(self.quantize_strength.get())
            left_hue = float(self.left_hue.get()) if self.left_hue.get().strip() else None
            right_hue = float(self.right_hue.get()) if self.right_hue.get().strip() else None
            hue_tolerance = float(self.hue_tolerance.get())
            release_tolerance = int(self.release_tolerance.get())
            min_note_duration = float(self.min_note_duration.get())
            if bpm <= 0 or line_y < 0 or c4_x < 0 or octave_width <= 0 or not (1 <= velocity <= 127) or subdivision <= 0 or not (0 <= strength <= 1) or release_tolerance < 0 or min_note_duration <= 0 or not (0 <= hue_tolerance <= 90) or (left_hue is not None and not (0 <= left_hue < 180)) or (right_hue is not None and not (0 <= right_hue < 180)):
                raise ValueError
        except ValueError:
            messagebox.showerror("Parametri non validi", "Controlla BPM, coordinate, velocity e parametri di quantizzazione.")
            return

        if self.preview.video_width:
            if line_y >= self.preview.video_height:
                messagebox.showerror("Linea Y non valida", f"Y deve essere compresa tra 0 e {self.preview.video_height - 1} px.")
                return
            if c4_x >= self.preview.video_width:
                messagebox.showerror("Centro C4 X non valido", f"X deve essere compresa tra 0 e {self.preview.video_width - 1} px.")
                return

        config = DetectorConfig(
            keyboard_line_y=line_y,
            c4_center_x=c4_x,
            octave_width_px=octave_width,
            auto_detect_colors=self.auto_detect_colors.get(),
            left_hue=left_hue,
            right_hue=right_hue,
            hue_tolerance=hue_tolerance,
        )

        self.stop_requested = False
        self.convert_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)
        self.status.configure(text="Avvio analisi...")

        thread = threading.Thread(
            target=self.worker,
            args=(config, bpm, velocity, subdivision, strength, release_tolerance, min_note_duration),
            daemon=True,
        )
        thread.start()

    def worker(self, config, bpm, velocity, subdivision, strength, release_tolerance, min_note_duration):
        config.release_tolerance_frames = release_tolerance
        config.min_note_duration = min_note_duration
        try:
            events = convert_video_to_midi(
                self.video_path.get(),
                self.output_path.get(),
                bpm=bpm,
                config=config,
                remove_initial_silence=self.remove_silence.get(),
                quantize=self.quantize.get(),
                subdivision=subdivision,
                quantize_strength=strength,
                velocity=velocity,
                progress_callback=lambda p, s: self.after(0, self.update_progress, p, s),
                stop_callback=lambda: self.stop_requested,
            )
            self.after(0, self.finished, events)
        except InterruptedError:
            self.after(0, self.cancelled)
        except Exception as exc:
            self.after(0, self.failed, str(exc))

    def update_progress(self, value, text):
        self.progress.set(value)
        self.status.configure(text=text)

    def finished(self, events):
        self.last_events = events
        self.progress.set(1)
        duration = max((e.end for e in events), default=0.0)
        self.status.configure(text="✅ Conversione completata")
        avg_duration = (sum(e.duration for e in events) / len(events)) if events else 0.0
        self.stats.configure(text=f"Note: {len(events)}\nDurata MIDI: {duration:.2f} s\nDurata media note: {avg_duration:.3f} s")
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.midi_preview.set_events(events)
        messagebox.showinfo("Completato", f"MIDI creato con successo.\n\n{self.output_path.get()}\n\nNote rilevate: {len(events)}")

    def failed(self, error):
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.status.configure(text="❌ Errore durante la conversione")
        messagebox.showerror("Errore", error)

    def cancelled(self):
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.status.configure(text="Conversione annullata")
        self.progress.set(0)

    def cancel_conversion(self):
        self.stop_requested = True
        self.status.configure(text="Annullamento in corso...")
        self.cancel_btn.configure(state="disabled")

    def on_close(self):
        self.stop_requested = True
        try:
            self.preview.close()
        finally:
            self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
