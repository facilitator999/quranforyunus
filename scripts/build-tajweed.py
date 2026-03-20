#!/usr/bin/env python3
"""
Pre-processor: converts the full cpfair tajweed JSON into a compact index.
Input:  scripts/tajweed.hafs.uthmani-pause-sajdah.json
Output: data/tajweed-index.json

Rules kept (matches the color scheme used in the app):
  silent, madd_2, madd_246, madd_muttasil, madd_6,
  ghunnah, ikhfa, ikhfa_shafawi, qalqalah, lam_shamsiyyah

Output shape:
{
  "1:1": [
    { "rule": "madd_2", "start": 24, "end": 25 },
    ...
  ],
  ...
}
Ayahs with zero matching annotations are omitted.
"""

import json, os, sys

KEEP_RULES = {
    'silent', 'madd_2', 'madd_246', 'madd_muttasil', 'madd_6',
    'ghunnah', 'ikhfa', 'ikhfa_shafawi', 'qalqalah', 'lam_shamsiyyah',
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)

src  = os.path.join(SCRIPT_DIR, 'tajweed.hafs.uthmani-pause-sajdah.json')
dest = os.path.join(ROOT_DIR, 'data', 'tajweed-index.json')

print(f'Reading {src} ...')
with open(src, encoding='utf-8') as f:
    data = json.load(f)

index = {}
for entry in data:
    surah = entry['surah']
    ayah  = entry['ayah']
    key   = f'{surah}:{ayah}'
    anns  = [
        {'rule': a['rule'], 'start': a['start'], 'end': a['end']}
        for a in entry.get('annotations', [])
        if a['rule'] in KEEP_RULES
    ]
    if anns:
        index[key] = anns

print(f'  {len(index)} ayahs with matching annotations (out of {len(data)} total)')
print(f'Writing {dest} ...')
with open(dest, 'w', encoding='utf-8') as f:
    json.dump(index, f, ensure_ascii=False, separators=(',', ':'))

size_kb = os.path.getsize(dest) / 1024
print(f'  Done — {size_kb:.1f} KB')
