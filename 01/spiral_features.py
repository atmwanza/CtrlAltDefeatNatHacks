import numpy as np

FS = 100          # resample every drawing to 100 samples per second
SMOOTH = 9        # moving-average window (samples) before taking velocity


def resample(t_ms, *signals):
    """Put irregular samples (browser pen events) onto an even 100 Hz time grid."""
    t = (np.asarray(t_ms, dtype=float) - t_ms[0]) / 1000.0
    keep = np.concatenate(([True], np.diff(t) > 0))   # drop duplicate timestamps
    t = t[keep]
    grid = np.arange(0, t[-1], 1 / FS)
    return [np.interp(grid, t, np.asarray(s, dtype=float)[keep]) for s in signals]


def moving_average(v, n):
    return np.convolve(v, np.ones(n) / n, mode='same')


def spectrum(v):
    """Power spectrum of the fast wobble in v (slow drawing motion removed, Hann window)."""
    fast = v - moving_average(v, FS // 2)                # strip motion slower than ~2 Hz
    power = np.abs(np.fft.rfft(fast * np.hanning(len(fast)))) ** 2
    freqs = np.fft.rfftfreq(len(fast), 1 / FS)
    return freqs, power


def tremor_features(x, y):
    """Share of wobble in the 4-6 Hz Parkinson's band, and the dominant 4-12 Hz frequency."""
    f, px = spectrum(np.diff(x) * FS)
    _, py = spectrum(np.diff(y) * FS)
    power = px + py
    band = (f >= 4) & (f <= 6)
    overall = (f >= 1) & (f <= 15)
    search = (f >= 4) & (f <= 12)
    tremor_pct = power[band].sum() / power[overall].sum()
    dom_freq = f[search][np.argmax(power[search])]
    return float(tremor_pct), float(dom_freq)


def velocity_cv(x, y):
    """How uneven the pen speed is (std / mean of smoothed speed)."""
    xs, ys = moving_average(x, SMOOTH), moving_average(y, SMOOTH)
    speed = np.hypot(np.diff(xs), np.diff(ys))[SMOOTH:-SMOOTH]  # trim smoothing edge effects
    return float(speed.std() / speed.mean())

def _spiral_fit(x, y, cx, cy):
    """Fit radius = a + b * angle around (cx, cy); return the leftover errors."""
    radius = np.hypot(x - cx, y - cy)
    angle = np.unwrap(np.arctan2(y - cy, x - cx))
    b, a = np.polyfit(angle, radius, 1)
    return radius - (a + b * angle), angle


def find_centre(x, y):
    """The spiral's true centre: the point that makes it closest to a perfect spiral.

    The average of the points is NOT the centre of a spiral (it's pulled toward the
    outer loop), which made even a perfect drawing look like it deviated.
    """
    step = max(1, len(x) // 800)                  # search on a subsample for speed
    xs, ys = x[::step], y[::step]
    cx, cy = x.mean(), y.mean()
    span = 0.25 * max(np.ptp(x), np.ptp(y))
    for _ in range(4):                            # coarse-to-fine grid search
        offsets = np.linspace(-span, span, 9)
        best = None
        for dx in offsets:
            for dy in offsets:
                err = _spiral_fit(xs, ys, cx + dx, cy + dy)[0].std()
                if best is None or err < best[0]:
                    best = (err, cx + dx, cy + dy)
        _, cx, cy = best
        span /= 4
    return cx, cy


def spiral_deviation(x, y):
    """How far the drawing strays from a smooth Archimedean spiral, as a fraction of its size."""
    cx, cy = find_centre(x, y)
    errors, _ = _spiral_fit(x, y, cx, cy)
    size = max(np.ptp(x), np.ptp(y))
    return float(errors.std() / size)


def turns(x, y):
    cx, cy = find_centre(x, y)
    _, angle = _spiral_fit(x, y, cx, cy)
    return float(abs(angle[-1] - angle[0]) / (2 * np.pi))


def extract_features(data, use_pressure=True):
    """data: dict with x, y, timestamp (ms) and pressure lists.

    Returns the scored features plus display-only ones.
    """
    x, y, p = resample(data['timestamp'], data['x'], data['y'], data['pressure'])
    tremor_pct, dom_freq = tremor_features(x, y)

    feats = {
        'dev_norm': spiral_deviation(x, y),
        'tremor_pct': tremor_pct,
        'vel_cv': velocity_cv(x, y),
        'dom_freq': dom_freq,          # display only, not scored
    }
    if use_pressure:
        p = p[p > 0]
        feats['p_cv'] = float(p.std() / p.mean())
    return feats