import csv
from pathlib import Path

# UCI spiral files: no header, semicolon-delimited, columns in this order
COLUMNS = ["x", "y", "z", "pressure", "grip_angle", "timestamp", "test_id"]
