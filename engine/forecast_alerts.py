#!/usr/bin/env python3
"""Forecast Alerts — twice-daily paragliding wind windows from Open-Meteo.

Usage:
  python3 forecast_alerts.py [--spots spots.json] [--prev prev.json] [--out result.json]

Reads the previous run (prev.json, optional), fetches 7 days of hourly wind for
six models per spot, builds a blended ("WG-like") forecast with model spread,
finds flyable windows per spot and compares them to the previous run.
Writes the full result to --out and prints a short summary (and the
notification text when anything changed) to stdout.
"""
import argparse, json, math, statistics, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pathlib import Path
try:
    VERSION = (Path(__file__).resolve().parent / "VERSION").read_text().strip()
except OSError:
    VERSION = "unknown"
TZ = ZoneInfo("Asia/Jerusalem")
MODELS = {
    "gfs_seamless": "GFS", "icon_seamless": "ICON", "ecmwf_ifs025": "ECMWF IFS",
    "arpege_seamless": "ARPEGE", "ukmo_seamless": "UKMO", "gem_seamless": "GEM",
}
GUST_FLAG_KMH = 10      # gust - speed above this -> ⚠️
SHIFT_HOURS = 1         # start/end moved >= this -> shifted
SHIFT_SPEED_KMH = 3     # avg speed changed > this -> shifted
MIN_MODELS = 2          # hours with fewer models available are skipped
DEFAULT_MAX_CLOUD = 75  # % total cloud cover; hours above a spot's max break a window
API = "https://api.open-meteo.com/v1/forecast"


def fetch(spot, retries=4):
    q = {
        "latitude": spot["lat"], "longitude": spot["lon"],
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,cloud_cover",
        "models": ",".join(MODELS), "wind_speed_unit": "kmh",
        "timezone": "Asia/Jerusalem", "forecast_days": 7,
    }
    url = API + "?" + urllib.parse.urlencode(q)
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                return json.load(r)["hourly"]
        except Exception as e:  # network hiccup -> retry
            err = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Open-Meteo failed for {spot['name']}: {err}")


def circ_mean(degs):
    s = sum(math.sin(math.radians(d)) for d in degs)
    c = sum(math.cos(math.radians(d)) for d in degs)
    return (math.degrees(math.atan2(s, c)) + 360) % 360


def circ_std(degs):
    """Circular standard deviation in degrees."""
    n = len(degs)
    s = sum(math.sin(math.radians(d)) for d in degs) / n
    c = sum(math.cos(math.radians(d)) for d in degs) / n
    r = min(1.0, math.hypot(s, c))
    return math.degrees(math.sqrt(-2 * math.log(r))) if r > 1e-9 else 180.0


def dir_in(d, lo, hi):
    """Clockwise range lo->hi, wrapping through north when lo > hi."""
    return lo <= d <= hi if lo <= hi else (d >= lo or d <= hi)


def blend(hourly):
    rows = []
    for i, t in enumerate(hourly["time"]):
        sp, dr, gu, cl, used = [], [], [], [], []
        for m, label in MODELS.items():
            s = hourly.get(f"wind_speed_10m_{m}", [None])[i]
            d = hourly.get(f"wind_direction_10m_{m}", [None])[i]
            g = hourly.get(f"wind_gusts_10m_{m}", [None])[i]
            if s is None or d is None:
                continue
            sp.append(s); dr.append(d); used.append(label)
            if g is not None:
                gu.append(g)
            c = hourly.get(f"cloud_cover_{m}", [None])[i]
            if c is not None:
                cl.append(c)
        if len(sp) < MIN_MODELS:
            rows.append({"time": t, "ok": False})
            continue
        speed = statistics.fmean(sp)
        gust = statistics.fmean(gu) if gu else speed
        rows.append({
            "time": t, "ok": True,
            "speed": round(speed, 1), "gust": round(gust, 1),
            "dir": round(circ_mean(dr)),
            "spread_speed": round(statistics.pstdev(sp), 1),
            "spread_dir": round(circ_std(dr)),
            "models": len(sp),
            "cloud": round(statistics.fmean(cl)) if cl else None,
            "spread_cloud": round(statistics.pstdev(cl)) if len(cl) > 1 else None,
            "gust_flag": (gust - speed) > GUST_FLAG_KMH,
        })
    return rows


