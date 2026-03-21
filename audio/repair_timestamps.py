#!/usr/bin/env python3
"""
Repair word-level timestamps for a specific verse using WhisperX forced alignment.

Takes the existing verse boundaries (timestamp_from / timestamp_to) as-is and
refines only the word-level segments[] array by running forced alignment against
the known Arabic text.

Usage:
    python repair_timestamps.py --reciter maher --surah 2 --verse 28
    python repair_timestamps.py --reciter minshawi --surah 1 --verse 3 --dry-run

Install requirements (once):
    pip install whisperx
    # whisperx will auto-download the Arabic wav2vec2 alignment model on first run

ffmpeg:
    The script looks for ../ffmpeg/ffmpeg.exe (bundled) then falls back to PATH.
"""

import os
import subprocess
import sys

# Windows terminals default to cp1252 which can't print Arabic
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def ensure_dependencies():
    """
    Check for all requirements upfront and install missing Python packages.
    Always uses sys.executable so the right Python's pip is called —
    avoids the 'pip points to Python 3.11 but python is 3.12' problem.
    """
    # --- Python packages ---
    PACKAGES = {
        'whisperx': 'whisperx',
        'scipy':    'scipy',
        'torch':    'torch',
    }

    missing_pip = []
    for import_name, pip_name in PACKAGES.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_pip.append(pip_name)

    if missing_pip:
        print("=" * 55)
        print(f"  Missing packages: {', '.join(missing_pip)}")
        print(f"  Installing via: {sys.executable} -m pip install ...")
        print("  (whisperx downloads ~1 GB of models on first alignment)")
        print("=" * 55)

        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install'] + missing_pip,
            capture_output=False,
        )

        if result.returncode != 0:
            print("\nERROR: pip install failed. Fix the error above then re-run.")
            sys.exit(1)

        print("\nAll packages installed. Continuing...\n")

    # --- ffmpeg ---
    import shutil as _shutil
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _bundled = os.path.join(_root, 'ffmpeg', 'ffmpeg.exe')
    _found = os.path.isfile(_bundled) or bool(_shutil.which('ffmpeg'))

    if not _found:
        print("=" * 55)
        print("  ERROR: ffmpeg not found.")
        print("  Either:")
        print(f"    1. Place ffmpeg.exe in:  {os.path.join(_root, 'ffmpeg', '')}")
        print("    2. Or add ffmpeg to your system PATH")
        print("  Download from: https://ffmpeg.org/download.html")
        print("=" * 55)
        sys.exit(1)


ensure_dependencies()

import argparse
import json
import os
import shutil
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)
PAGES_DIR  = os.path.join(ROOT_DIR, 'data', 'pages')
AUDIO_DIR  = os.path.join(ROOT_DIR, 'audio')


def clean_for_alignment(text):
    """
    Strip harakat and Quranic annotation marks so WhisperX sees clean consonants.
    Critically: removes embedded pause signs (ۖ ۗ ۘ etc.) that sit inside word
    text separated by spaces and would cause WhisperX to count extra tokens.
    """
    out = []
    for c in text:
        cp = ord(c)
        if 0x064B <= cp <= 0x065F: continue  # harakat (tanwin, vowels, shadda…)
        if cp == 0x0670:            continue  # alif khanjariya
        if 0x0610 <= cp <= 0x061A: continue  # Arabic extended marks
        if 0x06D6 <= cp <= 0x06E4: continue  # Quranic annotation signs (incl. ۝۞)
        if 0x06E7 <= cp <= 0x06E8: continue  # small high Quran signs
        if 0x06EA <= cp <= 0x06ED: continue  # Arabic symbols
        out.append(c)
    return ''.join(out).strip()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def find_ffmpeg():
    for candidate in [
        os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg.exe'),
        os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg'),
        'ffmpeg',
    ]:
        if os.path.isfile(candidate):
            return candidate
        if candidate == 'ffmpeg':
            if shutil.which('ffmpeg'):
                return 'ffmpeg'
    print("ERROR: ffmpeg not found. Put it in ../ffmpeg/ or add to PATH.")
    sys.exit(1)


