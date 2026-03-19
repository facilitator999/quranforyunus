#!/usr/bin/env python3
"""
Batch repair word-level timestamps for an entire surah using WhisperX.
Loads the Arabic alignment model ONCE and processes all verses sequentially —
much faster than running repair_timestamps.py once per verse.

Usage:
    python audio/repair_surah_batch.py --reciter maher --surah 2
    python audio/repair_surah_batch.py --reciter maher --surah 2 --start-verse 100
    python audio/repair_surah_batch.py --reciter maher --surah 2 --dry-run

If the run is interrupted, restart with --start-verse N to pick up where it left off.
Progress is saved to disk every 10 verses so a crash doesn't lose all work.
"""

import subprocess
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def ensure_dependencies():
    import os as _os
    import shutil as _shutil

    PACKAGES = {'whisperx': 'whisperx', 'scipy': 'scipy', 'torch': 'torch'}
    missing = []
    for name, pip_name in PACKAGES.items():
        try:
            __import__(name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print('=' * 55)
        print(f'  Missing packages: {", ".join(missing)}')
        print(f'  Installing via: {sys.executable} -m pip install ...')
        print('=' * 55)
        result = subprocess.run([sys.executable, '-m', 'pip', 'install'] + missing)
        if result.returncode != 0:
            print('\nERROR: pip install failed. Fix the error above then re-run.')
            sys.exit(1)
        print('\nAll packages installed. Continuing...\n')

    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _bundled = _os.path.join(_root, 'ffmpeg', 'ffmpeg.exe')
    if not _os.path.isfile(_bundled) and not _shutil.which('ffmpeg'):
        print('=' * 55)
        print('  ERROR: ffmpeg not found.')
        print(f'    1. Place ffmpeg.exe in: {_os.path.join(_root, "ffmpeg", "")}')
        print('    2. Or add ffmpeg to your system PATH')
        print('    Download: https://ffmpeg.org/download.html')
        print('=' * 55)
        sys.exit(1)


ensure_dependencies()

import argparse
import json
import os
import shutil
import tempfile

import numpy as np
import scipy.io.wavfile
import torch
import whisperx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)
PAGES_DIR  = os.path.join(ROOT_DIR, 'data', 'pages')
AUDIO_DIR  = os.path.join(ROOT_DIR, 'audio')

SAVE_EVERY = 10   # save JSON to disk after every N verses


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def clean_for_alignment(text):
    """Strip harakat and Quranic annotation marks so WhisperX counts tokens correctly."""
    out = []
    for c in text:
        cp = ord(c)
        if 0x064B <= cp <= 0x065F: continue  # harakat
        if cp == 0x0670:            continue  # alif khanjariya
        if 0x0610 <= cp <= 0x061A: continue  # Arabic extended marks
        if 0x06D6 <= cp <= 0x06DC: continue  # Quranic annotation signs
        if 0x06DF <= cp <= 0x06E4: continue  # more Quranic signs
        if 0x06E7 <= cp <= 0x06E8: continue  # small high Quran signs
        if 0x06EA <= cp <= 0x06ED: continue  # Arabic symbols
        out.append(c)
    return ''.join(out).strip()


def find_all_verse_words(surah):
    """Scan data/pages/ and return {verse_key: [word_dicts]} for every verse in surah."""
    result = {}
    prefix = f'{surah}:'
    for fname in sorted(os.listdir(PAGES_DIR), key=lambda n: int(n.split('.')[0])):
        if not fname.endswith('.json'):
            continue
        with open(os.path.join(PAGES_DIR, fname), encoding='utf-8-sig') as f:
            page = json.load(f)
        for v in page.get('verses', []):
            if v['verse_key'].startswith(prefix):
                words = [w for w in v['words'] if w['char_type_name'] == 'word']
                result[v['verse_key']] = words
    return result


def find_ffmpeg():
    for candidate in [
        os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg.exe'),
        os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg'),
        'ffmpeg',
    ]:
        if os.path.isfile(candidate):
            return candidate
        if candidate == 'ffmpeg' and shutil.which('ffmpeg'):
            return 'ffmpeg'
    print('ERROR: ffmpeg not found. Put it in {ROOT_DIR}/ffmpeg/ or add to PATH.')
    sys.exit(1)