def find_windows(spot, rows):
    h0, h1 = spot["hours"]
    lo, hi = spot["dir"]
    smin, smax = spot["speed"]
    cmax = spot.get("max_cloud", DEFAULT_MAX_CLOUD)
    good = []
    for r in rows:
        dt = datetime.fromisoformat(r["time"])
        r["_dt"] = dt
        r["match"] = bool(r["ok"] and h0 <= dt.hour < h1
                          and dir_in(r["dir"], lo, hi) and smin <= r["speed"] <= smax
                          and (r.get("cloud") is None or r["cloud"] <= cmax))
    windows, run = [], []
    for r in rows + [{"match": False, "_dt": None}]:
        if r["match"] and (not run or r["_dt"] - run[-1]["_dt"] == timedelta(hours=1)):
            run.append(r); continue
        if len(run) >= spot["min_hours"]:
            windows.append(make_window(run))
        run = [r] if r["match"] else []
    return windows


def make_window(run):
    start, last = run[0]["_dt"], run[-1]["_dt"]
    end = last + timedelta(hours=1)
    return {
        "date": start.strftime("%Y-%m-%d"),
        "start": start.strftime("%Y-%m-%dT%H:%M"),
        "end": end.strftime("%Y-%m-%dT%H:%M"),
        "hours": len(run),
        "avg_speed": round(statistics.fmean(r["speed"] for r in run), 1),
        "max_gust": round(max(r["gust"] for r in run), 1),
        "avg_dir": round(circ_mean([r["dir"] for r in run])),
        "spread_speed": round(statistics.fmean(r["spread_speed"] for r in run), 1),
        "spread_dir": round(statistics.fmean(r["spread_dir"] for r in run)),
        "avg_cloud": _avg([r.get("cloud") for r in run]),
        "spread_cloud": _avg([r.get("spread_cloud") for r in run]),
        "gust_flag_hours": [r["_dt"].strftime("%H:%M") for r in run if r["gust_flag"]],
        "detail": [{k: r.get(k) for k in ("time", "speed", "gust", "dir", "spread_speed",
                                      "spread_dir", "cloud", "spread_cloud", "models", "gust_flag")} for r in run],
    }


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs)) if xs else None


def _dt(s):
    return datetime.fromisoformat(s)


def diff(prev_windows, cur_windows, now):
    """Return list of change dicts for one spot."""
    changes = []
    prev = [w for w in prev_windows if _dt(w["end"]) > now]  # ignore windows already past
    used = set()
    for c in cur_windows:
        match = None
        for j, p in enumerate(prev):
            if j in used:
                continue
            if _dt(p["start"]) < _dt(c["end"]) and _dt(c["start"]) < _dt(p["end"]):
                match = j; break
        if match is None:
            changes.append({"type": "new", "window": c}); continue
        used.add(match)
        p = prev[match]
        ds = abs((_dt(c["start"]) - _dt(p["start"])).total_seconds()) / 3600
        de = abs((_dt(c["end"]) - _dt(p["end"])).total_seconds()) / 3600
        dv = abs(c["avg_speed"] - p["avg_speed"])
        if ds >= SHIFT_HOURS or de >= SHIFT_HOURS or dv > SHIFT_SPEED_KMH:
            changes.append({"type": "shifted", "window": c, "was": p})
    for j, p in enumerate(prev):
        if j not in used:
            changes.append({"type": "removed", "window": p})
    changes.sort(key=lambda x: x["window"]["start"])
    return changes


