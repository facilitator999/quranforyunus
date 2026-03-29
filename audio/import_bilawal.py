#!/usr/bin/env python3
"""
Import word-level timestamps from quranzen.com (Bilawal's WhisperX data)
and map them to our full-surah MP3 files using ffmpeg silence detection
for verse boundaries.

Usage:
    python audio/import_bilawal.py --reciter alafasy
    python audio/import_bilawal.py --reciter alafasy --surah 111
    python audio/import_bilawal.py --reciter alafasy --start 1 --end 114
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

EDITION_MAP = {
    'alafasy': 'alafasy',
    'minshawi': 'ar.minshawi',
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
FFMPEG = os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg.exe')
if not os.path.exists(FFMPEG):
    FFMPEG = 'ffmpeg'

AYAH_COUNTS = [
    7,286,200,176,120,165,206,75,129,109,123,111,43,52,99,128,111,
    110,98,135,112,78,118,64,77,227,93,88,69,60,34,30,73,54,45,83,
    182,88,75,85,54,53,89,59,37,35,38,88,52,45,60,49,62,55,78,96,
    29,22,24,13,14,11,11,18,12,12,30,52,52,44,28,28,20,56,40,31,
    50,40,46,42,29,19,36,25,22,17,19,26,30,20,15,21,11,8,8,19,5,
    8,8,11,11,8,3,9,5,4,7,3,6,3,5,4,5,6
]


def fetch_bilawal_segments(surah, ayah, edition):
    url = (f'https://quranzen.com/api/quran/audio-segments'
           f'/{surah}/{ayah}?edition={edition}')
    req = urllib.request.Request(url, headers={'User-Agent': 'QuranKids/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    return data.get('segments', [])


def detect_silences(mp3_path, noise_db=-30, min_dur=0.1):
    proc = subprocess.run([
        FFMPEG, '-y', '-i', mp3_path,
        '-af', f'silencedetect=noise={noise_db}dB:d={min_dur}',
        '-f', 'null', '-',
    ], capture_output=True, timeout=120)
    stderr = proc.stderr.decode('utf-8', errors='replace')

    silences = []
    current_start = None
    for line in stderr.split('\n'):
        if 'silence_start:' in line:
            try:
                val = float(line.split('silence_start:')[1].strip().split()[0])
                current_start = int(val * 1000)
            except (ValueError, IndexError):
                pass
        elif 'silence_end:' in line and current_start is not None:
            try:
                val = float(line.split('silence_end:')[1].strip().split()[0])
                current_end = int(val * 1000)
                silences.append((current_start, current_end))
                current_start = None
            except (ValueError, IndexError):
                pass
    return silences


def process_surah(reciter, edition, surah):
    mp3_path = os.path.join(ROOT_DIR, 'audio', reciter, 'recitation', f'{surah}.mp3')
    ts_path = os.path.join(ROOT_DIR, 'audio', reciter, 'timestamps', f'{surah}.json')

    if not os.path.exists(mp3_path):
        print(f'  [{surah:>3}] SKIP - no MP3')
        return False

    n_ayahs = AYAH_COUNTS[surah - 1]

    # Detect silences
    silences = detect_silences(mp3_path)

    if len(silences) < n_ayahs - 1:
        # Try lower threshold
        silences = detect_silences(mp3_path, noise_db=-25, min_dur=0.08)
        if len(silences) < n_ayahs - 1:
            print(f'  [{surah:>3}] WARN - {len(silences)} silences for {n_ayahs} ayahs, trying -20dB')
            silences = detect_silences(mp3_path, noise_db=-20, min_dur=0.05)
            if len(silences) < n_ayahs - 1:
                print(f'  [{surah:>3}] SKIP - only {len(silences)} silences for {n_ayahs} ayahs')
                return False

    # If more silences than ayahs, pick the largest ones as verse boundaries
    if len(silences) > n_ayahs:
        by_dur = sorted(silences, key=lambda s: s[1] - s[0], reverse=True)
        top = sorted(by_dur[:n_ayahs], key=lambda s: s[0])
        silences = top

    # Build verse boundaries
    verse_starts = [0]
    for i in range(min(n_ayahs - 1, len(silences))):
        verse_starts.append(silences[i][1])

    # verse_to for each ayah
    verse_tos = []
    for i in range(n_ayahs):
        if i < len(silences):
            verse_tos.append(silences[i][1])
        elif silences:
            verse_tos.append(silences[-1][1])
        else:
            verse_tos.append(verse_starts[i] + 10000)

    # Fetch and map
    timestamps = []
    errors = []
    for ayah in range(1, n_ayahs + 1):
        ayah_idx = ayah - 1
        try:
            segs = fetch_bilawal_segments(surah, ayah, edition)
        except Exception as e:
            errors.append(f'{surah}:{ayah}: {e}')
            continue

        if not segs:
            errors.append(f'{surah}:{ayah}: no segments')
            continue

        vs = verse_starts[ayah_idx] if ayah_idx < len(verse_starts) else verse_starts[-1]
        vt = verse_tos[ayah_idx] if ayah_idx < len(verse_tos) else verse_tos[-1]

        offset = vs - segs[0][1]

        mapped_segs = []
        for s in segs:
            mapped_segs.append([s[0], float(s[1] + offset), float(s[2] + offset)])

        timestamps.append({
            'verse_key': f'{surah}:{ayah}',
            'timestamp_from': vs,
            'timestamp_to': vt,
            'duration': vt - vs,
            'segments': mapped_segs,
        })

        time.sleep(0.05)

    if errors:
        for e in errors:
            print(f'  [{surah:>3}] ERROR: {e}')

    if len(timestamps) != n_ayahs:
        print(f'  [{surah:>3}] SKIP - got {len(timestamps)}/{n_ayahs} verses')
        return False

    out = {
        'audio_file': {
            'id': 0,
            'chapter_id': surah,
            'audio_url': f'audio/{reciter}/recitation/{surah}.mp3',
            'timestamps': timestamps,
        }
    }

    with open(ts_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f'  [{surah:>3}] OK - {n_ayahs} verses')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reciter', required=True)
    parser.add_argument('--surah', type=int)
    parser.add_argument('--start', type=int, default=1)
    parser.add_argument('--end', type=int, default=114)
    args = parser.parse_args()

    edition = EDITION_MAP.get(args.reciter)
    if not edition:
        print(f'Unknown reciter: {args.reciter}')
        print(f'Available: {list(EDITION_MAP.keys())}')
        sys.exit(1)

    if args.surah:
        surahs = [args.surah]
    else:
        surahs = list(range(args.start, args.end + 1))

    print(f'Importing Bilawal timestamps for {args.reciter} ({edition})')
    print(f'Surahs: {surahs[0]}-{surahs[-1]} ({len(surahs)} total)\n')

    ok = 0
    fail = 0
    for surah in surahs:
        if process_surah(args.reciter, edition, surah):
            ok += 1
        else:
            fail += 1

    print(f'\nDone. {ok} OK, {fail} failed.')


if __name__ == '__main__':
    main()
