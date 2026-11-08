"""pose.py - camera frames -> body landmarks (MediaPipe Pose) -> Brahm's sway features.

Bridges a recorded clip to sway_features.extract_sway_features(), which reads a landmark CSV
(time_ms, <name>_x, <name>_vis). The CSV is written to a temp file and deleted straight away;
the video itself is never saved.

The pixels-to-mm scale comes from the person's height: the shoulder-to-ankle distance in the
image is 77.9% of standing height (shoulder 0.818 H, ankle 0.039 H).
"""
import csv
import io
import os
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import cv2
import numpy as np

from sway_features import extract_sway_features   # Brahm's code, unchanged

HERE = Path(__file__).parent
POSE_MODEL = HERE / 'models' / 'pose_landmarker_lite.task'
POSE_URL = ('https://storage.googleapis.com/mediapipe-models/pose_landmarker/'
            'pose_landmarker_lite/float16/latest/pose_landmarker_lite.task')
SHOULDER_TO_ANKLE = 0.779
DEFAULT_HEIGHT_CM = 170
MIN_DETECT_PCT = 50

# MediaPipe Pose landmark indices, named the way sway_features expects them
LANDMARKS = {
    'left_ear': 7, 'right_ear': 8, 'left_shoulder': 11, 'right_shoulder': 12,
    'left_elbow': 13, 'right_elbow': 14, 'left_wrist': 15, 'right_wrist': 16,
    'left_pinky': 17, 'right_pinky': 18, 'left_index': 19, 'right_index': 20,
    'left_hip': 23, 'right_hip': 24, 'left_knee': 25, 'right_knee': 26,
    'left_ankle': 27, 'right_ankle': 28, 'left_foot_index': 31, 'right_foot_index': 32,
}


def load_clip(zip_bytes):
    """ZIP from the Pi capture service (NNNNN.jpg + timestamps.csv) ->
    (list of JPEG bytes, timestamps in ms from the first frame)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        rows = list(csv.DictReader(io.StringIO(z.read('timestamps.csv').decode())))
        frames = [z.read(f"{int(r['frame']):05d}.jpg") for r in rows]
    ts_ns = np.array([int(r['sensor_ts_ns']) for r in rows], dtype=np.int64)
    return frames, (ts_ns - ts_ns[0]) / 1e6


def ensure_pose_model():
    if not POSE_MODEL.exists():
        POSE_MODEL.parent.mkdir(exist_ok=True)
        urllib.request.urlretrieve(POSE_URL, POSE_MODEL)
    return POSE_MODEL


def extract_pose(frames, t_ms):
    """Per frame: {name: (x_pixels, visibility)}, or None when no person was found.
    Also returns the median shoulder-to-ankle height in pixels (None if never seen)."""
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    options = vision.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=str(ensure_pose_model())),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    rows, heights = [], []
    last_ts = -1
    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        for i, jpeg in enumerate(frames):
            bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                rows.append(None)
                continue
            h, w = bgr.shape[:2]
            ts = max(int(round(t_ms[i])), last_ts + 1)   # VIDEO mode needs strictly increasing ms
            last_ts = ts
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            res = landmarker.detect_for_video(image, ts)
            if not res.pose_landmarks:
                rows.append(None)
                continue
            p = res.pose_landmarks[0]
            rows.append({name: (p[k].x * w, p[k].visibility) for name, k in LANDMARKS.items()})
            shoulders = (p[11].y + p[12].y) / 2 * h
            ankles = (p[27].y + p[28].y) / 2 * h
            if ankles > shoulders:
                heights.append(ankles - shoulders)
    return rows, (float(np.median(heights)) if heights else None)


def write_landmark_csv(path, t_ms, rows):
    cols = ['time_ms'] + [f'{n}_{s}' for n in LANDMARKS for s in ('x', 'vis')]
    with open(path, 'w', newline='') as f:
        out = csv.writer(f)
        out.writerow(cols)
        for t, row in zip(t_ms, rows):
            if row is None:
                out.writerow([f'{t:.1f}'] + [''] * (len(cols) - 1))
            else:
                out.writerow([f'{t:.1f}'] + [f'{v:.3f}' for n in LANDMARKS for v in row[n]])


def analyze_frames(frames, t_ms, condition, height_cm=None):
    """Full analysis of one stage. Returns sway_features' result plus a few extras."""
    started = time.perf_counter()
    rows, body_px = extract_pose(frames, t_ms)
    detect_pct = 100 * sum(r is not None for r in rows) / max(len(rows), 1)
    height_cm = float(height_cm or DEFAULT_HEIGHT_CM)
    mm_per_px = SHOULDER_TO_ANKLE * height_cm * 10 / body_px if body_px else None

    fd, tmp = tempfile.mkstemp(suffix='.csv')
    os.close(fd)
    try:
        write_landmark_csv(tmp, t_ms, rows)
        feats = extract_sway_features(front=tmp, mm_per_px=mm_per_px, com='auto', condition=condition)
    except ValueError as e:
        feats = {'valid': False, 'reasons': [str(e)], 'warnings': []}
    finally:
        os.remove(tmp)

    if detect_pct < MIN_DETECT_PCT:
        feats['valid'] = False
        feats.setdefault('reasons', []).append(
            f'A person was found in only {detect_pct:.0f}% of frames. Stand so your whole body is in view.')
    if not mm_per_px:
        feats.setdefault('warnings', []).append(
            'Shoulders and ankles were not both in view, so sway is in pixels, not mm.')
    feats.update(condition=condition, detect_pct=round(detect_pct, 1), n_frames=len(rows),
                 height_cm=height_cm, mm_per_px=round(mm_per_px, 3) if mm_per_px else None,
                 analysis_s=round(time.perf_counter() - started, 2))
    return feats