def fmt_w(w):
    s, e = _dt(w["start"]), _dt(w["end"])
    g = " ⚠️" if (w.get("gust_flag_hours") or w.get("gusty")) else ""
    cloud = f" ☁{w['avg_cloud']}%" if w.get("avg_cloud") not in (None, "") else ""
    return (f"{s.strftime('%a %d/%m')} {s.strftime('%H:%M')}–{e.strftime('%H:%M')} "
            f"{w['avg_speed']:.0f} km/h {w['avg_dir']}° (±{w['spread_speed']:.0f}){cloud}{g}")


def notification(results):
    lines = []
    for sp in results["spots"]:
        if not sp["changes"]:
            continue
        lines.append(f"• {sp['name']}")
        for ch in sp["changes"]:
            w = ch["window"]
            if ch["type"] == "new":
                lines.append(f"  + {fmt_w(w)}")
            elif ch["type"] == "removed":
                lines.append(f"  − {fmt_w(w)} (gone)")
            else:
                lines.append(f"  ~ {fmt_w(w)} (was {_dt(ch['was']['start']).strftime('%H:%M')}–"
                             f"{_dt(ch['was']['end']).strftime('%H:%M')} {ch['was']['avg_speed']:.0f} km/h)")
    return "\n".join(lines)


def _row(spot, w, spot_id=""):
    return {"spot": spot, "spot_id": spot_id, "date": w["date"], "start": w["start"], "end": w["end"],
            "hours": w["hours"], "avg_speed": w["avg_speed"], "max_gust": w["max_gust"],
            "avg_dir": w["avg_dir"], "spread_speed": w["spread_speed"],
            "spread_dir": w["spread_dir"], "avg_cloud": w.get("avg_cloud"),
            "spread_cloud": w.get("spread_cloud"), "gusty": bool(w["gust_flag_hours"]),
            "gust_hours": ", ".join(w["gust_flag_hours"])}


WINDOW_COLS = ["spot", "spot_id", "date", "start", "end", "hours", "avg_speed", "max_gust", "avg_dir",
               "spread_speed", "spread_dir", "avg_cloud", "spread_cloud", "gusty", "gust_hours"]
CHANGE_COLS = ["spot", "spot_id", "change", "start", "end", "avg_speed", "was_start", "was_end", "was_speed"]


