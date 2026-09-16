# MidiGeneratorBetav1.0

Prototipo che rileva linee orizzontali nel video, estrae le fasce tra linee consecutive e le concatena in un'unica immagine verticale.

## macOS

1. Estrai lo ZIP.
2. Fai doppio clic su `run_macos.command` (oppure esegui `chmod +x run_macos.command`).
3. Lo script crea `.venv`, installa automaticamente i requirements e avvia la GUI.

## Avvio da terminale

```bash
python3 main.py "video.mp4" -o midi_image.png
```

La GUI permette di selezionare video/output e modificare i parametri del rilevamento Hough.
