# Takeoff Forecasts

Public page of paragliding wind windows for Israeli takeoffs, 7 days ahead, blended from six forecast models (GFS, ICON, ECMWF IFS, ARPEGE, UKMO, GEM) via Open-Meteo.

- `index.html` — the page (static, no build step)
- `data/forecast.json` — refreshed by the Forecast Alerts scheduled runs (~05:00 and ~17:00 Israel time)

Cloudflare Pages: connect this repo, no build command, output directory `/`.

Forecast data © Open-Meteo, CC BY 4.0. Model output, not a safety guarantee.
