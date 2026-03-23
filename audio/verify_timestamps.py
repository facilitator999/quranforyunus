#!/usr/bin/env python3
"""Verify word timestamps against actual audio energy levels."""
import json, sys, os, subprocess, struct, math

def get_audio_energy(mp3_path, start_ms, duration_ms=100):
    """Extract a tiny clip and measure its RMS energy."""
    cmd = [
        'ffmpeg', '-y', '-ss', str(start_ms / 1000.0),
        '-t', str(duration_ms / 1000.0),
        '-i', mp3_path,
        '-ar', '16000', '-ac', '1', '-f', 's16le', '-'
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        return 0.0
    raw = result.stdout
    if len(raw) < 4:
        return 0.0
    samples = struct.unpack(f'<{len(raw)//2}h', raw)
    rms = math.sqrt(sum(s*s for s in samples) / len(samples)) if samples else 0
    return rms

def scan_energy_profile(mp3_path, start_ms, end_ms, step_ms=50):
    """Get energy at regular intervals across a range."""
    energies = []
    t = start_ms
    while t < end_ms:
        e = get_audio_energy(mp3_path, t, step_ms)
        energies.append((t, e))
        t += step_ms
    return energies

def main():
    reciter = sys.argv[1] if len(sys.argv) > 1 else 'alafasy'
    surah = int(sys.argv[2]) if len(sys.argv) > 2 else 9
    verse = int(sys.argv[3]) if len(sys.argv) > 3 else 2

    vk = f'{surah}:{verse}'
    mp3_path = f'audio/{reciter}/recitation/{surah}.mp3'
    ts_path = f'audio/{reciter}/timestamps/{surah}.json'

    words_text = ['فَسِيحُوا۟','فِى','ٱلْأَرْضِ','أَرْبَعَةَ','أَشْهُرٍۢ',
                  'وَٱعْلَمُوٓا۟','أَنَّكُمْ','غَيْرُ','مُعْجِزِى','ٱللَّهِ',
                  'وَأَنَّ','ٱللَّهَ','مُخْزِى','ٱلْكَـٰفِرِينَ']

    with open(ts_path, encoding='utf-8-sig') as f:
        data = json.load(f)

    ts_entry = None
    for t in data['audio_file']['timestamps']:
        if t['verse_key'] == vk:
            ts_entry = t
            break

    if not ts_entry:
        print(f'Verse {vk} not found')
        return

    segs = ts_entry['segments']
    print(f'=== {reciter} {vk} ===')
    print(f'Verse: {ts_entry["timestamp_from"]}-{ts_entry["timestamp_to"]}ms\n')

    # Check energy at each word's start position
    print(f'Energy check at word START positions:')
    print(f'  {"Word":<4} {"Start":>7} {"End":>7} {"Dur":>5} {"Energy@Start":>13} {"Energy@Mid":>11} {"Text"}')
    print(f'  {"-"*4} {"-"*7} {"-"*7} {"-"*5} {"-"*13} {"-"*11} {"-"*15}')

    for i, s in enumerate(segs):
        start = int(s[1])
        end = int(s[2])
        dur = end - start
        mid = start + dur // 2

        e_start = get_audio_energy(mp3_path, start, 80)
        e_mid = get_audio_energy(mp3_path, mid, 80)

        w = words_text[i] if i < len(words_text) else '?'
        bar_s = '█' * int(e_start / 500) if e_start > 200 else '░' * max(1, int(e_start / 500))
        bar_m = '█' * int(e_mid / 500) if e_mid > 200 else '░' * max(1, int(e_mid / 500))

        flag = ''
        if e_start < 200:
            flag = ' ← SILENCE at start!'
        if e_mid < 200:
            flag += ' ← SILENCE at mid!'

        print(f'  [{i:2d}] {start:7d} {end:7d} {dur:5d} {e_start:8.0f} {bar_s:<5} {e_mid:8.0f} {bar_m:<3} {w}{flag}')

    # Scan energy profile across the verse to find speech/silence pattern
    print(f'\n--- Energy profile (speech vs silence) ---')
    first_start = int(segs[0][1])
    last_end = int(segs[-2][2]) if len(segs) > 1 else int(segs[0][2])  # exclude bridged last

    profile = scan_energy_profile(mp3_path, ts_entry['timestamp_from'], min(last_end + 2000, ts_entry['timestamp_to']), 200)

    # Find silence gaps (energy < 300 for >400ms)
    silence_start = None
    silences = []
    for t, e in profile:
        if e < 300:
            if silence_start is None:
                silence_start = t
        else:
            if silence_start is not None:
                gap = t - silence_start
                if gap >= 400:
                    silences.append((silence_start, t, gap))
                silence_start = None

    if silences:
        print(f'  Detected silence gaps (>400ms):')
        for s_start, s_end, gap in silences:
            # Check if any word boundary falls in this silence
            in_silence = []
            for i, s in enumerate(segs):
                if s_start <= s[1] <= s_end or s_start <= s[2] <= s_end:
                    in_silence.append(i)
            boundary_info = f' (words {in_silence} have boundary here)' if in_silence else ''
            print(f'    {s_start}-{s_end}ms ({gap}ms){boundary_info}')
    else:
        print(f'  No major silence gaps detected in first pass')

    # Check: does the audio have energy AFTER the last non-bridged segment?
    print(f'\n--- Repetition check ---')
    rep_start = int(segs[-2][2]) if len(segs) > 1 else int(segs[0][2])
    rep_profile = scan_energy_profile(mp3_path, rep_start, ts_entry['timestamp_to'], 500)
    has_speech = any(e > 500 for _, e in rep_profile)
    print(f'  Audio after word {len(segs)-2} end ({rep_start}ms): {"SPEECH detected (repetition)" if has_speech else "mostly silence"}')


if __name__ == '__main__':
    main()
