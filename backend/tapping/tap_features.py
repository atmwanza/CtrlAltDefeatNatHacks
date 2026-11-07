"""
tap_features.py - measurements from ONE 20-second DFT-style tapping trial.

Task (same general design as the published DFT protocol): hold the LEFT ARROW
with the middle finger and tap the DOWN ARROW with the index finger for 20 s.
Each hand is a separate trial. This is an independent research prototype, not
the original test.

Input CSV (header required), one row per key event:
    time_ms,key,event
    0.0,ArrowLeft,down
    812.4,ArrowDown,down
    905.1,ArrowDown,up
    ...
  key   : ArrowLeft (the held key) or ArrowDown (the tapped key)
  event : down or up
Front end: use event.code, performance.now(), and IGNORE events where
event.repeat is true (auto-repeat while a key is held).

Usage:  python tap_features.py trial.csv
"""
import csv
import json
import sys
import numpy as np

TRIAL_S = 20.0
MIN_DWELL_S = 0.020   # shorter than this = probably a glitch   (tunable assumption)
MAX_DWELL_S = 1.000   # longer than this = not a tap            (tunable assumption)

DEFINITIONS = {
    "ks20": "Kinesia score: number of valid taps in the 20 s trial. KS20 = total valid taps.",
    "at20_ms": "Akinesia time: mean key-hold time. Dwell_i = t_up,i - t_down,i; AT20 = mean(Dwell_i).",
    "is20_ms2": "Incoordination score: variance of travel times. Travel_i = t_down,i+1 - t_up,i; IS20 = Var(Travel).",
    "slowing_pct": "Progressive slowing: (taps in last 5 s - taps in first 5 s) / taps in first 5 s * 100. "
                   "A prototype feature, not the validated BRAIN sequence-effect algorithm.",
}


def load_events(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append((float(r["time_ms"]) / 1000.0, r["key"].strip(), r["event"].strip().lower()))
    rows.sort(key=lambda r: r[0])
    return rows


def extract_tap_features(events, trial_s=TRIAL_S):
    reasons, warnings = [], []

    # --- pair up ArrowDown down/up events into taps --------------------------
    taps, pending, dropped_repeats, orphan_ups = [], None, 0, 0
    for t, key, ev in events:
        if key != "ArrowDown":
            continue
        if ev == "down":
            if pending is not None:
                dropped_repeats += 1          # a second down with no up = auto-repeat/glitch
            else:
                pending = t
        elif ev == "up":
            if pending is None:
                orphan_ups += 1
            else:
                taps.append((pending, t))
                pending = None
    if not taps:
        return {"valid": False, "reasons": ["No taps recorded."], "warnings": []}

    t0 = taps[0][0]
    t_end = t0 + trial_s
    in_win = [(d, u) for d, u in taps if d < t_end]
    valid_taps = [(d, u) for d, u in in_win if MIN_DWELL_S <= (u - d) <= MAX_DWELL_S]
    n_invalid = len(in_win) - len(valid_taps)

    # --- quality checks (invalid recording vs. unusual movement) -------------
    last_event_t = max(t for t, _, _ in events)
    duration = last_event_t - t0
    left_events = [(t, ev) for t, k, ev in events if k == "ArrowLeft"]
    left_down = [t for t, ev in left_events if ev == "down"]
    hold_started = bool(left_down) and min(left_down) <= t0
    # A release only counts as a 'break' if tapping continued after it;
    # releasing the hold key after the last tap is just the end of the trial.
    last_tap_down = in_win[-1][0] if in_win else t0
    hold_breaks = sum(1 for t, ev in left_events if ev == "up" and t0 <= t < last_tap_down)
    if duration < trial_s - 2:
        reasons.append("Incomplete trial: only %.1f s recorded." % duration)
    if not hold_started:
        reasons.append("Hold key (ArrowLeft) was not down at the start.")
    if hold_breaks > 0:
        reasons.append("Hold key (ArrowLeft) was released %d time(s) during the trial." % hold_breaks)
    if len(valid_taps) < 10:
        reasons.append("Too few valid taps (%d)." % len(valid_taps))
    if in_win and n_invalid / len(in_win) > 0.2:
        reasons.append("%d of %d taps had implausible hold times." % (n_invalid, len(in_win)))
    if dropped_repeats:
        warnings.append("%d repeated keydown event(s) ignored (auto-repeat?)." % dropped_repeats)
    if orphan_ups:
        warnings.append("%d key-up event(s) had no matching key-down." % orphan_ups)

    if len(valid_taps) < 3:
        return {"valid": False, "reasons": reasons, "warnings": warnings}

    # --- measurements ---------------------------------------------------------
    downs = np.array([d for d, _ in valid_taps])
    ups = np.array([u for _, u in valid_taps])
    dwell_ms = (ups - downs) * 1000.0
    travel_ms = (downs[1:] - ups[:-1]) * 1000.0
    travel_ms = travel_ms[travel_ms > 0]
    first_n = int(np.sum((downs >= t0) & (downs < t0 + 5)))
    last_n = int(np.sum((downs >= t_end - 5) & (downs < t_end)))
    slowing = (last_n - first_n) / first_n * 100.0 if first_n > 0 else None

    return {
        "valid": len(reasons) == 0,
        "reasons": reasons,
        "warnings": warnings,
        "ks20": int(len(valid_taps)),
        "at20_ms": float(np.mean(dwell_ms)),
        "is20_ms2": float(np.var(travel_ms)) if len(travel_ms) > 1 else None,
        "mean_travel_ms": float(np.mean(travel_ms)) if len(travel_ms) else None,
        "mean_interval_ms": float(np.mean(np.diff(downs)) * 1000.0),
        "interval_series_ms": [round(float(v), 1) for v in np.diff(downs) * 1000.0][:200],
        "taps_first_5s": first_n,
        "taps_last_5s": last_n,
        "slowing_pct": float(slowing) if slowing is not None else None,
        "n_invalid_taps": int(n_invalid),
        "duration_s": float(duration),
    }


def features_from_csv(path):
    return extract_tap_features(load_events(path))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out = features_from_csv(sys.argv[1])
    out.pop("interval_series_ms", None)
    print(json.dumps(out, indent=2))
