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

Very short ayat (e.g. most of surahs 112–114) skip repetition-specific post-processing;
see SHORT_VERSE_SKIP_REPETITION_POST_MS — there is no hard-coded surah list.
"""

import subprocess
import sys
import os

# torch requires Python 3.8+. If we're running on something older, scan PATH
# for all python3.X interpreters, pick the highest version, and re-exec.
if sys.version_info < (3, 8):
    import shutil, glob
    _found_versions = []
    for _search in os.environ.get('PATH', '').split(os.pathsep):
        for _p in glob.glob(os.path.join(_search, 'python3.*')):
            try:
                _minor = int(os.path.basename(_p).split('.')[1])
                if _minor >= 8:
                    _found_versions.append((_minor, _p))
            except (IndexError, ValueError):
                pass
    if _found_versions:
        _best = sorted(_found_versions, reverse=True)[0][1]
        print(f'Python {sys.version_info.major}.{sys.version_info.minor} is too old '
              f'(need 3.8+). Re-running with {_best}...\n')
        os.execv(_best, [_best] + sys.argv)
    print(f'ERROR: Python 3.8+ is required but only {sys.version} was found.')
    print('Install python3.9 or later, then run:')
    print(f'  python3.9 {" ".join(sys.argv)}')
    sys.exit(1)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def ensure_dependencies():
    import os as _os
    import shutil as _shutil

    # Install torch first (must come before whisperx; use CPU wheel if no CUDA)
    try:
        __import__('torch')
    except ImportError:
        print('=' * 55)
        print('  Installing torch (CPU)...')
        print('=' * 55)
        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install', 'torch',
            '--index-url', 'https://download.pytorch.org/whl/cpu'
        ])
        if result.returncode != 0:
            print('\nERROR: torch install failed. Fix the error above then re-run.')
            sys.exit(1)

    # whisperx is not on PyPI — install from GitHub
    try:
        __import__('whisperx')
    except ImportError:
        print('=' * 55)
        print('  Installing whisperx from GitHub...')
        print('=' * 55)
        result = subprocess.run([
            sys.executable, '-m', 'pip', 'install',
            'git+https://github.com/m-bain/whisperX.git'
        ])
        if result.returncode != 0:
            print('\nERROR: whisperx install failed. Fix the error above then re-run.')
            sys.exit(1)

    # Remaining pure-PyPI packages
    plain = {'scipy': 'scipy'}
    missing = [pip for name, pip in plain.items() if not __import__('importlib').util.find_spec(name)]
    if missing:
        print('=' * 55)
        print(f'  Installing: {", ".join(missing)}')
        print('=' * 55)
        result = subprocess.run([sys.executable, '-m', 'pip', 'install'] + missing)
        if result.returncode != 0:
            print('\nERROR: pip install failed. Fix the error above then re-run.')
            sys.exit(1)

    print('\nAll packages installed. Continuing...\n')

    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    # On Windows look for the bundled ffmpeg.exe; on Linux/Mac use system ffmpeg
    _bundled = _os.path.join(_root, 'ffmpeg', 'ffmpeg.exe') if sys.platform == 'win32' else None
    if not (_bundled and _os.path.isfile(_bundled)) and not _shutil.which('ffmpeg'):
        print('=' * 55)
        print('  ffmpeg not found — attempting to install...')
        print('=' * 55)
        # Try common Linux package managers, then Homebrew (macOS)
        _installed = False
        for _cmd in [
            ['dnf',     'install', '-y', 'ffmpeg'],   # Rocky / RHEL / Fedora
            ['apt-get', 'install', '-y', 'ffmpeg'],   # Debian / Ubuntu
            ['yum',     'install', '-y', 'ffmpeg'],   # older CentOS
            ['brew',    'install',       'ffmpeg'],   # macOS Homebrew
        ]:
            if _shutil.which(_cmd[0]):
                print(f'  Running: {" ".join(_cmd)}')
                _r = subprocess.run(_cmd)
                if _r.returncode == 0 and _shutil.which('ffmpeg'):
                    print('  ffmpeg installed.\n')
                    _installed = True
                    break
        if not _installed:
            print('  ERROR: could not install ffmpeg automatically.')
            print('  Install it manually:')
            print('    Rocky/RHEL:  sudo dnf install ffmpeg')
            print('    Ubuntu:      sudo apt install ffmpeg')
            print('    Windows:     place ffmpeg.exe in the ffmpeg/ folder')
            print('    macOS:       brew install ffmpeg')
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

# Below this duration, skip realign_from_repetition + bridge_repetition_gaps. Those steps
# assume long ayat where the reciter repeats a phrase inside the same timestamp window.
# Very short ayat (incl. most of 112–114) often have silence or the next surah after the
# last word; the repetition logic can misfire. There is NO surah-number special case —
# only verse duration drives this.
SHORT_VERSE_SKIP_REPETITION_POST_MS = 5000

# If two consecutive words have silence >= this (ms), re-align the tail words on
# audio from just after the previous word (WhisperX often drags later words late).
# Only applies after word 1 (j>=1): tail-from-j0 mis-fires when word 1 still swallows
# audio, creating bogus huge gaps; first-word drift is handled by verse-level align.
INTRA_VERSE_GAP_RETRY_MS = 500

# Pad around first/last word ms; gap between ayat when chaining (ms).
VERSE_PAD_MS = 80
INTER_VERSE_GAP_MS = 0

# If the next ayah's first word starts much later than our last aligned word, part
# of that gap is usually trailing sound + breath for the current ayah. Extend
# timestamp_to into it so playback does not cut off abruptly (e.g. alafasy 113:3).
INTER_AYAH_GAP_MIN_MS = 400
INTER_AYAH_GAP_SHARE = 0.55  # fraction of (next_first - last_word_end) to assign to prev ayah
INTER_AYAH_NEXT_RESERVE_MS = 120  # leave this much before next ayah's first word start
INTER_AYAH_MAX_TAIL_AFTER_LAST_WORD_MS = 1600  # cap extension beyond last segment end

# ffmpeg slice: leading pad pulls in the previous ayah's audio; WhisperX then aligns
# the *next* ayah's text onto that tail (wrong words / overlaps). First ayah in a
# surah keeps a small pre-roll; every later ayah starts the slice exactly at
# timestamp_from (chain already accounts for prior end).
ALIGN_LEAD_BUFFER_FIRST_MS = 300
ALIGN_LEAD_BUFFER_CHAINED_MS = 0

# Cap FFmpeg end for forced align: inflated timestamp_to + long tail makes WhisperX
# compress early words on re-runs. Allow this much audio after loaded last segment end.
ALIGN_CLIP_MAX_TAIL_MS = 2200


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
        if 0x06D6 <= cp <= 0x06E4: continue  # Quranic annotation signs (incl. ۝۞)
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
    candidates = []
    if sys.platform == 'win32':
        candidates.append(os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg.exe'))
    candidates.append(os.path.join(ROOT_DIR, 'ffmpeg', 'ffmpeg'))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    if shutil.which('ffmpeg'):
        return 'ffmpeg'
    print(f'ERROR: ffmpeg not found. Put it in {ROOT_DIR}/ffmpeg/ or add to PATH.')
    sys.exit(1)


def extract_wav(ffmpeg, mp3_path, start_ms, end_ms, out_wav, buffer_ms=300,
                 buffer_before_ms=None):
    """buffer_ms pads after end_ms. buffer_before_ms defaults to buffer_ms; use 0 when
    start_ms is a chained ayah boundary so the clip does not include prior ayah audio."""
    bb = buffer_ms if buffer_before_ms is None else buffer_before_ms
    clip_start_ms = max(0, start_ms - bb)
    duration_sec = (end_ms + buffer_ms - clip_start_ms) / 1000.0
    subprocess.run([
        ffmpeg, '-y',
        '-ss', str(clip_start_ms / 1000.0),
        '-t',  str(duration_sec),
        '-i',  mp3_path,
        '-ar', '16000', '-ac', '1', '-f', 'wav', out_wav,
    ], check=True, capture_output=True)
    return clip_start_ms


def align_verse(wav_path, words, clip_start_ms, model_a, metadata, device):
    """Run WhisperX forced alignment on one verse. Returns (new_segments, n_aligned, scores)."""
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
    scores = []
    for i, aw in enumerate(aligned):
        if i >= len(words):
            break
        pos   = words[i]['position']
        w_s   = int(aw.get('start', 0) * 1000 + clip_start_ms)
        w_e   = int(aw.get('end',   0) * 1000 + clip_start_ms)
        new_segments.append([pos, float(w_s), float(w_e)])
        scores.append(aw.get('score', 0.0))

    return new_segments, len(aligned), scores


def smooth_segments(segs, scores, words, min_dur_ms=200):
    """Fix crushed segments by borrowing time from over-long neighbors.

    Conservative approach: only modifies the boundary between a crushed word
    and its longest neighbor. Does NOT shift other words — preserves WhisperX
    start positions which are critical for click-to-play accuracy.
    """
    if len(segs) < 2:
        return 0

    smoothed = 0
    for i in range(len(segs)):
        dur = segs[i][2] - segs[i][1]
        if dur >= min_dur_ms:
            continue

        # Find the longest adjacent word to borrow from
        prev_dur = segs[i - 1][2] - segs[i - 1][1] if i > 0 else 0
        next_dur = segs[i + 1][2] - segs[i + 1][1] if i < len(segs) - 1 else 0
        deficit = min_dur_ms - dur

        # Also account for gap between words
        gap_before = segs[i][1] - segs[i - 1][2] if i > 0 else 0
        gap_after = segs[i + 1][1] - segs[i][2] if i < len(segs) - 1 else 0

        # Strategy: first absorb gaps, then borrow from longest neighbor
        absorbed = 0

        # Absorb gap before (extend start backwards)
        if gap_before > 20:
            take = min(deficit - absorbed, gap_before - 10)
            if take > 0:
                segs[i][1] -= take
                absorbed += take

        # Absorb gap after (extend end forwards)
        if absorbed < deficit and gap_after > 20:
            take = min(deficit - absorbed, gap_after - 10)
            if take > 0:
                segs[i][2] += take
                absorbed += take

        # Still short? Borrow from the longest neighbor
        if absorbed < deficit:
            remaining = deficit - absorbed
            if prev_dur > next_dur and prev_dur > min_dur_ms + remaining:
                # Borrow from previous: shrink prev end, extend our start
                segs[i - 1][2] -= remaining
                segs[i][1] -= remaining
                absorbed += remaining
            elif next_dur > min_dur_ms + remaining:
                # Borrow from next: extend our end, shift next start
                segs[i][2] += remaining
                segs[i + 1][1] += remaining
                absorbed += remaining

        if absorbed > 0:
            smoothed += 1

    return smoothed


def squeeze_spurious_gap_after_first_word(segs, min_gap_ms=600, target_gap_ms=80):
    """If silence after word 1 is huge, WhisperX likely ended word 1 too early."""
    if len(segs) < 2:
        return False
    g = segs[1][1] - segs[0][2]
    if g < min_gap_ms:
        return False
    new_end = segs[1][1] - target_gap_ms
    if new_end <= segs[0][1] + 30:
        return False
    segs[0][2] = new_end
    return True


def realign_tail_after_internal_gap(ffmpeg, mp3_path, wav_path, words, segs, scores,
                                    start_ms, end_ms, model_a, metadata, device,
                                    gap_threshold_ms=950):
    """Re-align words after the first huge inter-word gap (fixes dragged late tails)."""
    if len(segs) < 2 or len(words) != len(segs):
        return 0
    for j in range(len(segs) - 1):
        if j == 0:
            continue
        gap = segs[j + 1][1] - segs[j][2]
        if gap < gap_threshold_ms:
            continue
        tail_words = words[j + 1:]
        if not tail_words:
            continue
        sub_start = max(start_ms, int(segs[j][2] + 30))
        if sub_start >= end_ms - 250:
            continue
        try:
            sub_clip = extract_wav(
                ffmpeg, mp3_path, sub_start, end_ms, wav_path, buffer_before_ms=0,
            )
            new_tail, n_al, tail_scores = align_verse(
                wav_path, tail_words, sub_clip, model_a, metadata, device
            )
            if n_al < len(tail_words):
                continue
            for k in range(len(tail_words)):
                segs[j + 1 + k] = new_tail[k]
                ts = tail_scores[k] if k < len(tail_scores) else 0.0
                if j + 1 + k < len(scores):
                    scores[j + 1 + k] = ts
                else:
                    scores.append(ts)
            while len(scores) < len(words):
                scores.append(0.0)
            return len(tail_words)
        except Exception:
            continue
    return 0


def realign_from_repetition(segs, scores, words, verse_start_ms, verse_end_ms,
                            ffmpeg, mp3_path, wav_path, model_a, metadata, device,
                            min_trailing_ms=3000, min_cluster=3):
    """Re-align trailing words using the repetition section of the audio.

    When a reciter repeats a phrase, WhisperX aligns all words to the first
    (rushed) pass.  The trailing audio after the last aligned word contains the
    clearer repetition.  This function:
      1. Detects trailing audio > min_trailing_ms after the last aligned word.
      2. Tries re-aligning the last N words (N = min_cluster..min_cluster+3)
         to several clip offsets within the repetition region.
      3. Picks the (N, offset) with the highest WhisperX average score.
      4. Replaces the affected segments.
    """
    if len(segs) < min_cluster:
        return 0

    # --- 1. detect trailing repetition audio ---
    last_word_end = segs[-1][2]
    trailing_ms = verse_end_ms - last_word_end

    if trailing_ms < min_trailing_ms:
        return 0  # no significant trailing audio

    rep_start = last_word_end
    rep_end = verse_end_ms
    rep_dur = rep_end - rep_start

    # --- 2. try re-aligning last N words to the repetition section ---
    best_segs = None
    best_avg = -1
    best_n = 0

    max_n = min(len(segs) // 2, min_cluster + 3)  # at most half the verse
    for n in range(min_cluster, max_n + 1):
        realign_start = len(segs) - n
        realign_words = words[realign_start:]
        realign_text = ' '.join(clean_for_alignment(w['text_uthmani'])
                                for w in realign_words)

        # candidate clips: start from various points in the repetition
        clip_candidates = [(int(rep_start), int(rep_end), 'full')]
        for pct, label in [(0.25, 's25'), (0.50, 's50'), (0.75, 's75')]:
            offset = int(rep_start + rep_dur * pct)
            clip_candidates.append((offset, int(rep_end), label))

        for clip_s, clip_e, label in clip_candidates:
            if clip_e - clip_s < 500:
                continue
            try:
                clip_offset = extract_wav(ffmpeg, mp3_path, clip_s, clip_e,
                                          wav_path, buffer_ms=0)
                sr_val, wav_data = scipy.io.wavfile.read(wav_path)
                audio = wav_data.astype(np.float32) / 32768.0
                if audio.ndim > 1:
                    audio = audio.mean(axis=1)
                duration = len(audio) / 16000.0
                if duration < 0.3:
                    continue

                transcript = [{'text': realign_text,
                               'start': 0.0, 'end': duration}]
                result = whisperx.align(transcript, model_a, metadata,
                                        audio, device,
                                        return_char_alignments=False)
                aligned = result.get('word_segments', [])
                if len(aligned) < n:
                    continue

                cand_segs = []
                cand_scores = []
                for j in range(n):
                    aw = aligned[j]
                    pos = realign_words[j]['position']
                    w_s = int(aw.get('start', 0) * 1000 + clip_offset)
                    w_e = int(aw.get('end',   0) * 1000 + clip_offset)
                    cand_segs.append([pos, float(w_s), float(w_e)])
                    cand_scores.append(aw.get('score', 0.0))

                avg_score = sum(cand_scores) / len(cand_scores)
                # penalise if first word stuck at clip start
                if (cand_scores[0] < 0.05
                        or (cand_segs[0][2] - cand_segs[0][1]) < 80):
                    avg_score *= 0.3

                if avg_score > best_avg:
                    best_avg = avg_score
                    best_segs = cand_segs
                    best_n = n
            except Exception:
                continue

        # early exit if we already found a very good match
        if best_avg > 0.6:
            break

    if best_segs is None or best_avg < 0.25:
        return 0

    # --- 3. smooth the new segments (contiguous boundaries) ---
    for j in range(len(best_segs) - 1):
        gap = best_segs[j + 1][1] - best_segs[j][2]
        if gap > 0:
            mid = best_segs[j][2] + gap / 2
            best_segs[j][2] = mid
            best_segs[j + 1][1] = mid
        elif gap < 0:
            mid = (best_segs[j][2] + best_segs[j + 1][1]) / 2
            best_segs[j][2] = mid
            best_segs[j + 1][1] = mid
    # extend last segment to verse end
    if best_segs:
        best_segs[-1][2] = float(verse_end_ms)

    # --- 4. check if preceding word has a gap to the first re-aligned word ---
    # If so, the cluster should include one more word.
    realign_start = len(segs) - best_n
    if realign_start > 0:
        gap_to_first = best_segs[0][1] - segs[realign_start - 1][2]
        if gap_to_first > 2000:
            # Try re-aligning best_n+1 words using a clip that starts earlier
            ext_n = best_n + 1
            ext_start = len(segs) - ext_n
            ext_words = words[ext_start:]
            ext_text = ' '.join(clean_for_alignment(w['text_uthmani'])
                                for w in ext_words)
            # Start clip earlier: from mid-gap to verse end
            ext_clip_s = int(segs[ext_start][2])  # after the word's first-pass end
            ext_candidates = [
                (ext_clip_s, int(rep_end), 'ext-full'),
                (int(ext_clip_s + (rep_end - ext_clip_s) * 0.25), int(rep_end), 'ext-s25'),
                (int(ext_clip_s + (rep_end - ext_clip_s) * 0.50), int(rep_end), 'ext-s50'),
            ]
            for clip_s, clip_e, label in ext_candidates:
                if clip_e - clip_s < 500:
                    continue
                try:
                    clip_offset = extract_wav(ffmpeg, mp3_path, clip_s, clip_e,
                                              wav_path, buffer_ms=0)
                    sr_val, wav_data = scipy.io.wavfile.read(wav_path)
                    audio = wav_data.astype(np.float32) / 32768.0
                    if audio.ndim > 1:
                        audio = audio.mean(axis=1)
                    duration = len(audio) / 16000.0
                    if duration < 0.3:
                        continue
                    transcript = [{'text': ext_text,
                                   'start': 0.0, 'end': duration}]
                    result = whisperx.align(transcript, model_a, metadata,
                                            audio, device,
                                            return_char_alignments=False)
                    aligned = result.get('word_segments', [])
                    if len(aligned) < ext_n:
                        continue
                    ext_segs = []
                    ext_scores = []
                    for j in range(ext_n):
                        aw = aligned[j]
                        pos = ext_words[j]['position']
                        w_s = int(aw.get('start', 0) * 1000 + clip_offset)
                        w_e = int(aw.get('end',   0) * 1000 + clip_offset)
                        ext_segs.append([pos, float(w_s), float(w_e)])
                        ext_scores.append(aw.get('score', 0.0))
                    ext_avg = sum(ext_scores) / len(ext_scores)
                    if ext_scores[0] < 0.05:
                        ext_avg *= 0.3
                    # Only accept if words are in the repetition region
                    # and score beats the initial alignment
                    if ext_segs[0][1] < rep_start:
                        continue  # words landed in first pass, not repetition
                    if ext_avg > best_avg:
                        best_segs = ext_segs
                        best_n = ext_n
                        realign_start = ext_start
                        # re-smooth extended segments
                        for j in range(len(best_segs) - 1):
                            gap = best_segs[j + 1][1] - best_segs[j][2]
                            if gap > 0:
                                mid = best_segs[j][2] + gap / 2
                                best_segs[j][2] = mid
                                best_segs[j + 1][1] = mid
                            elif gap < 0:
                                mid = (best_segs[j][2] + best_segs[j + 1][1]) / 2
                                best_segs[j][2] = mid
                                best_segs[j + 1][1] = mid
                        if best_segs:
                            best_segs[-1][2] = float(verse_end_ms)
                        break
                except Exception:
                    continue

    # --- 5. replace segments ---
    for j in range(best_n):
        segs[realign_start + j] = best_segs[j]

    return best_n


def bridge_repetition_gaps(segs, gap_threshold_ms=2000, verse_end_ms=None):
    """Extend each word's end time to the next word's start if the gap is large.

    Handles verses where the reciter repeats a phrase — WhisperX leaves a silent
    gap with no active segment, causing the highlighting to go blank. Extending
    the previous word keeps it highlighted through the repeated section.
    Only applies when the gap exceeds gap_threshold_ms (default 2 s).

    If verse_end_ms is given, also extends the last word to cover a trailing gap
    (reciter repeating at end of verse).
    """
    bridged = 0
    for i in range(len(segs) - 1):
        gap = segs[i + 1][1] - segs[i][2]
        if gap > gap_threshold_ms:
            segs[i][2] = segs[i + 1][1]
            bridged += 1
    # Bridge trailing gap (reciter repeats at end of verse)
    if verse_end_ms is not None and segs:
        trailing = verse_end_ms - segs[-1][2]
        if trailing > gap_threshold_ms:
            segs[-1][2] = float(verse_end_ms)
            bridged += 1
    return bridged


def normalize_segments(segs):
    """Convert flat [pos,start,end,pos,start,end,...] to nested [[pos,start,end],...]."""
    if not segs:
        return segs
    if isinstance(segs[0], (list, tuple)):
        return segs  # already nested
    # Flat format — group into triples
    return [segs[i:i+3] for i in range(0, len(segs) - len(segs) % 3, 3)]


def extend_timestamp_into_interayah_gap(ts_entry, last_seg_end, next_ts_entry):
    """Push timestamp_to forward when a long silence precedes the next ayah's speech."""
    cur = int(ts_entry['timestamp_to'])
    try:
        lte = int(float(last_seg_end))
    except (TypeError, ValueError):
        return cur
    if next_ts_entry is None:
        return cur
    nsegs = normalize_segments(next_ts_entry.get('segments') or [])
    if not nsegs:
        return cur
    next_first = int(min(float(s[1]) for s in nsegs))
    gap = next_first - lte
    if gap < INTER_AYAH_GAP_MIN_MS:
        return cur
    from_share = lte + int(gap * INTER_AYAH_GAP_SHARE)
    before_next = next_first - INTER_AYAH_NEXT_RESERVE_MS
    target = min(from_share, before_next)
    target = max(cur, target)
    cap = lte + INTER_AYAH_MAX_TAIL_AFTER_LAST_WORD_MS
    target = min(target, cap)
    return int(target)


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
    ap.add_argument('--end-verse',   type=int, default=0,
                    help='Stop after this verse (0 = process all)')
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
    with open(ts_path, encoding='utf-8-sig') as f:
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

    # End time of previous ayah in this surah (ms). Chaining fixes bad Tarteel
    # boundaries: if verse N's audio runs past timestamp_to, verse N+1 must not
    # be extracted from an overlapping window (common on short suwar / alafasy).
    prev_verse_end_ms = None

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, 'verse.wav')

        for idx, ts_entry in enumerate(timestamps):
            vk   = ts_entry['verse_key']
            vnum = int(vk.split(':')[1])
            if vnum < args.start_verse:
                prev_verse_end_ms = int(ts_entry['timestamp_to'])
                continue
            if args.end_verse and vnum > args.end_verse:
                break

            words = verse_words.get(vk)
            if not words:
                print(f'  [{vk:>8}] SKIP — not found in data/pages/')
                prev_verse_end_ms = int(ts_entry['timestamp_to'])
                continue

            next_ts_entry = (
                timestamps[idx + 1] if idx + 1 < len(timestamps) else None
            )

            if prev_verse_end_ms is not None:
                ts_entry['timestamp_from'] = max(
                    int(ts_entry['timestamp_from']),
                    prev_verse_end_ms + INTER_VERSE_GAP_MS,
                )
            start_ms  = int(ts_entry['timestamp_from'])
            end_ms    = int(ts_entry['timestamp_to'])
            lead_buf = (ALIGN_LEAD_BUFFER_CHAINED_MS if prev_verse_end_ms is not None
                        else ALIGN_LEAD_BUFFER_FIRST_MS)
            expected  = len(words)
            orig_segs = normalize_segments(ts_entry.get('segments', []))

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
                    ts_entry['segments'] = dedup_segs
                    ts_entry['timestamp_to'] = max(
                        int(ts_entry['timestamp_to']),
                        int(dedup_segs[-1][2]) + VERSE_PAD_MS,
                    )
                    ts_entry['timestamp_to'] = extend_timestamp_into_interayah_gap(
                        ts_entry, dedup_segs[-1][2], next_ts_entry
                    )
                    ts_entry['duration'] = (
                        int(ts_entry['timestamp_to']) - int(ts_entry['timestamp_from'])
                    )
                    prev_verse_end_ms = int(ts_entry['timestamp_to'])
                    if not args.dry_run:
                        changed += 1
                        if changed % SAVE_EVERY == 0:
                            save_json(ts_data, ts_path)
                            print(f'             └─ saved ({changed} verses so far)')
                else:
                    align_end_ms = end_ms
                    if orig_segs:
                        orig_last = max(s[2] for s in orig_segs)
                        if orig_last >= start_ms:
                            align_end_ms = min(
                                align_end_ms,
                                int(orig_last) + ALIGN_CLIP_MAX_TAIL_MS,
                            )
                    align_end_ms = max(align_end_ms, start_ms + 400)

                    clip_start_ms = extract_wav(
                        ffmpeg, mp3_path, start_ms, align_end_ms, wav_path,
                        buffer_before_ms=lead_buf,
                    )
                    new_segs, n_aligned, scores = align_verse(
                        wav_path, words, clip_start_ms, model_a, metadata, device
                    )

                    # Detect repetition: if aligned words cover <75% of verse,
                    # the audio likely contains the reciter repeating. Re-align
                    # with a shorter clip covering only the first pass for better
                    # per-word accuracy.
                    verse_dur = align_end_ms - start_ms
                    if new_segs and verse_dur > 0:
                        seg_span = new_segs[-1][2] - new_segs[0][1]
                        coverage = seg_span / verse_dur
                        if coverage < 0.75 and n_aligned >= expected:
                            # Re-extract clip ending just after last aligned word
                            retry_end = min(
                                int(new_segs[-1][2] + 1500),
                                align_end_ms,
                            )
                            clip_start_ms = extract_wav(
                                ffmpeg, mp3_path, start_ms, retry_end, wav_path,
                                buffer_before_ms=lead_buf,
                            )
                            new_segs, n_aligned, scores = align_verse(
                                wav_path, words, clip_start_ms, model_a, metadata, device
                            )

                    if n_aligned < expected:
                        # Fill missing positions from original data
                        for i in range(n_aligned, expected):
                            if i < len(orig_segs):
                                new_segs.append(orig_segs[i])
                            if i < len(scores):
                                pass
                            else:
                                scores.append(0.0)
                        partial.append(vk)
                        flag = ' ⚠ partial'
                    else:
                        flag = ''

                    # Smooth out crushed segments (WhisperX often compresses
                    # words in connected speech to <100ms)
                    n_smoothed = smooth_segments(new_segs, scores, words)
                    if n_smoothed:
                        flag += f' ~{n_smoothed} smoothed'

                    n_tail_passes = 0
                    for _ in range(2):
                        n_tw = realign_tail_after_internal_gap(
                            ffmpeg, mp3_path, wav_path, words, new_segs, scores,
                            start_ms, align_end_ms, model_a, metadata, device,
                            gap_threshold_ms=INTRA_VERSE_GAP_RETRY_MS,
                        )
                        if n_tw == 0:
                            break
                        n_tail_passes += 1
                        smooth_segments(new_segs, scores, words)
                    if n_tail_passes:
                        flag += f' ↳tail×{n_tail_passes}'

                    n_realigned = 0
                    n_bridged = 0
                    if verse_dur >= SHORT_VERSE_SKIP_REPETITION_POST_MS:
                        # Re-align trailing words using the repetition section
                        n_realigned = realign_from_repetition(
                            new_segs, scores, words, start_ms, align_end_ms,
                            ffmpeg, mp3_path, wav_path, model_a, metadata, device
                        )
                        # Bridge large gaps caused by reciter repeating a phrase
                        n_bridged = bridge_repetition_gaps(
                            new_segs, verse_end_ms=align_end_ms
                        )
                    if n_realigned:
                        flag += f' ♻ {n_realigned} re-aligned from repetition'
                    if n_bridged:
                        flag += f' ↔ {n_bridged} gap(s) bridged'

                    squeeze_spurious_gap_after_first_word(new_segs)

                    ts_entry['timestamp_to'] = max(
                        int(ts_entry['timestamp_to']),
                        int(new_segs[-1][2]) + VERSE_PAD_MS,
                    )
                    ts_entry['timestamp_to'] = extend_timestamp_into_interayah_gap(
                        ts_entry, new_segs[-1][2], next_ts_entry
                    )
                    ts_entry['duration'] = (
                        int(ts_entry['timestamp_to']) - int(ts_entry['timestamp_from'])
                    )
                    prev_verse_end_ms = int(ts_entry['timestamp_to'])

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
