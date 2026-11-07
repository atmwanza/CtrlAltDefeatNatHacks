import math
import statistics
from normalizer import normalize


def band_power(signal, fs, lo, hi, step=0.5):
    """Total power of the signal between lo and hi Hz."""
    total = 0.0
    f = lo
    while f <= hi:
        w = 2 * math.pi * f / fs
        re = sum(s * math.cos(w * i) for i, s in enumerate(signal))
        im = sum(s * math.sin(w * i) for i, s in enumerate(signal))
        total += re * re + im * im
        f += step
    return total


def remove_slow_motion(v, window):
    """Subtract a moving average so only fast wobble is left."""
    sums = [0.0]
    for val in v:
        sums.append(sums[-1] + val)
    out = []
    for i in range(len(v)):
        a = max(0, i - window // 2)
        b = min(len(v), i + window // 2 + 1)
        out.append(v[i] - (sums[b] - sums[a]) / (b - a))
    return out


def tremor_ratio(x, y, t):
    """Share of the pen's wobble that sits in the 4-6 Hz Parkinson's tremor band."""
    gaps = [t[i] - t[i - 1] for i in range(1, len(t))]
    fs = 1000 / statistics.median(gaps)          # samples per second
    vx = [x[i] - x[i - 1] for i in range(1, len(x))]
    vy = [y[i] - y[i - 1] for i in range(1, len(y))]
    window = int(fs / 2)                          # 0.5 s
    vx = remove_slow_motion(vx, window)
    vy = remove_slow_motion(vy, window)
    tremor = band_power(vx, fs, 4, 6) + band_power(vy, fs, 4, 6)
    overall = band_power(vx, fs, 1, 15) + band_power(vy, fs, 1, 15)
    return tremor / overall


def spiral_deviation(x, y):
    """How far the drawing strays from a smooth spiral, as a fraction of its size."""
    cx, cy = statistics.mean(x), statistics.mean(y)
    radius = [math.hypot(a - cx, b - cy) for a, b in zip(x, y)]

    # angle around the centre, "unwrapped" so it keeps growing each loop
    angle = [math.atan2(y[0] - cy, x[0] - cx)]
    for i in range(1, len(x)):
        step = math.atan2(y[i] - cy, x[i] - cx) - math.atan2(y[i - 1] - cy, x[i - 1] - cx)
        while step > math.pi:
            step -= 2 * math.pi
        while step < -math.pi:
            step += 2 * math.pi
        angle.append(angle[-1] + step)

    # an ideal Archimedean spiral is a straight line: radius = a + b * angle
    ma, mr = statistics.mean(angle), statistics.mean(radius)
    b = (sum((t - ma) * (r - mr) for t, r in zip(angle, radius))
         / sum((t - ma) ** 2 for t in angle))
    a = mr - b * ma
    errors = [r - (a + b * t) for t, r in zip(angle, radius)]

    size = max(max(x) - min(x), max(y) - min(y))
    return statistics.pstdev(errors) / size


def extract_features(data):
    p = [v for v in normalize(data['pressure']) if v > 0]
    x, y, t = data['x'], data['y'], data['timestamp']
    return {
        'pressure_cv': statistics.stdev(p),
        'tremor': tremor_ratio(x, y, t),
        'deviation': spiral_deviation(x, y),
    }