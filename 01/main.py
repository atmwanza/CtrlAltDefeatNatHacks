from normalizer import load_spiral, normalize
from spiral_features import extract_features
# 1-2: build reference from UCI
healthy, pd = [], []
for path, label in uci_files:
    data = load_spiral(path)
    feats = extract_features(data)
    (pd if label == 1 else healthy).append(feats)

ref = build_group_stats(healthy, pd)

# 3-4: score new input
new = extract_features(load_spiral('spen_drawing.csv'))
level = score(new, ref)   # 0-5