# Piano Video → MIDI

Applicazione desktop Python per convertire video con note a caduta (stile Synthesia) in file MIDI.

## 1. Installazione

Consigliato: Python 3.11 o 3.12.

```bash
python -m venv .venv
```

Windows:
```bash
.venv\\Scripts\\activate
```

macOS/Linux:
```bash
source .venv/bin/activate
```

Poi:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2. Avvio

```bash
python main.py
```

## 3. Uso

1. Seleziona il video `.mov`, `.mp4`, `.mkv` o `.avi`.
2. L'anteprima video appare nella scheda **Video & Conversione**.
3. Controlla i parametri:
   - BPM: `102` per il video di esempio.
   - Linea tastiera Y: `628`.
   - Centro C4 X: `830`.
   - Larghezza ottava: `400` px.
4. Scegli il file `.mid` di output.
5. Premi **CONVERTI IN MIDI**.
6. La barra di avanzamento mostra l'analisi.
7. Nella scheda **Anteprima MIDI** puoi visualizzare le note riconosciute.

## 4. Parametri del video di esempio

I valori predefiniti sono calibrati sul video fornito nella conversazione:

- risoluzione: 1920×1080
- piano-roll: circa Y=90..628
- linea di esecuzione/tastiera: Y≈628
- C4: X≈830
- un'ottava: ≈400 px
- BPM visualizzato: 102

Se usi un altro video con una grafica diversa, questi valori potrebbero dover essere modificati.

## 5. Funzionamento

Il programma:

1. legge il video frame per frame con OpenCV;
2. cerca le barre blu/verdi nel piano-roll;
3. individua quando la barra raggiunge la linea della tastiera;
4. usa la coordinata X per ricavare il pitch MIDI;
5. usa la permanenza della barra sulla linea per ricavare la durata;
6. opzionalmente rimuove il silenzio iniziale;
7. opzionalmente quantizza gli eventi;
8. scrive un file MIDI General MIDI con un suono di pianoforte.

## 6. Limiti attuali

Questa versione è calibrata sullo stile del video di esempio. Video con colori, prospettiva, posizione della tastiera o piano-roll differenti possono richiedere una nuova calibrazione.

La durata viene ricavata dalla grafica e non dall'audio.
