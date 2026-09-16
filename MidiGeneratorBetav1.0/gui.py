#!/usr/bin/env python3
"""GUI semplice per MidiGeneratorBetav1.0."""
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from main import build_image

class App(tk.Tk):
    """Finestra principale dell'applicazione."""
    def __init__(self):
        super().__init__()
        self.title("MidiGeneratorBetav1.0")
        self.geometry("650x420")
        self.minsize(600, 360)
        self.video = tk.StringVar()
        self.output = tk.StringVar(value="midi_image.png")
        self.line_min = tk.DoubleVar(value=0.15)
        self.line_max = tk.DoubleVar(value=0.90)
        self.threshold = tk.IntVar(value=180)
        self._build_ui()

    def _build_ui(self):
        """Costruisce i controlli della GUI."""
        root = ttk.Frame(self, padding=16); root.pack(fill="both", expand=True)
        ttk.Label(root, text="MidiGeneratorBetav1.0", font=("Arial", 18, "bold")).pack(anchor="w")
        ttk.Label(root, text="Ricostruzione immagine dalle fasce tra linee orizzontali").pack(anchor="w", pady=(0, 16))
        self._file_row(root, "Video sorgente", self.video, self._choose_video, False)
        self._file_row(root, "Immagine di output", self.output, self._choose_output, True)
        settings = ttk.LabelFrame(root, text="Parametri rilevamento", padding=10); settings.pack(fill="x", pady=12)
        self._number_row(settings, "Linea minima (0–1)", self.line_min, 0)
        self._number_row(settings, "Linea massima (0–1)", self.line_max, 1)
        self._number_row(settings, "Soglia Hough", self.threshold, 2)
        self.progress = ttk.Progressbar(root, mode="indeterminate"); self.progress.pack(fill="x", pady=(8, 4))
        self.status = ttk.Label(root, text="Seleziona un video per iniziare."); self.status.pack(anchor="w")
        buttons = ttk.Frame(root); buttons.pack(fill="x", pady=12)
        self.run_button = ttk.Button(buttons, text="Genera immagine", command=self._start); self.run_button.pack(side="left")
        ttk.Button(buttons, text="Esci", command=self.destroy).pack(side="right")
        self.log = tk.Text(root, height=6, state="disabled"); self.log.pack(fill="both", expand=True)

    def _file_row(self, parent, label, variable, command, save):
        """Aggiunge una riga con campo percorso e pulsante."""
        row = ttk.Frame(parent); row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=20).pack(side="left")
        ttk.Entry(row, textvariable=variable).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Sfoglia", command=command).pack(side="right")

    def _number_row(self, parent, label, variable, row):
        """Aggiunge un campo numerico."""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(parent, textvariable=variable, width=12).grid(row=row, column=1, sticky="w", padx=8, pady=3)

    def _choose_video(self):
        """Permette di scegliere il video sorgente."""
        path = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mov *.avi *.mkv"), ("Tutti i file", "*.*")])
        if path: self.video.set(path)

    def _choose_output(self):
        """Permette di scegliere il file immagine di destinazione."""
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png"), ("Tutti i file", "*.*")])
        if path: self.output.set(path)

    def _write_log(self, text):
        """Scrive un messaggio nell'area di log."""
        self.log.configure(state="normal"); self.log.insert("end", text + "\n"); self.log.see("end"); self.log.configure(state="disabled")

    def _start(self):
        """Valida i dati e avvia l'elaborazione in un thread."""
        if not self.video.get(): messagebox.showwarning("Video mancante", "Seleziona un video sorgente."); return
        self.run_button.configure(state="disabled"); self.progress.start(10); self.status.configure(text="Elaborazione in corso...")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        """Esegue la conversione senza bloccare la finestra."""
        try:
            lines, shape = build_image(Path(self.video.get()), Path(self.output.get()), self.line_min.get(), self.line_max.get(), line_threshold=self.threshold.get())
            self.after(0, lambda: self._done(f"Linee rilevate: {len(lines)}\nImmagine: {shape[1]}x{shape[0]}\nSalvata in: {self.output.get()}"))
        except Exception as exc:
            error_message = str(exc)
            self.after(0, lambda message=error_message: self._error(message))

    def _done(self, message):
        """Gestisce il completamento con successo."""
        self.progress.stop(); self.run_button.configure(state="normal"); self.status.configure(text="Completato."); self._write_log(message); messagebox.showinfo("Completato", message)

    def _error(self, message):
        """Gestisce gli errori dell'elaborazione."""
        self.progress.stop(); self.run_button.configure(state="normal"); self.status.configure(text="Errore."); self._write_log("Errore: " + message); messagebox.showerror("Errore", message)

if __name__ == "__main__":
    App().mainloop()
