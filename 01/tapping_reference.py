"""Compare finger-tapping features with the Kasemsap et al. 2025 reference
(47 healthy, 53 Parkinson's; tapping_reference.json, built by
tools/build_tapping_reference.py from the CC BY 4.0 figshare data).

- hand_comparison(): one hand's features next to the healthy and Parkinson's averages.
- combined_score(): the two-hand score (worse hand per feature, logistic regression,
  leave-one-person-out AUC stored in the JSON). Tap counts are shown, never scored.
"""
import json
import math
from pathlib import Path

REF = json.loads((Path(__file__).parent / 'tapping_reference.json').read_text())

# feature key in our results -> display info
FEATURES = [
    ('mean', 'Opening size', '%', 'Average tap opening, as % of your widest', True),
    ('std', 'Opening variability', '%', 'How much tap size varied (SD, % of widest)', True),
    ('diff10', 'Shrinkage, tap 1 to 10', 'pts', 'Tap 1 size minus tap 10 size; + means taps got smaller', True),
    ('count', 'Taps in 10 s', '', 'Shown for context, not scored: depends on age and setup', False),
]


def hand_comparison(hand, kas):
    prefix = 'rp_' if hand == 'right' else 'lp_'
    out = []
    for key, label, unit, help_text, scored in FEATURES:
        ref = REF['features'][prefix + key]
        out.append({'key': key, 'label': label, 'unit': unit, 'help': help_text, 'scored': scored,
                    'value': kas.get(key), 'healthy_mean': ref['hc_mean'], 'pd_mean': ref['pd_mean']})
    return out


def _worse_hand(right, left):
    pick = {'min': min, 'max': max}
    rows = []
    for name in REF['score']['inputs']:
        how = REF['score']['input_definitions'][name].split('(')[0]
        key = name.replace('worse_', '')
        r, l = right[key], left[key]
        v = pick[how](r, l)
        rows.append((name, key, v, 'right' if v == r else 'left'))
    return rows


def combined_score(right, left):
    """right/left: the 'kasemsap' feature dicts of each hand. Returns a dict, or raises
    ValueError with a user-facing reason."""
    for hand, k in (('right', right), ('left', left)):
        if not k:
            raise ValueError(f'No {hand}-hand measurement.')
        if any(k.get(f) is None for f in ('mean', 'std', 'diff10')):
            raise ValueError(f'The {hand} hand needs at least 10 detected taps for a score.')
    s = REF['score']
    rows = _worse_hand(right, left)
    z = [(v - m) / sd for (_, _, v, _), m, sd in zip(rows, s['mean'], s['sd'])]
    logit = s['intercept'] + sum(c * zi for c, zi in zip(s['coef'], z))
    prob = 1 / (1 + math.exp(-logit))
    tap_diff = REF['features']['tap_diff']
    return {
        'score': int(round(prob * 100)),
        'probability': round(prob, 3),
        'inputs': [{'key': key, 'value': round(v, 2), 'from_hand': hand,
                    'healthy_mean': REF['features'][('rp_' if hand == 'right' else 'lp_') + key]['hc_mean'],
                    'pd_mean': REF['features'][('rp_' if hand == 'right' else 'lp_') + key]['pd_mean']}
                   for _, key, v, hand in rows],
        'tap_difference': {'value': abs(right['count'] - left['count']),
                           'healthy_mean': tap_diff['hc_mean'], 'pd_mean': tap_diff['pd_mean'], 'scored': False},
        'validation': s['validation'],
        'reference': {'n_healthy': REF['source']['n_healthy'], 'n_parkinsons': REF['source']['n_parkinsons'],
                      'citation': REF['source']['citation']},
    }
