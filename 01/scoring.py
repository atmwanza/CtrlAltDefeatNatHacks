import math
import statistics


def build_group_stats(healthy, pd):
    ref = {}
    for name in healthy[0]:
        h = [f[name] for f in healthy]
        p = [f[name] for f in pd]
        ref[name] = {
            'h_mean': statistics.mean(h), 'h_sd': statistics.stdev(h),
            'p_mean': statistics.mean(p), 'p_sd': statistics.stdev(p),
        }
    return ref


def log_gauss(x, mean, sd):
    sd = max(sd, 1e-9)
    return -math.log(sd) - 0.5 * ((x - mean) / sd) ** 2


def score(features, ref):
    diff = 0.0
    for name, s in ref.items():
        x = features[name]
        diff += log_gauss(x, s['p_mean'], s['p_sd'])
        diff -= log_gauss(x, s['h_mean'], s['h_sd'])
    diff = max(min(diff, 50), -50)  # avoid overflow
    prob = 1 / (1 + math.exp(-diff))

    cutoffs = [0.1, 0.3, 0.5, 0.7, 0.9]
    level = sum(prob >= c for c in cutoffs)
    return level, prob