def find_verse_words(surah, verse):
    """Scan page JSONs and return the list of Arabic word dicts for the verse."""
    verse_key = f"{surah}:{verse}"
    for fname in sorted(os.listdir(PAGES_DIR), key=lambda n: int(n.split('.')[0])):
        if not fname.endswith('.json'):
            continue
        with open(os.path.join(PAGES_DIR, fname), encoding='utf-8-sig') as f:
            page = json.load(f)
        for v in page.get('verses', []):
            if v['verse_key'] == verse_key:
                # exclude end-of-verse markers (the ١ ٢ … symbols)
                return [w for w in v['words'] if w['char_type_name'] == 'word']
    return None


def load_surah_timestamps(reciter, surah):
    path = os.path.join(AUDIO_DIR, reciter, 'timestamps', f'{surah}.json')
    if not os.path.exists(path):
        print(f"ERROR: timestamp file not found: {path}")
        sys.exit(1)
    with open(path, encoding='utf-8') as f:
        return json.load(f), path


def extract_wav(ffmpeg, mp3_path, start_ms, end_ms, out_wav, buffer_ms=300):
    """
    Cut the verse audio (plus a small buffer) from the surah MP3 as 16 kHz mono WAV.
    Returns the actual start offset (in ms) of the extracted clip within the MP3.
    """
    clip_start_ms = max(0, start_ms - buffer_ms)
    clip_end_ms   = end_ms + buffer_ms
    duration_sec  = (clip_end_ms - clip_start_ms) / 1000.0

    subprocess.run(
        [
            ffmpeg, '-y',
            '-ss', str(clip_start_ms / 1000.0),
            '-t',  str(duration_sec),
            '-i',  mp3_path,
            '-ar', '16000', '-ac', '1', '-f', 'wav',
            out_wav,
        ],
        check=True,
        capture_output=True,
    )
    return clip_start_ms  # offset to add when converting back to MP3 time


