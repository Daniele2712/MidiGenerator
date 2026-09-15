# Piano Video → MIDI 2.2

Applicazione Python con GUI CustomTkinter per convertire video di pianoforti digitali con note a caduta in file MIDI.

## Novità della versione 2.2

- **Calibrazione automatica** dei parametri geometrici del video.
- Rilevamento automatico della linea della tastiera tramite la linea rossa di separazione.
- Rilevamento automatico della geometria della tastiera tramite il pattern dei tasti neri.
- Stima automatica di `Centro C4 X` e `Larghezza ottava (px)`.
- Indicazione della confidenza della calibrazione.
- Linee di calibrazione sovrapposte all'anteprima per verificare visivamente i risultati.
- Pulsante per ripetere manualmente la calibrazione automatica.
- Restano disponibili i parametri manuali per eventuali correzioni.
- Assi X/Y attorno all'anteprima con coordinate in pixel del video originale.
- Supporto `.mov`, `.mp4`, `.mkv`, `.avi`.

## Come funziona la calibrazione automatica

Quando carichi un video, il programma analizza diversi fotogrammi e cerca:

1. la linea rossa sopra la tastiera;
2. i tasti neri nella zona della tastiera;
3. il pattern ripetitivo dei tasti neri (`C# D# F# G# A#`);
4. la distanza tra i tasti per stimare un'ottava;
5. la posizione del C4 rispetto alla tastiera visibile.

Per il video di esempio utilizzato nello sviluppo, la calibrazione rileva automaticamente valori nell'ordine di:

```text
Limite note / tastiera Y ≈ 720 px
C4 X                  ≈ 950.5 px
Larghezza ottava      ≈ 462 px
```

Questi numeri sono solo un esempio: **non vengono più hardcodati**, perché vengono ricalcolati per ogni video.

> Il BPM non viene ricavato dalla geometria della tastiera. Rimane un parametro musicale separato; può essere impostato manualmente.

## Installazione

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Avvio

```bash
python main.py
```

Su macOS puoi usare anche:

```bash
chmod +x avvia_macos.command
./avvia_macos.command
```

Su Windows è disponibile `run_windows.bat`.

## Uso

1. Avvia la GUI.
2. Seleziona il video.
3. La calibrazione automatica parte subito.
4. Controlla le linee colorate sull'anteprima e i valori nei campi.
5. Se necessario, premi **CALIBRA PARAMETRI AUTOMATICAMENTE** per ripetere l'analisi.
6. Puoi correggere manualmente i valori usando gli assi X/Y.
7. Scegli il file MIDI di output e premi **CONVERTI IN MIDI**.

## Nota tecnica

La calibrazione automatica è pensata per video con una tastiera orizzontale e un piano-roll simile a quello del video di esempio. Se un video ha una grafica completamente diversa, la GUI mantiene comunque la possibilità di inserire manualmente i parametri.
