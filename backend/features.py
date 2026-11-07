"""
features.py - turns one spiral-drawing CSV into a dictionary of measurements.

Input CSV columns (header row required):  time_ms, x, y
  time_ms : timestamp of each sample in milliseconds
  x, y    : pen/mouse position in pixels

Assumes the spiral is drawn OUTWARD, starting near the center.
Optional template info from the drawing screen (more accurate):
  template_turns  : number of turns of the template spiral
  template_rmax   : outer radius of the template spiral, in pixels

Usage:  python features.py spiral.csv [template_turns template_rmax]
"""
import csv
import json
import sys
import numpy as np

RESAMPLE_HZ = 100.0   # we resample to an even time grid so derivatives work
TREMOR_BAND = (4.0, 12.0)   # Hz - exploratory, check against your sources


def load_csv(path):
    t, x, y = [], [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t.append(float(row["time_ms"]) / 1000.0)
            x.append(float(row["x"]))
            y.append(float(row["y"]))
    t, x, y = np.array(t), np.array(x), np.array(y)
    # drop duplicate / out-of-order timestamps
    t, idx = np.unique(t, return_index=True)
    return t, x[idx], y[idx]


def smooth(a, w):
    """Moving average with odd window w (edges padded)."""
    if w <= 1:
        return a
    pad = w // 2
    ap = np.pad(a, pad, mode="edge")
    return np.convolve(ap, np.ones(w) / w, mode="valid")[:len(a)]


def count_runs(mask, min_len):
    """Count runs of True of at least min_len samples; return (count, total_samples)."""
    n_runs, total, run = 0, 0, 0
    for m in mask:
        if m:
            run += 1
        else:
            if run >= min_len:
                n_runs += 1
                total += run
            run = 0
    if run >= min_len:
        n_runs += 1
        total += run
    return n_runs, total


def bandpass(sig, hz, lo, hi):
    spec = np.fft.rfft(sig - np.mean(sig))
    f = np.fft.rfftfreq(len(sig), 1.0 / hz)
    spec[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(spec, n=len(sig))


def extract_features(t, x, y, template_turns=None, template_rmax=None):
    warnings = []
    if len(t) < 50:
        raise ValueError("Need at least 50 samples (got %d)" % len(t))

    median_dt = float(np.median(np.diff(t)))
    sampling_hz = 1.0 / median_dt
    duration = float(t[-1] - t[0])
    if sampling_hz < 30:
        warnings.append("Low sampling rate (%.0f Hz): tremor measures are unreliable." % sampling_hz)
    if duration < 3:
        warnings.append("Drawing is very short (%.1f s)." % duration)

    # --- resample to an even grid -------------------------------------------
    dt = 1.0 / RESAMPLE_HZ
    tg = np.arange(t[0], t[-1], dt)
    xg = np.interp(tg, t, x)
    yg = np.interp(tg, t, y)

    # --- speed, jerk (smoothed, so noise isn't blown up by differentiation) --
    xs, ys = smooth(xg, 9), smooth(yg, 9)
    vx, vy = np.gradient(xs, dt), np.gradient(ys, dt)
    speed = np.hypot(vx, vy)
    ax, ay = np.gradient(vx, dt), np.gradient(vy, dt)
    jx, jy = np.gradient(ax, dt), np.gradient(ay, dt)
    jerk = np.hypot(jx, jy)
    path_len = float(np.sum(speed) * dt)
    T = len(tg) * dt
    # dimensionless normalized jerk (lower = smoother)
    norm_jerk = float(np.sqrt(0.5 * np.sum(jerk ** 2) * dt * T ** 5 / (path_len ** 2)))

    # --- polar coordinates around the spiral center -------------------------
    # Near the center the angle is meaningless noise, so we only start
    # measuring once the pen is a few percent of the way out.
    cx, cy = np.mean(xg[:5]), np.mean(yg[:5])
    r_full = np.hypot(xg - cx, yg - cy)
    valid = np.where(r_full > 0.08 * np.max(r_full))[0]
    i0 = int(valid[0])
    theta = np.unwrap(np.arctan2(yg[i0:] - cy, xg[i0:] - cx))
    if theta[-1] < theta[0]:        # clockwise drawing -> flip so angle grows
        theta = -theta
    theta = theta - theta[0]
    r = r_full[i0:]
    tg = tg[i0:]
    speed = speed[i0:]
    total_angle = float(theta[-1])
    total_turns = total_angle / (2 * np.pi)
    if total_turns < 1:
        warnings.append("Less than one full turn detected; results may be meaningless.")
        total_angle = max(total_angle, 1e-6)
    T_draw = len(tg) * dt           # time spent drawing (from the first valid point)

    # --- angular velocity ----------------------------------------------------
    omega = np.gradient(smooth(theta, 9), dt)
    mean_omega = total_angle / T_draw
    omega_cv = float(np.std(omega) / max(abs(np.mean(omega)), 1e-9))

    # --- pauses / hesitations (angular speed, so a bigger radius isn't "faster")
    thresh = 0.1 * float(np.median(omega))
    n_pauses, pause_samples = count_runs(omega < thresh, int(0.2 * RESAMPLE_HZ))
    pause_time = pause_samples * dt

    # --- expansion rate of the radius, and error vs an ideal spiral ---------
    r_max_drawn = float(np.max(r))
    r_max_ref = float(template_rmax) if template_rmax else r_max_drawn
    if template_turns and template_rmax:
        b_ideal = float(template_rmax) / (2 * np.pi * float(template_turns))
    else:
        b_ideal = r_max_drawn / total_angle
    b_fit, _ = np.polyfit(theta, r, 1)
    half = len(theta) // 2
    b_first, _ = np.polyfit(theta[:half], r[:half], 1)
    b_second, _ = np.polyfit(theta[half:], r[half:], 1)
    r_ideal = b_ideal * theta
    err_px = float(np.mean(np.abs(r - r_ideal)))

    hypometria = (r_max_drawn / float(template_rmax)) if template_rmax else None

    # --- tremor (exploratory): wobble of the radius at 4-12 Hz ---------------
    tremor_fraction, tremor_rms, tremor_peak = None, None, None
    if sampling_hz >= 30 and len(tg) >= 200:
        resid = r - smooth(r, 51)                      # remove slow drawing path
        spec = np.abs(np.fft.rfft(resid * np.hanning(len(resid)))) ** 2
        f = np.fft.rfftfreq(len(resid), dt)
        band = (f >= TREMOR_BAND[0]) & (f <= TREMOR_BAND[1])
        total = (f >= 1) & (f <= 25)
        tremor_fraction = float(spec[band].sum() / max(spec[total].sum(), 1e-12))
        tremor_rms = float(np.std(bandpass(resid, RESAMPLE_HZ, *TREMOR_BAND)))
        tremor_peak = float(f[band][np.argmax(spec[band])])

    return {
        "mean_angular_velocity": float(mean_omega),          # rad/s, lower = slower
        "angular_velocity_cv": omega_cv,                     # speed steadiness
        "mean_speed_px_s": float(np.mean(speed)),
        "normalized_jerk": norm_jerk,                        # higher = less smooth
        "mean_jerk_px_s3": float(np.mean(jerk)),
        "pause_time_s": float(pause_time),
        "pause_fraction": float(pause_time / T_draw),
        "n_pauses": int(n_pauses),
        "expansion_rate_px_per_rad": float(b_fit),
        "expansion_ratio": float(b_fit / b_ideal),           # 1.0 = matches ideal spiral
        "expansion_halves_ratio": float(b_second / b_first) if abs(b_first) > 1e-9 else None,
        "error_distance_px": err_px,
        "error_distance_norm": float(err_px / r_max_ref),    # fraction of spiral size
        "hypometria_ratio": hypometria,                      # drawn size / template size
        "tremor_band_fraction": tremor_fraction,
        "tremor_rms_px": tremor_rms,
        "tremor_peak_hz": tremor_peak,
        "quality": {
            "n_samples": int(len(t)),
            "duration_s": duration,
            "sampling_hz": float(sampling_hz),
            "total_turns": float(total_turns),
            "warnings": warnings,
        },
    }


def features_from_csv(path, template_turns=None, template_rmax=None):
    t, x, y = load_csv(path)
    return extract_features(t, x, y, template_turns, template_rmax)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    tt = float(sys.argv[2]) if len(sys.argv) > 3 else None
    tr = float(sys.argv[3]) if len(sys.argv) > 3 else None
    print(json.dumps(features_from_csv(sys.argv[1], tt, tr), indent=2))
