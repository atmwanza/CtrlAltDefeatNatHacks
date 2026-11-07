import statistics
from normalizer import normalize


def extract_features(data):
    p = [v for v in normalize(data['pressure']) if v > 0]
    g = normalize(data['grip_angle'])
    x, y, t = data['x'], data['y'], data['timestamp']

    duration = (t[-1] - t[0]) / 1000  # ms -> seconds

    # path length, scaled by spiral size so it works across devices
    path = sum(((x[i] - x[i-1])**2 + (y[i] - y[i-1])**2) ** 0.5
               for i in range(1, len(x)))
    size = max(max(x) - min(x), max(y) - min(y))

    return {
        'pressure_cv': statistics.stdev(p),
        'grip_sd': statistics.stdev(g),
        'duration': duration,
        'speed': (path / size) / duration,
    }