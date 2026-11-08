"""Compare finger-tapping features with the Kasemsap et al. 2025 reference
(47 healthy, 53 Parkinson's; tapping_reference.json, built by
tools/build_tapping_reference.py from the CC BY 4.0 figshare data).

- hand_comparison(): one hand's features next to the healthy and Parkinson's averages.
- hand_score(): one hand's score, 0-100, from its speed (tap count), opening size,
  variability and shrinkage (logistic regression; leave-one-person-out AUC in the JSON).
- combined_score(): both hands; the person's result is the worse hand.
"""
import json
import math
from pathlib import Path

REF = json.loads((Path(__file__).parent / 'tapping_reference.json').read_text())

# feature key in our results -> display info
FEATURES = [
    ('count', 'Taps in 10 s', '', 'Speed: fewer taps means slower tapping', True),
    ('mean', 'Opening size', '%', 'Average tap opening, as % of your widest', True),
    ('std', 'Opening variability', '%', 'How much tap size varied (SD, % of widest)', True),
    ('diff10', 'Shrinkage, tap 1 to 10', 'pts', 'Tap 1 size minus tap 10 size; + means taps got smaller', True),
]
LABELS = {key: label for key, label, *_ in FEATURES}

BANDS = [  # (key, css class, label) — same wording as the spiral's result bands
    ('typical', 'band-low', 'Within typical range'),
    ('borderline', 'band-moderate', 'Borderline: consider a retest'),
    ('elevated', 'band-high', 'Elevated: consider a clinical review'),
]


def _prefix(hand):
    return 'rp_' if hand == 'right' else 'lp_'


def hand_comparison(hand, kas):
    out = []
    for key, label, unit, help_text, scored in FEATURES:
        ref = REF['features'][_prefix(hand) + key]
        out.append({'key': key, 'label': label, 'unit': unit, 'help': help_text, 'scored': scored,
                    'value': kas.get(key), 'healthy_mean': ref['hc_mean'], 'pd_mean': ref['pd_mean']})
    return out


def band_for(score):
    b = REF['score']['bands']
    key, cls, label = BANDS[0] if score < b['typical_below'] else (
        BANDS[1] if score < b['elevated_from'] else BANDS[2])
    return {'key': key, 'cls': cls, 'label': label}


def hand_score(hand, kas):
    """One hand's 0-100 score. Raises ValueError with a user-facing reason."""
    if not kas or not kas.get('count'):
        raise ValueError(f'No taps detected on the {hand} hand.')
    if any(kas.get(f) is None for f in REF['score']['inputs']):
        raise ValueError(f'The {hand}-hand measurement is incomplete. Record it again.')
    s = REF['score']
    z = [(kas[k] - m) / sd for k, m, sd in zip(s['inputs'], s['mean'], s['sd'])]
    logit = s['intercept'] + sum(c * zi for c, zi in zip(s['coef'], z))
    prob = 1 / (1 + math.exp(-logit))
    inputs = [{'key': k, 'label': LABELS[k], 'value': round(kas[k], 2),
               'healthy_mean': REF['features'][_prefix(hand) + k]['hc_mean'],
               'pd_mean': REF['features'][_prefix(hand) + k]['pd_mean'],
               'push': round(c * zi, 2)}            # + pushes toward the Parkinson's group
              for k, c, zi in zip(s['inputs'], s['coef'], z)]
    return {'score': int(round(prob * 100)), 'probability': round(prob, 3), 'inputs': inputs}


def combined_score(right, left):
    """right/left: the 'kasemsap' feature dicts of each hand. Returns a dict, or raises
    ValueError with a user-facing reason."""
    hands = {'right': hand_score('right', right), 'left': hand_score('left', left)}
    worse = max(hands, key=lambda h: hands[h]['score'])
    score = hands[worse]['score']
    tap_diff = REF['features']['tap_diff']
    return {
        'score': score,
        'probability': hands[worse]['probability'],
        'band': band_for(score),
        'worse_hand': worse,
        'hands': hands,
        'tap_difference': {'value': abs(right['count'] - left['count']),
                           'healthy_mean': tap_diff['hc_mean'], 'pd_mean': tap_diff['pd_mean'], 'scored': False},
        'validation': REF['score']['validation'],
        'bands': {k: v for k, v in REF['score']['bands'].items() if k in ('typical_below', 'elevated_from')},
        'reference': {'n_healthy': REF['source']['n_healthy'], 'n_parkinsons': REF['source']['n_parkinsons'],
                      'citation': REF['source']['citation']},
    }
