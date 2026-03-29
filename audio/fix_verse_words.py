#!/usr/bin/env python3
"""
Re-align all words in specified verses using WhisperX forced alignment
on our full-surah MP3, keeping verse boundaries from Bilawal intact.

Usage:
    python audio/fix_verse_words.py --reciter alafasy --surah 114
    python audio/fix_verse_words.py --reciter alafasy --surah 114 --verse 1
"""

import argparse
import json
import os
import shutil
import subprocess
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
    start_sec = max(0, start_ms) / 1000.0
    dur_sec = (end_ms - max(0, start_ms)) / 1000.0
    subprocess.run([
        ffmpeg, '-y',
        '-ss', str(start_sec),
        '-t', str(dur_sec),
        '-i', mp3_path,
        '-ar', '16000', '-ac', '1', '-f', 'wav', out_wav,
    ], capture_output=True, timeout=30)


def align_verse(wav_path, words, clip_start_ms, model_a, metadata, device):
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
        pos = words[i]['position']
        w_s = int(aw.get('start', 0) * 1000 + clip_start_ms)
        w_e = int(aw.get('end', 0) * 1000 + clip_start_ms)
        new_segments.append([pos, float(w_s), float(w_e)])

    return new_segments, len(aligned)


def process_surah(reciter, surah, ffmpeg, model_a, metadata, device, only_verse=None):
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

    for verse in timestamps:
        vk = verse['verse_key']
        ayah_num = int(vk.split(':')[1])

        if only_verse and ayah_num != only_verse:
            continue

        words = verse_words.get(vk)
        if not words:
            print(f'  [{vk:>8}] SKIP - no word data')
            continue

        old_segs = verse['segments']
        vs = verse['timestamp_from']
        vt = verse['timestamp_to']

        # Extract clip for this verse
        tmp_wav = os.path.join(tempfile.gettempdir(), f'fix_{surah}_{ayah_num}.wav')
        extract_wav(ffmpeg, mp3_path, vs, vt, tmp_wav)

        try:
            new_segs, n_aligned = align_verse(tmp_wav, words, vs, model_a, metadata, device)
        except Exception as e:
            print(f'  [{vk:>8}] align error: {e}')
            continue
        finally:
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)

        if n_aligned != len(words):
            print(f'  [{vk:>8}] SKIP - aligned {n_aligned}/{len(words)} words')
            continue

        # Preserve last word's end from Bilawal (WhisperX compresses it)
        if new_segs and old_segs:
            new_segs[-1][2] = old_segs[-1][2]

        # Show comparison
        print(f'  [{vk:>8}] {len(words)} words:')
        for i in range(len(old_segs)):
            if i < len(new_segs):
                o = old_segs[i]
                n = new_segs[i]
                word_text = words[i]['text_uthmani'] if i < len(words) else '?'
                changed = '*' if abs(o[1] - n[1]) > 30 or abs(o[2] - n[2]) > 30 else ' '
                print(f'    {changed} w{o[0]}: {o[1]:.0f}-{o[2]:.0f} -> {n[1]:.0f}-{n[2]:.0f}  ({word_text})')

        verse['segments'] = new_segs
        fixed += 1

    if fixed > 0:
        with open(ts_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f'\n  [{surah:>3}] saved - {fixed} verses re-aligned')
    else:
        print(f'\n  [{surah:>3}] no changes')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reciter', required=True)
    parser.add_argument('--surah', type=int, required=True)
    parser.add_argument('--verse', type=int)
    args = parser.parse_args()

    ffmpeg = find_ffmpeg()

    print('Loading WhisperX Arabic alignment model...')
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model_a, metadata = whisperx.load_align_model(language_code='ar', device=device)
    print(f'Model loaded on {device}\n')

    process_surah(args.reciter, args.surah, ffmpeg, model_a, metadata, device, args.verse)
    print('\nDone.')


if __name__ == '__main__':
    main()
