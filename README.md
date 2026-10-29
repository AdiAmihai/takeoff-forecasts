# Takeoff Forecasts

Paragliding wind windows for Israeli takeoffs, 7 days ahead, blended from six forecast models (GFS, ICON, ECMWF IFS, ARPEGE, UKMO, GEM) via Open-Meteo.
Live site: https://takeoff-forecasts.adi-test1.workers.dev/

## Edit your takeoffs — `config/spots.json`
Open `config/spots.json` here on GitHub → pencil icon → edit → **Commit changes**. The next scheduled run (≈04:48 / ≈16:48 Israel time) uses it. This file is **not** served by the website.

Each spot is one line:
```json
{"id": "beit-jean", "name": "Beit Jean (7winds Har Haari)", "lat": 32.635675, "lon": 35.402343, "hours": [9, 16], "dir": [140, 200], "speed": [5, 20], "min_hours": 2}
```

| Field | Meaning |
|---|---|
| `id` | Fixed internal key — **don't change it** (it keeps the spot's history). New spot → new unique id: lowercase letters, digits, dashes. |
| `name` | Display name — rename freely. |
| `lat`, `lon` | Takeoff location. |
| `hours` | `[start, end]` local time, whole hours: `[9, 16]` = 09:00–16:00. |
| `dir` | `[from, to]` wind direction (where it blows **from**), read clockwise. `[230, 133]` wraps through north. |
| `speed` | `[min, max]` km/h (blended model average). |
| `min_hours` | Minimum consecutive hours for a window. |
| `max_cloud` | Optional: max total cloud % per hour. Without it the spot uses `defaults.max_cloud` (75). |

Separate spots with commas; no comma after the last one.

**If you make a mistake** (missing comma, min > max…), the run keeps using the last good criteria and your notification says what to fix, e.g. `spot #3 (Tavor take off): "speed" must be [min, max] km/h with min ≤ max`.

## Run it now
GitHub (web or mobile app) → this repo → **Actions** → **Run forecast now** → **Run workflow**. About 1–2 minutes later the site shows the new forecast. This updates the website only; the claude.ai dashboard and phone notification update on the next scheduled run (or ask Claude "run now" for a full run).

## Files
- `index.html` — the public page (static, no build step)
- `data/forecast.json` — refreshed by every scheduled run
- `config/spots.json` — your criteria (kept off the website)
- `engine/` — forecast engine used by the manual run (`spots.json` there is the fallback criteria)
- `.github/workflows/run-forecast.yml` — the manual run button
- `.assetsignore` — keeps `config/`, `engine/`, `.github/` and Markdown files off the website
- `_headers` — no-cache for the data file

Forecast data © Open-Meteo, CC BY 4.0. Model output, not a safety guarantee.
