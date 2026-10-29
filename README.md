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

## How it runs
- **Automatically** twice a day: this repo's GitHub Action runs the forecast (≈03:15 / 15:15 Israel winter time, ≈04:15 / 16:15 summer time) and publishes `data/forecast.json`; Cloudflare updates the site within a minute.
- **Now:** GitHub (web or mobile app) → this repo → **Actions** → **Run forecast now** → **Run workflow**.
- The claude.ai task (≈04:48 / 16:48) reads the latest site data, refreshes the private dashboard and sends the phone notification when windows change or this config has a problem.

## Files
- `index.html` — the public page (static, no build step)
- `data/forecast.json` — written by the GitHub Action on every run
- `config/spots.json` — your criteria (kept off the website)
- `engine/` — the forecast engine (`spots.json` there is the fallback if `config/spots.json` has an error)
- `.github/workflows/run-forecast.yml` — scheduled + manual forecast runs
- `.assetsignore` — keeps `config/`, `engine/`, `.github/` and Markdown files off the website
- `_headers` — no-cache for the data file

Forecast data © Open-Meteo, CC BY 4.0. Model output, not a safety guarantee.
