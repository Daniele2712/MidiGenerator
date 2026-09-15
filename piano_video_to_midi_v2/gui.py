from __future__ import annotations

import os
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import cv2
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw, ImageFont

from video_to_midi import DetectorConfig, NoteEvent, convert_video_to_midi


class VideoPreview(ctk.CTkFrame):
    def __init__(self, master, on_time_changed=None):
        super().__init__(master, fg_color="transparent")
        self.on_time_changed = on_time_changed
        self.cap = None
        self.path = None
        self.fps = 30.0
        self.frame_count = 0
        self.duration = 0.0
        self.current_frame = 0
        self.playing = False
        self.photo = None
        self._after_id = None

        self.image_label = ctk.CTkLabel(self, text="Seleziona un video", width=820, height=430)
        self.image_label.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        controls = ctk.CTkFrame(self)
        controls.pack(fill="x", padx=8, pady=4)

        self.play_btn = ctk.CTkButton(controls, text="▶ Riproduci", width=110, command=self.toggle_play)
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
        self.duration = self.frame_count / self.fps if self.fps else 0.0
        self.slider.configure(to=max(self.duration, 0.01))
        self.show_frame(0)

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
        image = Image.fromarray(rgb)
        image.thumbnail((900, 480), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image)
        self.image_label.configure(image=self.photo, text="")
        current_time = self.current_frame / self.fps
        self.slider.set(current_time)
        self.time_label.configure(text=f"{format_time(current_time)} / {format_time(self.duration)}")
        if self.on_time_changed:
            self.on_time_changed(current_time)

    def seek(self, value):
        if self.cap and not self.playing:
            self.show_frame(int(float(value) * self.fps))

    def toggle_play(self):
        if not self.cap:
            return
        self.playing = not self.playing
        self.play_btn.configure(text="⏸ Pausa" if self.playing else "▶ Riproduci")
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

    def close(self):
        self.playing = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self.cap:
            self.cap.release()
            self.cap = None


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class MidiPreview(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        self.events: list[NoteEvent] = []
        self.canvas = tk.Canvas(self, bg="#171717", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=8)
        self.info = ctk.CTkLabel(self, text="Converti un video per vedere l'anteprima MIDI")
        self.info.pack(pady=(0, 8))
        self.bind("<Configure>", lambda e: self.draw())

    def set_events(self, events: list[NoteEvent]):
        self.events = events
        self.info.configure(text=f"Note rilevate: {len(events)}")
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        if not self.events:
            self.canvas.create_text(350, 180, text="Nessuna nota", fill="white", font=("Arial", 16))
            return

        width = max(400, self.canvas.winfo_width())
        height = max(250, self.canvas.winfo_height())
        min_pitch = min(e.pitch for e in self.events)
        max_pitch = max(e.pitch for e in self.events)
        max_time = max(e.end for e in self.events) or 1.0

        left = 55
        top = 15
        right = 15
        bottom = 30
        plot_w = width - left - right
        plot_h = height - top - bottom
        pitch_span = max(1, max_pitch - min_pitch + 1)
        row_h = max(5, plot_h / pitch_span)

        # Grid and pitch labels.
        for i, pitch in enumerate(range(min_pitch, max_pitch + 1)):
            y = top + (max_pitch - pitch) * row_h
            if pitch % 12 in (0, 5):
                self.canvas.create_line(left, y, width - right, y, fill="#333333")
            if pitch % 12 == 0:
                self.canvas.create_text(5, y + row_h / 2, anchor="w", text=midi_name(pitch), fill="#aaaaaa", font=("Arial", 8))

        # Time grid every second.
        sec = 0
        while sec <= max_time:
            x = left + (sec / max_time) * plot_w
            self.canvas.create_line(x, top, x, height - bottom, fill="#292929")
            self.canvas.create_text(x + 2, height - 15, anchor="w", text=f"{sec}s", fill="#aaaaaa", font=("Arial", 8))
            sec += max(1, int(max_time / 10))

        for event in self.events:
            x1 = left + event.start / max_time * plot_w
            x2 = left + event.end / max_time * plot_w
            y1 = top + (max_pitch - event.pitch) * row_h + 1
            y2 = y1 + max(3, row_h - 2)
            self.canvas.create_rectangle(x1, y1, max(x1 + 2, x2), y2, fill="#4da3ff", outline="")


def midi_name(pitch: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Piano Video → MIDI")
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
        self.stop_requested = False
        self.last_events: list[NoteEvent] = []

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build_ui()

    def build_ui(self):
        header = ctk.CTkFrame(self, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(header, text="🎹  Piano Video → MIDI", font=("Arial", 28, "bold")).pack(side="left", padx=25, pady=18)
        ctk.CTkLabel(header, text="Falling Notes Converter", font=("Arial", 13)).pack(side="left", padx=5, pady=18)

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=18, pady=18)
        video_tab = tabs.add("Video & Conversione")
        midi_tab = tabs.add("Anteprima MIDI")

        # Left settings / right preview.
        settings = ctk.CTkFrame(video_tab, width=350)
        settings.pack(side="left", fill="y", padx=(10, 8), pady=10)
        settings.pack_propagate(False)
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
        self.add_entry(settings, "Velocity", self.velocity)

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
            self.status.configure(text="Video caricato. Pronto per la conversione.")
        except Exception as exc:
            messagebox.showerror("Errore video", str(exc))

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
            if bpm <= 0 or not (1 <= velocity <= 127) or subdivision <= 0 or not (0 <= strength <= 1):
                raise ValueError
        except ValueError:
            messagebox.showerror("Parametri non validi", "Controlla BPM, coordinate, velocity e parametri di quantizzazione.")
            return

        config = DetectorConfig(
            keyboard_line_y=line_y,
            c4_center_x=c4_x,
            octave_width_px=octave_width,
        )

        self.stop_requested = False
        self.convert_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)
        self.status.configure(text="Avvio analisi...")

        thread = threading.Thread(
            target=self.worker,
            args=(config, bpm, velocity, subdivision, strength),
            daemon=True,
        )
        thread.start()

    def worker(self, config, bpm, velocity, subdivision, strength):
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
        self.stats.configure(text=f"Note: {len(events)}\nDurata MIDI: {duration:.2f} s")
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
