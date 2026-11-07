"""
make_demo_tap_data.py - writes SYNTHETIC tapping trials for testing the code.
They are fake: they show the pipeline runs, not that it detects anything real.

Usage: python make_demo_tap_data.py   (writes to demo_tap_data/)
"""
import os
import numpy as np


def make_trial(seed, slow=False, break_hold=False, total_s=20.5):
    rng = np.random.default_rng(seed)
    ev = [(0.0, "ArrowLeft", "down")]
    t, i = 0.8, 0
    while t < total_s - 0.4:
        frac = t / 20.0
        dwell = rng.normal(0.125 if slow else 0.095, 0.015 if slow else 0.010)
        travel = rng.normal(0.17 if slow else 0.11, 0.05 if slow else 0.018)
        if slow:
            travel *= 1.0 + 0.6 * frac                    # progressive slowing
        dwell, travel = max(dwell, 0.03), max(travel, 0.03)
        ev.append((t, "ArrowDown", "down"))
        ev.append((t + dwell, "ArrowDown", "up"))
        t += dwell + travel
        i += 1
    if break_hold:
        ev.append((9.0, "ArrowLeft", "up"))
    ev.append((total_s, "ArrowLeft", "up"))
    return ev


def write_trial(path, ev):
    with open(path, "w") as f:
        f.write("time_ms,key,event\n")
        for t, k, e in sorted(ev):
            f.write("%.1f,%s,%s\n" % (t * 1000.0, k, e))


if __name__ == "__main__":
    os.makedirs("demo_tap_data", exist_ok=True)
    for i in range(10):
        write_trial("demo_tap_data/healthy_%d.csv" % i, make_trial(200 + i))
    write_trial("demo_tap_data/test_healthy.csv", make_trial(700))
    write_trial("demo_tap_data/test_healthy_retest.csv", make_trial(701))
    write_trial("demo_tap_data/test_slow.csv", make_trial(800, slow=True))
    write_trial("demo_tap_data/test_invalid.csv", make_trial(900, break_hold=True))
    print("wrote demo_tap_data/")