def run_alignment(wav_path, words, clip_start_ms):
    """
    Run WhisperX forced alignment.
    Returns (new_segments, n_aligned) where new_segments is a list of
    [word_position, start_ms, end_ms] in original MP3 coordinates.
    """
    import whisperx          # imported here so the rest of the script works without it
    import torch
    import numpy as np
    import scipy.io.wavfile  # read WAV without needing ffmpeg again

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"  device        : {device}")

    # Read the WAV ourselves (avoids whisperx needing ffmpeg a second time)
    sample_rate, wav_data = scipy.io.wavfile.read(wav_path)
    if wav_data.dtype == np.int16:
        audio = wav_data.astype(np.float32) / 32768.0
    elif wav_data.dtype == np.int32:
        audio = wav_data.astype(np.float32) / 2147483648.0
    else:
        audio = wav_data.astype(np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # stereo → mono
    duration = len(audio) / 16000.0

    print("  loading Arabic alignment model (downloads once on first run)…")
    model_a, metadata = whisperx.load_align_model(language_code='ar', device=device)

    verse_text = ' '.join(clean_for_alignment(w['text_uthmani']) for w in words)
    print(f"  aligning text : {verse_text}")

    transcript = [{'text': verse_text, 'start': 0.0, 'end': duration}]
    result     = whisperx.align(transcript, model_a, metadata, audio, device,
                                return_char_alignments=False)

    aligned = result.get('word_segments', [])
    print(f"  aligned words : {len(aligned)}  (expected {len(words)})")

    new_segments = []
    for i, aw in enumerate(aligned):
        if i >= len(words):
            break
        pos     = words[i]['position']
        w_start = int(aw.get('start', 0) * 1000 + clip_start_ms)
        w_end   = int(aw.get('end',   0) * 1000 + clip_start_ms)
        new_segments.append([pos, float(w_start), float(w_end)])

    return new_segments, len(aligned)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description='Repair word-level Quran timestamps using WhisperX forced alignment'
    )
    ap.add_argument('--reciter', required=True,
                    help='Reciter folder name (e.g. maher, minshawi, alafasy)')
    ap.add_argument('--surah',   type=int, required=True, help='Surah number 1-114')
    ap.add_argument('--verse',   type=int, required=True, help='Verse number')
    ap.add_argument('--dry-run', action='store_true',
                    help='Print what would change without writing anything')
    args = ap.parse_args()

    verse_key = f"{args.surah}:{args.verse}"
    ffmpeg    = find_ffmpeg()

    print(f"\n{'='*55}")
    print(f"  Timestamp repair — {args.reciter}  {verse_key}")
    if args.dry_run:
        print("  (DRY RUN — no files will be written)")
    print(f"{'='*55}\n")

    # 1 — Arabic word text
    print("[1/5] Looking up Arabic verse text…")
    words = find_verse_words(args.surah, args.verse)
    if not words:
        print(f"ERROR: {verse_key} not found in data/pages/")
        sys.exit(1)
    print(f"  {len(words)} words: {' '.join(w['text_uthmani'] for w in words)}")

    # 2 — Existing timestamp entry
    print("\n[2/5] Loading existing timestamps…")
    ts_data, ts_path = load_surah_timestamps(args.reciter, args.surah)
    ts_entry = next(
        (t for t in ts_data['audio_file']['timestamps'] if t['verse_key'] == verse_key),
        None,
    )
    if ts_entry is None:
        print(f"ERROR: {verse_key} not found in {ts_path}")
        sys.exit(1)

    start_ms = ts_entry['timestamp_from']
    end_ms   = ts_entry['timestamp_to']
    print(f"  verse range   : {start_ms} ms – {end_ms} ms  ({end_ms - start_ms} ms)")
    print(f"  old segments  : {ts_entry['segments']}")

    # 3 — MP3 check
    mp3_path = os.path.join(AUDIO_DIR, args.reciter, 'recitation', f'{args.surah}.mp3')
    if not os.path.exists(mp3_path):
        print(f"\nERROR: MP3 not found: {mp3_path}")
        sys.exit(1)

    # 4 — Extract audio + align
    print("\n[3/5] Extracting verse audio segment…")
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, 'verse.wav')
        clip_start_ms = extract_wav(ffmpeg, mp3_path, start_ms, end_ms, wav_path)
        print(f"  clip offset   : {clip_start_ms} ms into MP3")

        print("\n[4/5] Running WhisperX forced alignment…")
        new_segments, n_aligned = run_alignment(wav_path, words, clip_start_ms)

    # 5 — Show diff
    print("\n[5/5] Result:")
    print(f"  old segments  : {ts_entry['segments']}")
    print(f"  new segments  : {new_segments}")

    if n_aligned < len(words):
        print(f"\n  WARNING: only {n_aligned} of {len(words)} words were aligned.")
        print("  The remaining words keep their old timestamps.")
        # fill missing words with original data
        for i in range(n_aligned, len(words)):
            if i < len(ts_entry['segments']):
                new_segments.append(ts_entry['segments'][i])
            # if no old segment exists for this position, skip

    if args.dry_run:
        print("\n  (DRY RUN) No changes written.")
        return

    # backup + save
    backup = ts_path + '.bak'
    shutil.copy2(ts_path, backup)
    print(f"\n  Backup written : {backup}")

    ts_entry['segments'] = new_segments

    with open(ts_path, 'w', encoding='utf-8') as f:
        json.dump(ts_data, f, ensure_ascii=False, indent=2)

    print(f"  Saved          : {ts_path}")
    print("\nDone.\n")


if __name__ == '__main__':
    main()
