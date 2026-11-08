"""
make_demo_sway_data.py - writes SYNTHETIC pose-landmark recordings for testing.
They are fake (a rigid body rocking about the ankles plus tracker jitter):
they show the pipeline runs, not that it measures anything real.

Usage: python make_demo_sway_data.py   (writes to demo_sway_data/)
"""
import os
import numpy as np

MM_PER_PX = 1.4
H_MM = 1700.0
# (lateral offset in mm for the FRONT view, height as fraction of body height)
POINTS = {
    "ear": (80, 0.93), "shoulder": (200, 0.82), "elbow": (230, 0.62), "wrist": (220, 0.47),
    "hip": (90, 0.53), "knee": (90, 0.285), "ankle": (90, 0.04),
    "foot_index": (90, 0.0), "index": (215, 0.42), "pinky": (225, 0.43),
}


def lowpass_noise(rng, n, fs, cutoff, rms_mm):
    w = rng.normal(size=n)
    spec = np.fft.rfft(w)
    spec[np.fft.rfftfreq(n, 1.0 / fs) > cutoff] = 0
    x = np.fft.irfft(spec, n=n)
    return x / np.std(x) * rms_mm


def make_trial(seed, rms_ml=3.0, rms_ap=4.0, duration=40.0, jitter_px=1.5, excursion=False, fs=30.0):
    rng = np.random.default_rng(seed)
    n = int(duration * fs)
    t = np.cumsum(rng.uniform(0.9, 1.1, n) / fs)
    t -= t[0]
    ml = lowpass_noise(rng, n, fs, 0.8, rms_ml) if rms_ml > 0 else np.zeros(n)
    ap = lowpass_noise(rng, n, fs, 0.8, rms_ap) if rms_ap > 0 else np.zeros(n)
    if excursion:
        k = int(0.6 * n)
        ml[k:k + 45] += 170.0 * np.sin(np.linspace(0, np.pi, 45))
    out = {}
    for view, sway in (("front", ml), ("side", ap)):
        phi = sway / (0.555 * H_MM)                    # rocking angle; CoM sits at 0.555 H
        cols = {"time_ms": t * 1000.0}
        for name, (off, h) in POINTS.items():
            for side, sign in (("left_", -1), ("right_", 1)):
                lateral = sign * off if view == "front" else (100.0 if name == "foot_index" else 0.0)
                x_mm = lateral + phi * h * H_MM
                cols[side + name + "_x"] = 400.0 + x_mm / MM_PER_PX + rng.normal(0, jitter_px, n)
                cols[side + name + "_vis"] = np.clip(rng.normal(0.95, 0.02, n), 0, 1)
        out[view] = cols
    return out


def write_csv(path, cols):
    names = list(cols)
    with open(path, "w") as f:
        f.write(",".join(names) + "\n")
        for i in range(len(cols["time_ms"])):
            f.write(",".join("%.3f" % cols[k][i] for k in names) + "\n")


if __name__ == "__main__":
    os.makedirs("demo_sway_data", exist_ok=True)
    rng = np.random.default_rng(1)
    for i in range(10):
        s = max(1.8, rng.normal(3.0, 0.5))
        write_csv("demo_sway_data/healthy_eo_%d.csv" % i, make_trial(300 + i, rms_ml=s, rms_ap=1.3 * s)["front"])
        write_csv("demo_sway_data/healthy_ec_%d.csv" % i, make_trial(400 + i, rms_ml=1.4 * s, rms_ap=1.8 * s)["front"])
    p = make_trial(700, rms_ml=3.0, rms_ap=4.0)
    write_csv("demo_sway_data/test_eo_front.csv", p["front"])
    write_csv("demo_sway_data/test_eo_side.csv", p["side"])
    write_csv("demo_sway_data/test_ec_front.csv", make_trial(701, rms_ml=4.3, rms_ap=5.5)["front"])
    write_csv("demo_sway_data/test_high_sway.csv", make_trial(702, rms_ml=9.0, rms_ap=11.0)["front"])
    write_csv("demo_sway_data/test_noisy.csv", make_trial(703, jitter_px=14.0)["front"])
    write_csv("demo_sway_data/test_short.csv", make_trial(704, duration=12.0)["front"])
    write_csv("demo_sway_data/test_step.csv", make_trial(705, excursion=True)["front"])
    write_csv("demo_sway_data/mannequin.csv", make_trial(706, rms_ml=0.0, rms_ap=0.0)["front"])
    print("wrote demo_sway_data/")
