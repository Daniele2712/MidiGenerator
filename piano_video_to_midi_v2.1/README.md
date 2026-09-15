# Piano Video → MIDI 2.1

Applicazione Python con GUI CustomTkinter per convertire video di pianoforti digitali con note a caduta in file MIDI.

## Novità della versione 2.1

- Assi X e Y attorno all'anteprima video.
- Coordinate espresse nei **pixel del video originale**, anche quando il video viene ridimensionato nella GUI.
- Coordinate X/Y del mouse visualizzate in tempo reale.
- Reticolo/crosshair giallo per individuare con precisione un punto del video.
- Risoluzione del video mostrata sotto l'anteprima.
- Controlli per `Linea tastiera Y` e `Centro C4 X` con validazione rispetto alla risoluzione del video.
- Supporto video `.mov`, `.mp4`, `.mkv`, `.avi`.

## Installazione

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Poi:

```bash
pip install -r requirements.txt
```

## Avvio

```bash
python main.py
```

Su Windows è disponibile anche `run_windows.bat`.

## Uso degli assi

1. Seleziona il video.
2. Gli assi vengono calibrati automaticamente sulla risoluzione originale.
3. Muovi il mouse sull'immagine: sotto l'anteprima compariranno `X` e `Y` in pixel.
4. Usa le coordinate per impostare, ad esempio, `Linea tastiera Y` e `Centro C4 X`.
5. I valori degli assi **non dipendono dalla dimensione con cui il video viene mostrato nella GUI**.

Per esempio, per un video 1920×1080 potrai leggere valori come `X 830 px, Y 628 px` direttamente sull'anteprima.
