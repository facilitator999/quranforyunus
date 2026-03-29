#!/usr/bin/env python3
"""
Fix word-level timestamps using Bilawal verse boundaries + WhisperX word alignment.

Pipeline per surah:
1. Import verse boundaries from Bilawal (quranzen.com)
2. WhisperX full-verse alignment for internal word boundaries
3. WhisperX single-word alignment for last word's end

Usage:
    python audio/fix_timestamps.py --reciter alafasy --surah 109
    python audio/fix_timestamps.py --reciter alafasy --start 109 --end 114
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import numpy as np
import scipy.io.wavfile
import torch
import whisperx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
PAGES_DIR = os.path.join(ROOT_DIR, 'data', 'pages')

EDITION_MAP = {
    'alafasy': 'alafasy',
    'minshawi': 'ar.minshawi',
}

# Reciters that already have good verse boundaries — skip Bilawal import
SKIP_BILAWAL = {'maher', 'minshawi'}

AYAH_COUNTS = [
    7,286,200,176,120,165,206,75,129,109,123,111,43,52,99,128,111,
    110,98,135,112,78,118,64,77,227,93,88,69,60,34,30,73,54,45,83,
    182,88,75,85,54,53,89,59,37,35,38,88,52,45,60,49,62,55,78,96,
    29,22,24,13,14,11,11,18,12,12,30,52,52,44,28,28,20,56,40,31,
    50,40,46,42,29,19,36,25,22,17,19,26,30,20,15,21,11,8,8,19,5,
    8,8,11,11,8,3,9,5,4,7,3,6,3,5,4,5,6
]


def find_ffmpeg():
    candidates = []
    if sys.platform == 'win32':
        candidates.append(os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg.exe'))
    candidates.append(os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg'))
    for c in candidates:
        if os.path.isfile(c):
            return c
    if shutil.which('ffmpeg'):
        return 'ffmpeg'
    print('ERROR: ffmpeg not found')
    sys.exit(1)


def clean_for_alignment(text):
    out = []
    for c in text:
        cp = ord(c)
        if 0x064B <= cp <= 0x065F: continue
        if cp == 0x0670: continue
        if 0x0610 <= cp <= 0x061A: continue
        if 0x06D6 <= cp <= 0x06E4: continue
        if 0x06E7 <= cp <= 0x06E8: continue
        if 0x06EA <= cp <= 0x06ED: continue
        out.append(c)
    return ''.join(out).strip()


def find_all_verse_words(surah):
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


def extract_wav(ffmpeg, mp3_path, start_ms, end_ms, out_wav):
    start_sec = max(0, start_ms) / 1000.0
    dur_sec = (end_ms - max(0, start_ms)) / 1000.0
    subprocess.run([
        ffmpeg, '-y',
        '-ss', str(start_sec),
        '-t', str(dur_sec),
        '-i', mp3_path,
        '-ar', '16000', '-ac', '1', '-f', 'wav', out_wav,
    ], capture_output=True, timeout=30)


# ---------------------------------------------------------------------------
# Step 1: Bilawal import (verse boundaries + initial word positions)
# ---------------------------------------------------------------------------

def fetch_bilawal_segments(surah, ayah, edition):
    url = (f'https://quranzen.com/api/quran/audio-segments'
           f'/{surah}/{ayah}?edition={edition}')
    req = urllib.request.Request(url, headers={'User-Agent': 'QuranKids/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    return data.get('segments', [])


def detect_silences(mp3_path, ffmpeg, noise_db=-30, min_dur=0.1):
    proc = subprocess.run([
        ffmpeg, '-y', '-i', mp3_path,
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


def import_bilawal(reciter, edition, surah, ffmpeg, mp3_path):
    """Returns timestamp data from Bilawal, or None on failure."""
    n_ayahs = AYAH_COUNTS[surah - 1]

    silences = detect_silences(mp3_path, ffmpeg)
    if len(silences) < n_ayahs - 1:
        silences = detect_silences(mp3_path, ffmpeg, noise_db=-25, min_dur=0.08)
        if len(silences) < n_ayahs - 1:
            silences = detect_silences(mp3_path, ffmpeg, noise_db=-20, min_dur=0.05)
            if len(silences) < n_ayahs - 1:
                print(f'  [{surah:>3}] SKIP bilawal - only {len(silences)} silences for {n_ayahs} ayahs')
                return None

    if len(silences) > n_ayahs:
        by_dur = sorted(silences, key=lambda s: s[1] - s[0], reverse=True)
        top = sorted(by_dur[:n_ayahs], key=lambda s: s[0])
        silences = top

    verse_starts = [0]
    for i in range(min(n_ayahs - 1, len(silences))):
        verse_starts.append(silences[i][1])

    verse_tos = []
    for i in range(n_ayahs):
        if i < len(silences):
            verse_tos.append(silences[i][1])
        elif silences:
            verse_tos.append(silences[-1][1])
        else:
            verse_tos.append(verse_starts[i] + 10000)

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
            print(f'  [{surah:>3}] bilawal error: {e}')

    if len(timestamps) != n_ayahs:
        print(f'  [{surah:>3}] SKIP bilawal - got {len(timestamps)}/{n_ayahs} verses')
        return None

    return {
        'audio_file': {
            'id': 0,
            'chapter_id': surah,
            'audio_url': f'audio/{reciter}/recitation/{surah}.mp3',
            'timestamps': timestamps,
        }
    }


# ---------------------------------------------------------------------------
# Step 2: WhisperX full-verse alignment (fix internal word boundaries)
# ---------------------------------------------------------------------------

def align_verse_words(ffmpeg, mp3_path, verse, words, model_a, metadata, device):
    """Re-align all words in a verse. Returns new segments, preserving last word end."""
    segs = verse['segments']
    vs = verse['timestamp_from']
    vt = verse['timestamp_to']

    tmp_wav = os.path.join(tempfile.gettempdir(), f'align_{verse["verse_key"].replace(":", "_")}.wav')
    extract_wav(ffmpeg, mp3_path, vs, vt, tmp_wav)

    try:
        sample_rate, wav_data = scipy.io.wavfile.read(tmp_wav)
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

        if len(aligned) != len(words):
            return None

        new_segs = []
        for i, aw in enumerate(aligned):
            pos = words[i]['position']
            w_s = int(aw.get('start', 0) * 1000 + vs)
            w_e = int(aw.get('end', 0) * 1000 + vs)
            new_segs.append([pos, float(w_s), float(w_e)])

        # Reject if WhisperX crushed any word below 150ms
        for seg in new_segs:
            if seg[2] - seg[1] < 150:
                return None

        return new_segs
    except Exception:
        return None
    finally:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)


# ---------------------------------------------------------------------------
# Step 3: WhisperX single-word alignment (fix last word's end)
# ---------------------------------------------------------------------------

def fix_last_word(ffmpeg, mp3_path, verse, vi, timestamps, words, model_a, metadata, device):
    """Re-align last word individually to find its true end. Returns True if fixed."""
    segs = verse['segments']
    if not segs or not words:
        return False

    last_seg = segs[-1]
    last_word_text = words[-1].get('text_uthmani', '') if len(words) >= len(segs) else None
    if not last_word_text:
        return False

    cur_start = last_seg[1]
    cur_end = last_seg[2]
    vt = verse['timestamp_to']

    if vi + 1 < len(timestamps):
        next_segs = timestamps[vi + 1]['segments']
        hard_limit = next_segs[0][1] if next_segs else vt
    else:
        hard_limit = vt

    if hard_limit - cur_end < 50:
        return False

    clip_start = int(cur_start)
    clip_end = int(vt + 300)
    tmp_wav = os.path.join(tempfile.gettempdir(), f'lastw_{verse["verse_key"].replace(":", "_")}.wav')
    extract_wav(ffmpeg, mp3_path, clip_start, clip_end, tmp_wav)

    try:
        sample_rate, wav_data = scipy.io.wavfile.read(tmp_wav)
        if wav_data.dtype == np.int16:
            audio = wav_data.astype(np.float32) / 32768.0
        elif wav_data.dtype == np.int32:
            audio = wav_data.astype(np.float32) / 2147483648.0
        else:
            audio = wav_data.astype(np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        duration = len(audio) / 16000.0

        cleaned = clean_for_alignment(last_word_text)
        transcript = [{'text': cleaned, 'start': 0.0, 'end': duration}]
        result = whisperx.align(transcript, model_a, metadata, audio, device,
                                return_char_alignments=False)
        aligned = result.get('word_segments', [])
        if not aligned:
            return False

        w = aligned[0]
        new_end = int(w.get('end', 0) * 1000 + clip_start)
        new_end = min(new_end, hard_limit)

        if new_end > cur_end + 30:
            last_seg[2] = float(new_end)
            return True
    except Exception:
        pass
    finally:
        if os.path.exists(tmp_wav):
            os.remove(tmp_wav)

    # Fallback: WhisperX didn't extend — stretch last word to next verse's first word start
    last_seg[2] = float(hard_limit)
    return True


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process_surah(reciter, edition, surah, ffmpeg, model_a, metadata, device):
    mp3_path = os.path.join(ROOT_DIR, 'audio', reciter, 'recitation', f'{surah}.mp3')
    ts_path = os.path.join(ROOT_DIR, 'audio', reciter, 'timestamps', f'{surah}.json')

    if not os.path.exists(mp3_path):
        print(f'  [{surah:>3}] SKIP - no MP3')
        return False

    if reciter in SKIP_BILAWAL:
        # Use existing timestamps — just fix word boundaries
        if not os.path.exists(ts_path):
            print(f'  [{surah:>3}] SKIP - no timestamps')
            return False
        print(f'  [{surah:>3}] Step 1: using existing verse boundaries...')
        with open(ts_path, encoding='utf-8') as f:
            data = json.load(f)
    else:
        # Step 1: Bilawal
        print(f'  [{surah:>3}] Step 1: importing Bilawal verse boundaries...')
        data = import_bilawal(reciter, edition, surah, ffmpeg, mp3_path)
        if not data:
            return False

    verse_words = find_all_verse_words(surah)
    timestamps = data['audio_file']['timestamps']

    # Step 2: WhisperX full-verse alignment
    print(f'  [{surah:>3}] Step 2: WhisperX word alignment...')
    aligned_count = 0
    for verse in timestamps:
        vk = verse['verse_key']
        words = verse_words.get(vk)
        if not words:
            continue

        new_segs = align_verse_words(ffmpeg, mp3_path, verse, words, model_a, metadata, device)
        if new_segs:
            verse['segments'] = new_segs
            aligned_count += 1

    # Step 3: WhisperX last-word fix
    print(f'  [{surah:>3}] Step 3: fixing last words...')
    last_fixed = 0
    for vi, verse in enumerate(timestamps):
        vk = verse['verse_key']
        words = verse_words.get(vk)
        if not words:
            continue
        old_end = verse['segments'][-1][2] if verse['segments'] else 0
        if fix_last_word(ffmpeg, mp3_path, verse, vi, timestamps, words, model_a, metadata, device):
            new_end = verse['segments'][-1][2]
            print(f'    {vk} last word: {old_end:.0f} -> {new_end:.0f}')
            last_fixed += 1

    # Save
    with open(ts_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    n_ayahs = AYAH_COUNTS[surah - 1]
    print(f'  [{surah:>3}] OK - {n_ayahs} verses, {aligned_count} word-aligned, {last_fixed} last words fixed')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reciter', required=True)
    parser.add_argument('--surah', type=int)
    parser.add_argument('--start', type=int, default=109)
    parser.add_argument('--end', type=int, default=114)
    args = parser.parse_args()

    edition = EDITION_MAP.get(args.reciter)
    if not edition and args.reciter not in SKIP_BILAWAL:
        print(f'Unknown reciter: {args.reciter}')
        sys.exit(1)

    ffmpeg = find_ffmpeg()

    if args.surah:
        surahs = [args.surah]
    else:
        surahs = list(range(args.start, args.end + 1))

    print('Loading WhisperX Arabic alignment model...')
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model_a, metadata = whisperx.load_align_model(language_code='ar', device=device)
    print(f'Model loaded on {device}\n')

    ok = 0
    fail = 0
    for surah in surahs:
        if process_surah(args.reciter, edition, surah, ffmpeg, model_a, metadata, device):
            ok += 1
        else:
            fail += 1

    print(f'\nDone. {ok} OK, {fail} failed.')


if __name__ == '__main__':
    main()
