#!/bin/bash

# Piano Video -> MIDI 2.2 - avvio macOS
# Può essere eseguito dal Terminale oppure con doppio clic nel Finder.

set -u

cd "$(dirname "$0")" || exit 1

echo "=========================================="
echo "   Piano Video -> MIDI 2.2 - macOS"
echo "=========================================="
echo

# Cerca Python 3
if command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "ERRORE: Python 3 non è installato."
    echo
    echo "Installa Python 3 e riprova."
    echo "Consigliato: Python 3.11 o 3.12."
    echo
    read -r -p "Premi INVIO per chiudere..."
    exit 1
fi

# Mostra versione
PY_VERSION=$($PYTHON --version 2>&1)
echo "Python rilevato: $PY_VERSION"

# Controlla Tkinter, necessario per CustomTkinter
if ! $PYTHON -c "import tkinter" >/dev/null 2>&1; then
    echo
    echo "ERRORE: Tkinter non è disponibile in questa installazione di Python."
    echo
    echo "Installa Python dal sito ufficiale python.org, che include Tkinter."
    echo "Poi esegui nuovamente questo script."
    echo
    read -r -p "Premi INVIO per chiudere..."
    exit 1
fi

# Crea ambiente virtuale se non esiste
if [ ! -d ".venv" ]; then
    echo
    echo "Creo l'ambiente virtuale .venv..."
    $PYTHON -m venv .venv
    if [ $? -ne 0 ]; then
        echo "ERRORE: impossibile creare l'ambiente virtuale."
        read -r -p "Premi INVIO per chiudere..."
        exit 1
    fi
fi

PYTHON_VENV="$(pwd)/.venv/bin/python"
PIP_VENV="$(pwd)/.venv/bin/pip"

# Aggiorna pip e installa/aggiorna le dipendenze
echo
echo "Controllo le dipendenze..."
$PYTHON_VENV -m pip install --upgrade pip
if [ $? -ne 0 ]; then
    echo "ERRORE durante l'aggiornamento di pip."
    read -r -p "Premi INVIO per chiudere..."
    exit 1
fi

$PYTHON_VENV -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo
    echo "ERRORE durante l'installazione delle dipendenze."
    read -r -p "Premi INVIO per chiudere..."
    exit 1
fi

echo
echo "Avvio Piano Video -> MIDI 2.2..."
echo

# Avvia la GUI
$PYTHON_VENV main.py
STATUS=$?

echo
if [ $STATUS -ne 0 ]; then
    echo "Il programma è terminato con errore (codice $STATUS)."
else
    echo "Programma terminato."
fi

echo
read -r -p "Premi INVIO per chiudere il Terminale..."
exit $STATUS
