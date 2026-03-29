#!/usr/bin/env python3
"""
Fix last-word timestamps in each verse by re-aligning with WhisperX.

Extracts a clip from the last word's current start to the verse boundary,
runs WhisperX forced alignment on just that single word, and updates the
end time. Only extends, never shortens. Clamped to not overlap next verse.

Usage:
    python audio/fix_last_words.py --reciter alafasy --surah 109
    python audio/fix_last_words.py --reciter alafasy --start 109 --end 114
    python audio/fix_last_words.py --reciter alafasy --start 1 --end 114
"""

import argparse
import json
import os
import shutil
import sys
import tempfile

import numpy as np
import scipy.io.wavfile
import torch
import whisperx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
PAGES_DIR = os.path.join(ROOT_DIR, 'data', 'pages')


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
    import subprocess
    start_sec = max(0, start_ms) / 1000.0
    dur_sec = (end_ms - max(0, start_ms)) / 1000.0
    subprocess.run([
        ffmpeg, '-y',
        '-ss', str(start_sec),
        '-t', str(dur_sec),
        '-i', mp3_path,
        '-ar', '16000', '-ac', '1', '-f', 'wav', out_wav,
    ], capture_output=True, timeout=30)


def align_word(wav_path, word_text, clip_start_ms, model_a, metadata, device):
    """Align a single word in a wav clip. Returns (start_ms, end_ms) absolute, or None."""
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

    cleaned = clean_for_alignment(word_text)
    transcript = [{'text': cleaned, 'start': 0.0, 'end': duration}]
    result = whisperx.align(transcript, model_a, metadata, audio, device,
                            return_char_alignments=False)
    aligned = result.get('word_segments', [])
    if not aligned:
        return None

    w = aligned[0]
    w_s = int(w.get('start', 0) * 1000 + clip_start_ms)
    w_e = int(w.get('end', 0) * 1000 + clip_start_ms)
    return w_s, w_e


def process_surah(reciter, surah, ffmpeg, model_a, metadata, device):
    ts_path = os.path.join(ROOT_DIR, 'audio', reciter, 'timestamps', f'{surah}.json')
    mp3_path = os.path.join(ROOT_DIR, 'audio', reciter, 'recitation', f'{surah}.mp3')

    if not os.path.exists(ts_path) or not os.path.exists(mp3_path):
        print(f'  [{surah:>3}] SKIP - missing files')
        return

    with open(ts_path, encoding='utf-8') as f:
        data = json.load(f)

    verse_words = find_all_verse_words(surah)
    timestamps = data['audio_file']['timestamps']
    fixed = 0

    for vi, verse in enumerate(timestamps):
        vk = verse['verse_key']
        segs = verse['segments']
        words = verse_words.get(vk)
        if not words or not segs:
            continue

        last_seg = segs[-1]
        last_word_text = words[-1].get('text_uthmani', '') if len(words) >= len(segs) else None
        if not last_word_text:
            continue

        # Current last word timing
        cur_start = last_seg[1]
        cur_end = last_seg[2]
        vt = verse['timestamp_to']

        # Hard limit: next verse's first word start (don't bleed into it)
        if vi + 1 < len(timestamps):
            next_segs = timestamps[vi + 1]['segments']
            hard_limit = next_segs[0][1] if next_segs else vt
        else:
            hard_limit = vt

        # If last word already reaches close to the limit, skip
        if hard_limit - cur_end < 50:
            continue

        # Extract clip from last word start to verse boundary + buffer
        clip_start = int(cur_start)
        clip_end = int(vt + 300)
        tmp_wav = os.path.join(tempfile.gettempdir(), f'fix_last_{surah}_{vk.replace(":", "_")}.wav')
        extract_wav(ffmpeg, mp3_path, clip_start, clip_end, tmp_wav)

        try:
            result = align_word(tmp_wav, last_word_text, clip_start, model_a, metadata, device)
        except Exception as e:
            print(f'  [{vk:>8}] align error: {e}')
            continue
        finally:
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)

        if result is None:
            continue

        new_start, new_end = result

        # Clamp to hard limit (next verse first word)
        new_end = min(new_end, hard_limit)

        # Only update if WhisperX found a longer end (don't shorten)
        if new_end > cur_end + 30:
            old_dur = cur_end - cur_start
            new_dur = new_end - cur_start
            last_seg[2] = float(new_end)
            fixed += 1
            print(f'  [{vk:>8}] last word extended: {old_dur:.0f}ms -> {new_dur:.0f}ms')

    if fixed > 0:
        with open(ts_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f'  [{surah:>3}] saved - {fixed} last words fixed')
    else:
        print(f'  [{surah:>3}] no changes needed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reciter', required=True)
    parser.add_argument('--surah', type=int)
    parser.add_argument('--start', type=int, default=109)
    parser.add_argument('--end', type=int, default=114)
    args = parser.parse_args()

    ffmpeg = find_ffmpeg()

    if args.surah:
        surahs = [args.surah]
    else:
        surahs = list(range(args.start, args.end + 1))

    print(f'Loading WhisperX Arabic alignment model...')
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model_a, metadata = whisperx.load_align_model(language_code='ar', device=device)
    print(f'Model loaded on {device}\n')

    print(f'Fixing last-word timestamps for {args.reciter}, surahs {surahs[0]}-{surahs[-1]}')
    for surah in surahs:
        process_surah(args.reciter, surah, ffmpeg, model_a, metadata, device)

    print('\nDone.')


if __name__ == '__main__':
    main()
