# Midi Generator v2.4

Applicazione Python con GUI CustomTkinter per convertire video di pianoforti digitali con note a caduta in file MIDI.

## Novità della versione 2.4

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
- Rilevamento della durata delle note tramite tracking temporale frame-by-frame.
- Tolleranza configurabile per piccoli buchi di rilevamento.
- Filtro configurabile della durata minima delle note.
- Progress bar suddivisa tra calibrazione, analisi video e generazione MIDI.
- Pannello parametri scrollabile per finestre di dimensioni ridotte.
- Statistiche su durata totale e durata media delle note.

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


## Rilevamento della durata delle note

La durata viene stimata osservando per quanti frame una nota resta presente nella zona di attivazione vicino alla tastiera:

- il primo frame stabile diventa l'inizio della nota;
- la nota viene considerata ancora attiva finché viene rilevata;
- il rilascio viene confermato dopo un numero configurabile di frame mancanti;
- in questo modo piccoli difetti di compressione non spezzano una nota lunga;
- gli intervalli frammentati dello stesso pitch vengono uniti quando la pausa è molto breve.

I parametri disponibili nella GUI sono `Tolleranza rilascio (frame)` e `Durata minima (s)`. La durata viene salvata nel MIDI attraverso la distanza tra gli eventi `note_on` e `note_off`.


### v2.4
- Nome applicazione: **Midi Generator v2.4**.
- Riconoscimento separato delle note blu (mano sinistra) e verdi (mano destra).
- Esportazione MIDI su canali distinti: canale 1 per la mano sinistra, canale 2 per la mano destra.
- Tracciamento della persistenza delle note per stimare in modo più fedele inizio e fine della durata.


### Correzione 2.4: note ripetute

La fusione automatica di eventi vicini è stata disattivata: note consecutive
della stessa altezza non vengono più accorpate in una singola nota lunga.
La durata viene determinata dal tracciamento per fotogrammi e dalla tolleranza
di rilascio.


## Colori generici (v2.4)

Il rilevatore non è più vincolato a blu e verde: campiona vari fotogrammi, individua due tonalità HSV dominanti e assegna automaticamente la tonalità con posizione media più a sinistra alla mano sinistra e l'altra alla mano destra.

È possibile disattivare il rilevamento automatico e inserire manualmente i valori Hue OpenCV (0-179) nella GUI. Le istruzioni principali del codice contengono commenti brevi per chiarire il ruolo delle operazioni.


### Correzione separazione note
La rilevazione usa ora attacco, continuità e rilascio espliciti: la fascia di continuità vicino alla tastiera è stata rimossa per evitare di fondere barre separate. La tolleranza predefinita è 0 frame; può essere aumentata manualmente se il video presenta piccoli buchi di rilevamento.
