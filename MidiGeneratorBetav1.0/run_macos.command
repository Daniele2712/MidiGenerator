#!/bin/bash
# Entra nella cartella del progetto.
cd "$(dirname "$0")"
# Crea un ambiente virtuale isolato se non esiste.
if [ ! -d ".venv" ]; then python3 -m venv .venv || exit 1; fi
# Attiva l'ambiente virtuale.
source .venv/bin/activate
# Aggiorna pip e installa le dipendenze.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || exit 1
# Avvia la GUI.
python gui.py