def export(out, prev_rows, d):
    """Flat row files for the dashboard. windows.json is also next run's --prev."""
    d.mkdir(parents=True, exist_ok=True)
    windows = [_row(s["name"], w, s["id"]) for s in out["spots"] for w in s["windows"]]
    changes = []
    for s in out["spots"]:
        for ch in s["changes"]:
            w, p = ch["window"], ch.get("was") or {}
            changes.append({"spot": s["name"], "spot_id": s["id"], "change": ch["type"], "start": w["start"],
                            "end": w["end"], "avg_speed": w["avg_speed"],
                            "was_start": p.get("start", ""), "was_end": p.get("end", ""),
                            "was_speed": p.get("avg_speed", "")})
    spots = [{"spot": s["name"], "spot_id": s["id"], "hours": f"{s['hours'][0]:02d}–{s['hours'][1]:02d}",
              "dir": f"{s['dir'][0]}→{s['dir'][1]}", "speed": f"{s['speed'][0]}–{s['speed'][1]}",
              "min_hours": s["min_hours"], "max_cloud": s["max_cloud"], "windows": len(s["windows"])} for s in out["spots"]]
    run = [{"run_at": out["run_at"], "version": out["version"], "first_run": out["first_run"],
            "windows": len(windows), "changes": len(changes),
            "spots_with_windows": sum(1 for s in out["spots"] if s["windows"]),
            "models": ", ".join(out["models"]), "notification": out["notification"],
            "config_source": out["config_source"], "config_commit": out["config_commit"],
            "config_error": out["config_error"]}]
    prev = [{k: r.get(k, "") for k in WINDOW_COLS} for r in prev_rows]
    for name, rows in (("run", run), ("windows", windows), ("spots", spots)):
        (d / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    # CSV (header always present) so an empty list still reads as a table on the dashboard
    import csv
    for name, rows, cols in (("changes", changes, CHANGE_COLS), ("previous", prev, WINDOW_COLS)):
        with open(d / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader(); w.writerows(rows)
    # One bundle for the public site (takeoff-forecasts repo, data/forecast.json)
    (d / "forecast.json").write_text(json.dumps(
        {"run": run[0], "windows": windows, "changes": changes, "spots": spots, "previous": prev},
        ensure_ascii=False, indent=1))


ID_OK = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_config(cfg):
    """Return a list of plain-language problems; empty means the criteria are usable."""
    errs = []
    if not isinstance(cfg, dict) or not isinstance(cfg.get("spots"), list) or not cfg["spots"]:
        return ['needs a "spots" list with at least one spot']
    dflt = cfg.get("defaults", {})
    if not isinstance(dflt, dict):
        errs.append('"defaults" must be an object')
        dflt = {}
    if "max_cloud" in dflt and not (_num(dflt["max_cloud"]) and 0 <= dflt["max_cloud"] <= 100):
        errs.append("defaults.max_cloud must be a number 0–100")
    ids, names = set(), set()
    for i, sp in enumerate(cfg["spots"], 1):
        if not isinstance(sp, dict):
            errs.append(f"spot #{i} is not an object"); continue
        who = f'spot #{i} ({sp.get("name", "no name")})'
        sid = sp.get("id")
        if not isinstance(sid, str) or not sid or not set(sid) <= ID_OK:
            errs.append(f'{who}: "id" must be lowercase letters, digits and dashes')
        elif sid in ids:
            errs.append(f'{who}: id "{sid}" is used twice')
        else:
            ids.add(sid)
        nm = sp.get("name")
        if not isinstance(nm, str) or not nm.strip():
            errs.append(f'{who}: "name" is missing')
        elif nm in names:
            errs.append(f'{who}: name is used twice')
        else:
            names.add(nm)
        if not (_num(sp.get("lat")) and -90 <= sp["lat"] <= 90):
            errs.append(f'{who}: "lat" must be a number -90…90')
        if not (_num(sp.get("lon")) and -180 <= sp["lon"] <= 180):
            errs.append(f'{who}: "lon" must be a number -180…180')
        def pair(key):
            v = sp.get(key)
            return v if isinstance(v, list) and len(v) == 2 and all(_num(x) for x in v) else None
        h = pair("hours")
        if not h or not (0 <= h[0] < h[1] <= 24) or any(int(x) != x for x in h):
            errs.append(f'{who}: "hours" must be [start, end] whole hours 0–24, start before end')
        d = pair("dir")
        if not d or not all(0 <= x <= 360 for x in d):
            errs.append(f'{who}: "dir" must be [from, to] degrees 0–360')
        v = pair("speed")
        if not v or not (0 <= v[0] <= v[1]):
            errs.append(f'{who}: "speed" must be [min, max] km/h with min ≤ max')
        m = sp.get("min_hours")
        if not (isinstance(m, int) and not isinstance(m, bool) and m >= 1):
            errs.append(f'{who}: "min_hours" must be a whole number ≥ 1')
        elif h and h[1] - h[0] < m:
            errs.append(f'{who}: "min_hours" is longer than its hours range')
        if "max_cloud" in sp and not (_num(sp["max_cloud"]) and 0 <= sp["max_cloud"] <= 100):
            errs.append(f'{who}: "max_cloud" must be a number 0–100')
    return errs


def load_config(path):
    """(cfg, errors). JSON syntax errors are reported with their line number."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        return None, [f"cannot read {path}: {e.strerror}"]
    try:
        cfg = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [f"JSON error at line {e.lineno}, column {e.colno}: {e.msg}"]
    errs = validate_config(cfg)
    return (cfg if not errs else None), errs


def spots_from(cfg):
    dflt = cfg.get("defaults", {})
    return [{"max_cloud": dflt.get("max_cloud", DEFAULT_MAX_CLOUD), **s} for s in cfg["spots"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spots", default="spots.json", help="criteria to use (e.g. the repo's config/spots.json)")
    ap.add_argument("--fallback-spots", default=None, help="last good criteria, used if --spots is invalid")
    ap.add_argument("--config-commit", default="", help="short git commit of the criteria file, for display")
    ap.add_argument("--prev", default=None)
    ap.add_argument("--out", default="result.json")
    ap.add_argument("--export-dir", default=None,
                    help="write dashboard datasets (run/windows/changes/spots/previous .json)")
    a = ap.parse_args()

    cfg, errs = load_config(a.spots)
    config_source, config_error, config_commit = "primary", "", a.config_commit
    if errs:
        config_error = "; ".join(errs)
        if not a.fallback_spots:
            sys.exit(f"spots config invalid: {config_error}")
        cfg, ferrs = load_config(a.fallback_spots)
        if ferrs:
            sys.exit(f"spots config invalid: {config_error}; fallback also invalid: {'; '.join(ferrs)}")
        config_source, config_commit = "fallback", ""
    spots = spots_from(cfg)
    name2id = {s["name"]: s["id"] for s in spots}
    prev, prev_rows, first_run = {}, [], True
    if a.prev:
        try:
            raw = json.load(open(a.prev))
            first_run = False
            # windows are matched by spot id; rows from before ids existed fall back to the name
            if isinstance(raw, list):          # dashboard windows.json rows
                prev_rows = raw
                for r in raw:
                    key = r.get("spot_id") or name2id.get(r["spot"], r["spot"])
                    prev.setdefault(key, []).append(r)
            else:                              # full result.json
                for sp in raw.get("spots", []):
                    key = sp.get("id") or name2id.get(sp["name"], sp["name"])
                    prev[key] = sp["windows"]
                    prev_rows += [{"spot": sp["name"], "spot_id": key,
                                   **{k: v for k, v in w.items() if k != "detail"}} for w in sp["windows"]]
        except FileNotFoundError:
            pass
    now = datetime.now(TZ).replace(tzinfo=None)

    out = {"version": VERSION, "run_at": datetime.now(TZ).isoformat(timespec="seconds"),
           "first_run": first_run, "models": list(MODELS.values()), "spots": [],
           "config_source": config_source, "config_commit": config_commit, "config_error": config_error}
    for spot in spots:
        rows = blend(fetch(spot))
        wins = [w for w in find_windows(spot, rows) if _dt(w["end"]) > now]
        changes = [] if first_run else diff(prev.get(spot["id"], []), wins, now)
        out["spots"].append({**{k: spot[k] for k in ("id", "name", "lat", "lon", "hours", "dir", "speed", "min_hours", "max_cloud")},
                             "windows": wins, "changes": changes})
    out["change_count"] = sum(len(s["changes"]) for s in out["spots"])
    note = notification(out)
    if config_error:
        note = (f"⚠️ spots.json was not used ({config_error}). Using the last good criteria.\n" + note).strip()
    out["notification"] = note
    json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
    if a.export_dir:
        export(out, prev_rows, Path(a.export_dir))

    total = sum(len(s["windows"]) for s in out["spots"])
    print(f"Forecast Alerts v{VERSION} — {out['run_at']} — criteria: {config_source}"
          f"{' @' + config_commit if config_commit else ''} — {total} windows, "
          f"{out['change_count']} changes{' (first run, baseline only)' if first_run else ''}")
    for s in out["spots"]:
        print(f"{s['name']}: " + ("; ".join(fmt_w(w) for w in s["windows"]) or "no windows"))
    if out["notification"]:
        print("\nNOTIFICATION:\n" + out["notification"])


if __name__ == "__main__":
    sys.exit(main())
