@echo off
cd /d "%~dp0"
python -m pip install pyinstaller
pyinstaller --noconfirm --clean --windowed --name PianoVideoToMIDI main.py
pause
