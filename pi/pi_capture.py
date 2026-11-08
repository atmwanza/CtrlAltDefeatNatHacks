#!/usr/bin/env python3
"""DrawDx finger-tapping capture service.

Runs on the Raspberry Pi (camera module), or on the laptop as the webcam fallback, or
with a synthetic source for testing the plumbing. It records a clip when the laptop asks,
then uploads it; it never analyses or stores anything itself.

    Pi:       python3 pi_capture.py                      (SOURCE=picamera, the default)
    Webcam:   SOURCE=webcam python pi/pi_capture.py      (laptop fallback)
    Testing:  SOURCE=synthetic python pi/pi_capture.py   (blank frames, no camera needed)

HTTP (port 8000): GET /health, GET /snapshot.jpg, POST /record {session_id, hand, duration_s}
Every 5 s it says hello to the laptop (POST /pi/hello) so the laptop knows where it is.
Uploads go to the laptop: POST /tapping/upload (multipart: clip=ZIP, meta=JSON).

Settings (environment variables, all optional):
    SOURCE        picamera | webcam | synthetic
    LAPTOP_URLS   comma-separated, tried in order
                  (default: hotspot http://192.168.137.1:5000, Ethernet http://10.42.0.1:5000;
                   for webcam/synthetic: http://127.0.0.1:5000)
    PORT          8000
    FPS           40 (picamera; the V2's full-view mode tops out at ~41.85), 30 (webcam)
    EXPOSURE_US   5000   short exposure so fast fingers don't blur (needs a bright lamp)
    GAIN          4.0
    JPEG_QUALITY  85
    LED_PIN       17     BCM pin for the "recording" LED (Pi only; skipped if absent)
"""
import io
import json
import os
import statistics
import sys
import threading
import time
import zipfile

import numpy as np
import requests
from flask import Flask, Response, jsonify, request

SOURCE = os.environ.get('SOURCE', 'picamera').lower()
LOCAL = SOURCE in ('webcam', 'synthetic')
LAPTOP_URLS = [u.strip().rstrip('/') for u in os.environ.get(
    'LAPTOP_URLS',
    'http://127.0.0.1:5000' if LOCAL else 'http://192.168.137.1:5000,http://10.42.0.1:5000').split(',') if u.strip()]
PORT = int(os.environ.get('PORT', 8000))
FPS = int(os.environ.get('FPS', 30 if SOURCE == 'webcam' else 40))
EXPOSURE_US = int(os.environ.get('EXPOSURE_US', 5000))
GAIN = float(os.environ.get('GAIN', 4.0))
JPEG_QUALITY = int(os.environ.get('JPEG_QUALITY', 85))
LED_PIN = int(os.environ.get('LED_PIN', 17))
SIZE = (640, 480)


# ---------- status LED (Pi only, optional) ----------

class _NoLed:
    def on(self): pass
    def off(self): pass
    def blink(self, *a, **k): pass


def _make_led():
    if SOURCE != 'picamera':
        return _NoLed()
    try:
        from gpiozero import LED
        return LED(LED_PIN)
    except Exception as e:   # no gpiozero / not wired: run without the LED
        print(f'[capture] LED disabled: {e}', flush=True)
        return _NoLed()


# ---------- camera sources: grab() -> (BGR uint8 array 480x640x3, timestamp in ns) ----------

