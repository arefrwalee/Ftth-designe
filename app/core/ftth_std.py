# -*- coding: utf-8 -*-
"""Standards loader: standards/<name>.json deep-merged with the study's `overrides`.
All modules read the shared dict STD (updated in place by load())."""
import json, os, copy

STD = {}
LAY = {}      # layer names
LBL = {}      # BOQ row labels

def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict): _merge(a[k], v)
        else: a[k] = v
    return a

def load(study_cfg, package_dir):
    """package_dir = folder holding core/ and standards/. Returns STD."""
    name = study_cfg.get('standards', 'aerial_default')
    path = name if os.path.isabs(name) else os.path.join(package_dir, 'standards', name if name.endswith('.json') else name + '.json')
    base = json.load(open(path, encoding='utf-8'))
    merged = _merge(copy.deepcopy(base), study_cfg.get('overrides', {}))
    STD.clear(); STD.update(merged)
    LAY.clear(); LAY.update(STD['layers'])
    LBL.clear(); LBL.update(STD['boq_labels'])
    return STD
