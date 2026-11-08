#!/usr/bin/env python3
"""Live sharpness meter for focusing the Camera Module V2 at hand distance.

Tape a page of small text 45-50 cm from the lens, run this, then turn the lens with the
plastic focus tool 1/8 turn at a time. Stop at the highest number. (The V2 ships focused
near infinity, so a hand at 45 cm is soft until refocused.)

    python3 focus_check.py        Ctrl+C to stop (stop the capture service first:
                                   sudo systemctl stop drawdx-capture)
"""
import time

import numpy as np
from picamera2 import Picamera2

cam = Picamera2()
cam.configure(cam.create_video_configuration(main={'size': (640, 480), 'format': 'YUV420'}))
cam.start()
best = 0.0
try:
    while True:
        y = cam.capture_array()[:480, :640].astype(float)        # luminance plane
        lap = np.abs(4 * y[1:-1, 1:-1] - y[:-2, 1:-1] - y[2:, 1:-1] - y[1:-1, :-2] - y[1:-1, 2:])
        score = lap.var()
        best = max(best, score)
        bar = '#' * int(40 * score / best) if best else ''
        print(f'sharpness {score:9.1f}   best {best:9.1f}   {bar}', flush=True)
        time.sleep(0.3)
except KeyboardInterrupt:
    pass
finally:
    cam.stop()
