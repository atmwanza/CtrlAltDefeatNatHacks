"""
make_demo_data.py - writes SYNTHETIC spiral CSVs so you can test the pipeline.
These are fake. They prove the code runs, not that it detects anything real.

Usage: python make_demo_data.py   (writes to demo_data/)
"""
import os
import numpy as np


def make_spiral(seed, impaired=False, turns=3, rmax=200.0, hz=60):
    rng = np.random.default_rng(seed)
    duration = rng.uniform(12, 16) if impaired else rng.uniform(7, 10)
    n = int(duration * hz)
    t = np.cumsum(rng.uniform(0.8, 1.2, n) / hz)
    t -= t[0]
    speed = np.ones(n)
    if impaired:                                   # hesitations: speed dips to ~0
        for c in rng.uniform(2, duration - 2, 3):
            speed -= 0.97 * np.exp(-((t - c) / 0.6) ** 2)
    progress = np.cumsum(speed)
    progress = progress / progress[-1]
    theta = 2 * np.pi * turns * progress
    r = rmax * progress * (0.8 if impaired else 1.0)
    if impaired:
        r = r + 3.0 * np.sin(2 * np.pi * 5.5 * t) + rng.normal(0, 1.5, n)
    else:
        r = r + rng.normal(0, 0.8, n)
    x = 400 + r * np.cos(theta)
    y = 300 + r * np.sin(theta)
    return t * 1000.0, x, y


def write_csv(path, t, x, y):
    with open(path, "w") as f:
        f.write("time_ms,x,y\n")
        for a, b, c in zip(t, x, y):
            f.write("%.1f,%.2f,%.2f\n" % (a, b, c))


if __name__ == "__main__":
    os.makedirs("demo_data", exist_ok=True)
    for i in range(10):
        write_csv("demo_data/healthy_%d.csv" % i, *make_spiral(100 + i))
    write_csv("demo_data/test_healthy.csv", *make_spiral(500))
    write_csv("demo_data/test_impaired.csv", *make_spiral(600, impaired=True))
    print("wrote demo_data/")
