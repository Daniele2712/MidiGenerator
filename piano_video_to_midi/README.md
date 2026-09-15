# Piano video → MIDI

Converts a Synthesia-style falling-note video into a `.mid` file.

## Install

```bash
python -m pip install -r requirements.txt
```

## Run

For the supplied example:

```bash
python main.py clip_ex.mov output.mid --bpm 102
```

The program automatically searches for the red strike line.

## If the video layout changes

The important calibration parameters are:

- `--c2-x`: X coordinate of C2 in the piano roll
- `--octave-width`: pixel distance from one C grid line to the next
- `--c2-midi`: MIDI number of C2 (normally 36)
- `--hit-y`: Y coordinate of the red strike line

Example:

```bash
python main.py video.mov output.mid \
    --c2-x 0 \
    --octave-width 400 \
    --c2-midi 36 \
    --bpm 102
```

## Timing

The note times come from the actual video frame timestamps. `--bpm` tells the MIDI file which musical tempo to use.

If you want to force notes onto a musical grid:

```bash
--quantize 0.25
```

This is useful for 1/16-note quantization at the chosen BPM.

## Important limitation

This is a computer-vision prototype. It works best when the piano roll has a fixed horizontal mapping and colored falling notes. Videos with camera movement, unusual note effects, changing zoom, or a different visual theme may need additional calibration/detection rules.