def extract_wav(ffmpeg, mp3_path, start_ms, end_ms, out_wav, buffer_ms=300):
    clip_start_ms = max(0, start_ms - buffer_ms)
    duration_sec  = (end_ms + buffer_ms - clip_start_ms) / 1000.0
    subprocess.run([
        ffmpeg, '-y',
        '-ss', str(clip_start_ms / 1000.0),
        '-t',  str(duration_sec),
        '-i',  mp3_path,
        '-ar', '16000', '-ac', '1', '-f', 'wav', out_wav,
    ], check=True, capture_output=True)
    return clip_start_ms


def align_verse(wav_path, words, clip_start_ms, model_a, metadata, device):
    """Run WhisperX forced alignment on one verse. Returns (new_segments, n_aligned)."""
    sample_rate, wav_data = scipy.io.wavfile.read(wav_path)
    if wav_data.dtype == np.int16:
        audio = wav_data.astype(np.float32) / 32768.0
    elif wav_data.dtype == np.int32:
        audio = wav_data.astype(np.float32) / 2147483648.0
    else:
        audio = wav_data.astype(np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    duration = len(audio) / 16000.0

    verse_text = ' '.join(clean_for_alignment(w['text_uthmani']) for w in words)
    transcript = [{'text': verse_text, 'start': 0.0, 'end': duration}]
    result = whisperx.align(transcript, model_a, metadata, audio, device,
                            return_char_alignments=False)
    aligned = result.get('word_segments', [])

    new_segments = []
    for i, aw in enumerate(aligned):
        if i >= len(words):
            break
        pos   = words[i]['position']
        w_s   = int(aw.get('start', 0) * 1000 + clip_start_ms)
        w_e   = int(aw.get('end',   0) * 1000 + clip_start_ms)
        new_segments.append([pos, float(w_s), float(w_e)])

    return new_segments, len(aligned)


def save_json(ts_data, ts_path):
    with open(ts_path, 'w', encoding='utf-8') as f:
        json.dump(ts_data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='Batch repair surah timestamps with WhisperX forced alignment'
    )
    ap.add_argument('--reciter',     required=True,
                    help='Reciter folder name (e.g. maher, minshawi)')
    ap.add_argument('--surah',       type=int, required=True,
                    help='Surah number 1-114')
    ap.add_argument('--start-verse', type=int, default=1,
                    help='Resume from this verse (skip earlier ones)')
    ap.add_argument('--dry-run',     action='store_true',
                    help='Print what would change without writing anything')
    args = ap.parse_args()

    ffmpeg   = find_ffmpeg()
    mp3_path = os.path.join(AUDIO_DIR, args.reciter, 'recitation', f'{args.surah}.mp3')
    ts_path  = os.path.join(AUDIO_DIR, args.reciter, 'timestamps', f'{args.surah}.json')

    if not os.path.exists(mp3_path):
        print(f'ERROR: MP3 not found: {mp3_path}'); sys.exit(1)
    if not os.path.exists(ts_path):
        print(f'ERROR: Timestamps not found: {ts_path}'); sys.exit(1)

    print(f'\n{"=" * 55}')
    print(f'  Batch repair — {args.reciter}  surah {args.surah}')
    if args.start_verse > 1:
        print(f'  Resuming from verse {args.start_verse}')
    if args.dry_run:
        print('  (DRY RUN — no files will be written)')
    print(f'{"=" * 55}\n')

    # 1 — Arabic word data
    print('[1/4] Loading Arabic word data from data/pages/...')
    verse_words = find_all_verse_words(args.surah)
    print(f'  {len(verse_words)} verses loaded.')

    # 2 — Timestamps
    print('[2/4] Loading existing timestamps...')
    with open(ts_path, encoding='utf-8') as f:
        ts_data = json.load(f)
    timestamps = ts_data['audio_file']['timestamps']
    total = sum(1 for t in timestamps if int(t['verse_key'].split(':')[1]) >= args.start_verse)
    print(f'  {len(timestamps)} verses in JSON, {total} to process.')

    if not args.dry_run:
        backup = ts_path + '.bak'
        shutil.copy2(ts_path, backup)
        print(f'  Backup written: {backup}')

    # 3 — Load WhisperX model once
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f'\n[3/4] Loading Arabic alignment model (device: {device})...')
    print('  (downloads ~1 GB on first run)')
    model_a, metadata = whisperx.load_align_model(language_code='ar', device=device)
    print('  Model ready.\n')

    # 4 — Process
    print(f'[4/4] Aligning {total} verses (saving every {SAVE_EVERY})...\n')
    done_count = 0
    changed    = 0
    failed     = []
    partial    = []
    deduped    = []

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, 'verse.wav')

        for ts_entry in timestamps:
            vk   = ts_entry['verse_key']
            vnum = int(vk.split(':')[1])
            if vnum < args.start_verse:
                continue

            words = verse_words.get(vk)
            if not words:
                print(f'  [{vk:>8}] SKIP — not found in data/pages/')
                continue

            start_ms  = ts_entry['timestamp_from']
            end_ms    = ts_entry['timestamp_to']
            expected  = len(words)
            orig_segs = ts_entry.get('segments', [])

            # Detect Tarteel duplicate-segment bug: more segments than words means
            # some word positions were exported twice, pushing trailing words out of
            # range and breaking post-pause timing. Fix by deduplicating (first-wins).
            dedup_segs = None
            if len(orig_segs) > expected:
                seen  = set()
                clean = []
                for seg in orig_segs:
                    wp = seg[0]
                    if wp not in seen:
                        seen.add(wp)
                        clean.append(seg)
                if len(clean) == expected:
                    dedup_segs = clean  # exact match — safe to use original timing

            try:
                if dedup_segs is not None:
                    # Use deduplicated original — preserves pause-aware timing
                    done_count += 1
                    pct = done_count / total * 100
                    print(f'  [{vk:>8}] {expected}/{expected} words  '
                          f'({pct:5.1f}%  {done_count}/{total}) [dedup-orig]')
                    deduped.append(vk)
                    if not args.dry_run:
                        ts_entry['segments'] = dedup_segs
                        changed += 1
                        if changed % SAVE_EVERY == 0:
                            save_json(ts_data, ts_path)
                            print(f'             └─ saved ({changed} verses so far)')
                else:
                    clip_start_ms = extract_wav(ffmpeg, mp3_path, start_ms, end_ms, wav_path)
                    new_segs, n_aligned = align_verse(
                        wav_path, words, clip_start_ms, model_a, metadata, device
                    )

                    if n_aligned < expected:
                        # Fill missing positions from original data
                        for i in range(n_aligned, expected):
                            if i < len(orig_segs):
                                new_segs.append(orig_segs[i])
                        partial.append(vk)
                        flag = ' ⚠ partial'
                    else:
                        flag = ''

                    done_count += 1
                    pct = done_count / total * 100
                    print(f'  [{vk:>8}] {n_aligned}/{expected} words  '
                          f'({pct:5.1f}%  {done_count}/{total}){flag}')

                    if not args.dry_run:
                        ts_entry['segments'] = new_segs
                        changed += 1
                        if changed % SAVE_EVERY == 0:
                            save_json(ts_data, ts_path)
                            print(f'             └─ saved ({changed} verses so far)')

            except Exception as e:
                print(f'  [{vk:>8}] ERROR: {e}')
                failed.append(vk)

    # Final save
    if not args.dry_run and changed:
        save_json(ts_data, ts_path)

    print(f'\n{"=" * 55}')
    print(f'  Done.  {changed} verses updated.')
    if deduped:
        print(f'  Dedup-orig ({len(deduped)} verses): Tarteel duplicate bug fixed,'
              f' original pause-aware timing restored.')
    if partial:
        print(f'  Partial alignments ({len(partial)}): {partial}')
    if failed:
        print(f'  Failures ({len(failed)}): {failed}')
        print(f'  Re-run with --start-verse to retry individual failures.')
    print(f'{"=" * 55}\n')


if __name__ == '__main__':
    main()