class PiCameraSource:
    name = 'imx219'

    def __init__(self):
        from picamera2 import Picamera2
        self.cam = Picamera2()
        info = self.cam.camera_properties.get('Model', 'unknown')
        self.name = str(info)
        config = self.cam.create_video_configuration(
            main={'size': SIZE, 'format': 'RGB888'},            # BGR byte order in memory
            sensor={'output_size': (1640, 1232), 'bit_depth': 10},   # V2 full-view binned mode
            controls={'FrameDurationLimits': (1_000_000 // FPS, 1_000_000 // FPS),
                      'AeEnable': False, 'ExposureTime': EXPOSURE_US, 'AnalogueGain': GAIN},
            buffer_count=6)
        self.cam.configure(config)
        self.cam.start()

    def grab(self):
        req = self.cam.capture_request()
        try:
            return req.make_array('main'), int(req.get_metadata()['SensorTimestamp'])
        finally:
            req.release()


class WebcamSource:
    name = 'webcam'

    def __init__(self):
        import cv2
        self.cv2 = cv2
        self._open()

    def _open(self):
        cv2 = self.cv2
        backend = cv2.CAP_DSHOW if sys.platform.startswith('win') else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(int(os.environ.get('WEBCAM_INDEX', 0)), backend)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, SIZE[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, SIZE[1])
        self.cap.set(cv2.CAP_PROP_FPS, FPS)
        if not self.cap.isOpened():
            raise RuntimeError('Could not open the webcam.')

    def grab(self):
        ok, frame = self.cap.read()
        if not ok:
            # e.g. a laptop privacy shutter toggled: the camera drops off and comes back
            self.cap.release()
            time.sleep(0.5)
            self._open()
            ok, frame = self.cap.read()
        ts = time.perf_counter_ns()          # webcam has no sensor clock: time of arrival
        if not ok:
            raise RuntimeError('Webcam frame grab failed.')
        if frame.shape[1] != SIZE[0]:
            frame = self.cv2.resize(frame, SIZE)
        return frame, ts


class SyntheticSource:
    name = 'synthetic'

    def __init__(self):
        self.next_t = time.perf_counter()

    def grab(self):
        # pace at FPS; after idle time, restart the clock instead of bursting to catch up
        self.next_t = max(self.next_t + 1 / FPS, time.perf_counter())
        delay = self.next_t - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        frame = np.full((SIZE[1], SIZE[0], 3), 40, np.uint8)
        return frame, time.perf_counter_ns()


def _encode_jpeg(arr, quality):
    try:
        import simplejpeg   # fast on the Pi
        return simplejpeg.encode_jpeg(np.ascontiguousarray(arr), quality=quality, colorspace='BGR')
    except ImportError:
        import cv2
        ok, buf = cv2.imencode('.jpg', arr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        return buf.tobytes()


source = {'picamera': PiCameraSource, 'webcam': WebcamSource, 'synthetic': SyntheticSource}[SOURCE]()
led = _make_led()
cam_lock = threading.Lock()      # one reader at a time (recording vs snapshot)
busy = threading.Lock()          # one recording at a time
state = {'laptop': None, 'last': None}
app = Flask(__name__)


def grab():
    with cam_lock:
        return source.grab()


def post_laptop(path, timeout, **kw):
    """POST to the laptop, trying the last good URL first. Returns True on success."""
    urls = ([state['laptop']] if state['laptop'] else []) + [u for u in LAPTOP_URLS if u != state['laptop']]
    for base in urls:
        try:
            r = requests.post(base + path, timeout=timeout, **kw)
            r.raise_for_status()
            state['laptop'] = base
            return True
        except requests.RequestException:
            continue
    return False


def record_and_upload(sid, hand, duration):
    frames, ts = [], []
    try:
        led.on()
        t_end = time.monotonic() + duration
        while time.monotonic() < t_end:
            arr, t = grab()
            frames.append(_encode_jpeg(arr, JPEG_QUALITY))
            ts.append(t)
        led.off()

        dt = [(b - a) / 1e6 for a, b in zip(ts, ts[1:])]
        med = statistics.median(dt) if dt else 0
        drops = sum(round(d / med) - 1 for d in dt if med and d > 1.5 * med)
        fps = (len(ts) - 1) / ((ts[-1] - ts[0]) / 1e9) if len(ts) > 1 else 0
        print(f'[capture] {sid} {hand}: frames={len(ts)} fps={fps:.1f} median_dt={med:.1f}ms drops={drops}', flush=True)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:   # JPEGs are already compressed
            z.writestr('timestamps.csv', 'frame,sensor_ts_ns\n' + ''.join(f'{i},{t}\n' for i, t in enumerate(ts)))
            for i, f in enumerate(frames):
                z.writestr(f'{i:05d}.jpg', f)
        meta = dict(session_id=sid, hand=hand, duration_s=duration, n_frames=len(ts), fps_cfg=FPS,
                    fps_measured=round(fps, 2), drops=drops, exposure_us=EXPOSURE_US, gain=GAIN,
                    res=list(SIZE), camera=source.name, source=SOURCE,
                    ts_source='SensorTimestamp' if SOURCE == 'picamera' else 'perf_counter')
        led.blink(0.1, 0.1)
        ok = post_laptop('/tapping/upload', timeout=60,
                         files={'clip': ('clip.zip', buf.getvalue(), 'application/zip')},
                         data={'meta': json.dumps(meta)})
        state['last'] = dict(meta, uploaded=ok, mb=round(len(buf.getvalue()) / 1e6, 1))
        print(f'[capture] {sid} upload {"ok" if ok else "FAILED"} ({state["last"]["mb"]} MB)', flush=True)
    except Exception as e:
        print(f'[capture] {sid} recording failed: {e}', flush=True)
        state['last'] = {'session_id': sid, 'error': str(e)}
    finally:
        led.off()
        frames.clear()          # nothing is kept on the capture device
        busy.release()


@app.post('/record')
def record():
    if not busy.acquire(blocking=False):
        return jsonify(error='busy'), 409
    body = request.get_json(force=True)
    duration = min(float(body.get('duration_s', 10)), 30)
    threading.Thread(target=record_and_upload, args=(body['session_id'], body.get('hand'), duration),
                     daemon=True).start()
    return jsonify(accepted=True), 202


@app.get('/snapshot.jpg')
def snapshot():
    if busy.locked():
        return 'recording', 409          # never take frames away from a recording
    arr, _ = grab()
    return Response(_encode_jpeg(arr, 70), mimetype='image/jpeg', headers={'Cache-Control': 'no-store'})


@app.get('/health')
def health():
    return jsonify(ok=True, busy=busy.locked(), source=SOURCE, camera=source.name, fps_cfg=FPS,
                   laptop=state['laptop'], last=state['last'])


def heartbeat():
    while True:
        post_laptop('/pi/hello', timeout=2, json={'port': PORT, 'source': SOURCE, 'camera': source.name})
        time.sleep(5)


if __name__ == '__main__':
    print(f'[capture] source={SOURCE} camera={source.name} fps={FPS} port={PORT} laptop={LAPTOP_URLS}', flush=True)
    threading.Thread(target=heartbeat, daemon=True).start()
    # On the laptop (webcam/synthetic) only the local backend needs to reach us.
    app.run(host='127.0.0.1' if LOCAL else '0.0.0.0', port=PORT, threaded=True)
