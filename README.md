# Drift Wood Map Generator

A detailed procedural hex map generator for Drift Wood / Hex War Arc.

The app has a browser control panel and a small Python server that renders generated maps as PNG images with Pillow.

## Features

- board size presets and custom tile dimensions
- terrain count controls for water, sand, plains, forest, stone, and mountains
- river placement modes
- planet themes and custom color palettes
- relief, height, scale, and offset controls
- optional villages, reefs, forest details, boar, frozen water, and mountain erosion
- generated PNG output

## Run Locally

```bash
python3 -m pip install -r requirements.txt
python3 server.py
```

Then open `http://127.0.0.1:8000`.

On macOS, you can also run `./run.command`.

## Project Files

- `index.html` is the UI shell.
- `style.css` contains the app styling.
- `app.js` controls the browser UI and sends generation settings.
- `server.py` serves the app and renders generated maps.
- `*.png` files are sample generated maps.
- `Conquer_The_Hexagonal_*.pdf` files are included design/rulebook references.
