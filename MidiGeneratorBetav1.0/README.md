# MidiGeneratorBetav1.0

Prototipo sperimentale che crea una singola immagine verticale, simile a un "midi immagine", concatenando le fasce del video comprese tra linee orizzontali consecutive.

## Installazione

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Utilizzo

```bash
python main.py "video.mp4" -o midi_image.png
```

Parametri utili:

```bash
python main.py "video.mp4" -o midi_image.png --line-min 0.15 --line-max 0.90 --threshold 180
```

## Funzionamento

1. Campiona alcuni fotogrammi del video e sceglie quello con maggiore presenza di colori saturi.
2. Rileva le linee orizzontali con la trasformata di Hough.
3. Estrae le fasce comprese tra linee consecutive.
4. Incolla le fasce in un'unica immagine verticale, invertendo l'ordine per avere il riferimento iniziale in basso.

È un prototipo: se le linee non vengono rilevate correttamente, occorre regolare i parametri o introdurre un rilevamento guidato manualmente.
