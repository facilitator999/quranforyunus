# Adding a New Reciter & Repairing Timestamps

This guide covers every step needed to add a new reciter to the app — from finding audio to
generating letter sounds — plus tools for repairing word-level timestamps after the fact.
Updated as each reciter was actually added so the steps reflect what really works.

---

## Hard Rules

- **No individual verse (ayah) MP3 files.** The final `recitation/` folder must contain only
  114 surah-level files (`1.mp3` … `114.mp3`). No per-ayah files anywhere in the repo.
- **MP3 and timestamps must come from the same source.** Mixing sources causes word highlighting
  to drift or be completely wrong. Always verify both are from the same recording before using.
- **Never binary-concatenate ayah files as a substitute for the real surah file.** Even if the
  result plays correctly, the timing will not match surah-level timestamps. This happened with
  Maher's surah 1 — the ayah-concat was 483KB (30.9s) vs the correct surah file at 507KB (32.4s).
- **Always verify duration matches.** After downloading, check that estimated MP3 duration ≈
  last `timestamp_to` in the JSON (within ~100ms). See the verification script below.

---

## What each reciter needs

```
audio/{reciter}/
  recitation/     ← one MP3 per surah (1.mp3 … 114.mp3)
  timestamps/     ← one JSON per surah (1.json … 114.json)
  letters/        ← one MP3 per Arabic letter/diacritic (48 files)
```

Plus two lines in `index.html` (one in `RECITERS`, one in the `<select>`).

---

## Choosing a source

There are two timestamp sources. Pick the one that has your reciter:

| Source | Reciters | Timestamps | Audio |
|--------|----------|-----------|-------|
| **Quran.com API** | 12 popular reciters (see list below) | ✅ word-level | Download separately from quranicaudio.com |
| **Tarteel QUL** | 41 reciters with segments | ✅ word-level | Download from Tarteel CDN |

If the reciter isn't in either, you can add them without word-level timestamps — the app falls
back to surah-level playback only (no word highlighting).

---

## Step 1 — Get timestamps + audio (matched pair)

### Method A — Quran.com API

Works for these 12 reciters:

| ID | Reciter |
|----|---------|
| 7  | Mishary Alafasy |
| 9  | Minshawi (Murattal) |
| 1  | AbdulBaset AbdulSamad |
| 2  | AbdulBaset (Mujawwad) |
| 10 | Hudhaify |
| 3  | Abdur-Rahman as-Sudais |
| 4  | Abu Bakr al-Shatri |
| 5  | Hani ar-Rifai |
| 6  | Mahmoud Khalil Al-Husary |
| 8  | Minshawi (Mujawwad) |
| 11 | Mohamed al-Tablawi |
| 12 | Al-Husary (Muallim) |

**Step 1a — Fetch timestamps:**
```bash
py fetch_alafasy_timestamps_qf.py --reciter-id <ID> --force
```
By default writes to `audio/alafasy/timestamps/`. To target a different folder, edit `TS_DIR`
at the top of the script (two places: the dir path and the `audio_url` string).

**Step 1b — Get the matching audio URL:**
```
https://api.quran.com/api/v4/chapter_recitations/{reciter_id}/{chapter}
```
The response contains `audio_url` (e.g. `https://download.quranicaudio.com/qdc/siddiq_minshawi/murattal/2.mp3`).
Download all 114 from that CDN pattern:

```python
import urllib.request, os
from concurrent.futures import ThreadPoolExecutor

CDN = 'https://download.quranicaudio.com/qdc/siddiq_minshawi/murattal'  # change per reciter
OUT = 'audio/minshawi/recitation'
os.makedirs(OUT, exist_ok=True)

def dl(ch):
    url  = f'{CDN}/{ch}.mp3'
    dest = f'{OUT}/{ch}.mp3'
    if os.path.exists(dest) and os.path.getsize(dest) > 10000: return ch, 'skip'
    req = urllib.request.Request(url, headers={'User-Agent': 'QuranKids/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r: data = r.read()
    open(dest, 'wb').write(data)
    return ch, len(data)

with ThreadPoolExecutor(max_workers=8) as ex:
    for ch, result in ex.map(dl, range(1, 115)):
        print(f'{ch}/114: {result}')
```

---

### Method B — Tarteel QUL (preferred for reciters not in Quran.com API)

**Source:** `https://qul.tarteel.ai/resources/recitation`
Filter by "With Segments". Requires a Tarteel account.

Each reciter on QUL has two listing types — always use the **Surah by Surah (Gapless)** one:

| Type | Audio files | Notes |
|------|-------------|-------|
| **Surah by Surah (Gapless)** ✅ | 114 surah MP3s | Timestamps already absolute — use this |
| Ayah by Ayah (Gapped) ❌ | 6236 per-ayah files | Violates the no-individual-verses rule |

#### Download the data files

From the reciter's QUL page, download:
- `surah-recitation-{name}.zip` — contains `surah.json` + `segments.json`
- `surah-recitation-{name}.db.zip` — SQLite version (backup; the JSON is easier)

Place the unzipped contents in `scripts/{reciter}_surah/`.

#### File formats

**`surah.json`** — one entry per surah:
```json
{
  "1": {
    "surah_number": 1,
    "audio_url": "https://audio-cdn.tarteel.ai/quran/surah/maherAlMuaiqly/murattal/mp3/001.mp3",
    "duration": 32
  }
}
```

**`segments.json`** — one entry per ayah, timestamps already absolute within the surah MP3:
```json
{
  "1:1": {
    "timestamp_from": 0,
    "timestamp_to":   4312,
    "duration_ms":    4312,
    "segments": [[1, 0, 1790], [2, 1840, 2590], [3, 2640, 3630], [4, 3680, 4312]]
  },
  "1:2": {
    "timestamp_from": 4512,
    "timestamp_to":   8199,
    "segments": [[1, 4880, 5390], ...]
  }
}
```
Segments are `[word_number, start_ms, end_ms]`, all absolute within the surah file.

#### Run the extractor

For Maher Al-Muaiqly (already set up):
```bash
py scripts/extract_maher_surah.py
```

For a new reciter — copy `scripts/extract_maher_surah.py`, update these constants at the top:
```python
DATA_DIR = os.path.join(SCRIPT_DIR, 'your_reciter_surah')  # folder with surah.json + segments.json
RECITER  = 'your_reciter'                                   # folder name under audio/
```

This writes `audio/{reciter}/timestamps/1.json … 114.json` and `audio/{reciter}/surah_downloads.txt`.

#### Download the 114 surah MP3s

```python
import urllib.request, os
from concurrent.futures import ThreadPoolExecutor

RECITER = 'maher'
os.makedirs(f'audio/{RECITER}/recitation', exist_ok=True)
with open(f'audio/{RECITER}/surah_downloads.txt') as f:
    urls = [l.strip() for l in f if l.strip()]

def dl(args):
    i, url = args
    dest = f'audio/{RECITER}/recitation/{i}.mp3'
    if os.path.exists(dest) and os.path.getsize(dest) > 10000: return i, 'skip'
    req = urllib.request.Request(url, headers={'User-Agent': 'QuranKids/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r: data = r.read()
    open(dest, 'wb').write(data)
    return i, len(data)

with ThreadPoolExecutor(max_workers=8) as ex:
    for i, result in ex.map(dl, enumerate(urls, 1)):
        print(f'{i}/114: {result}')
```

#### Known reciters on Tarteel QUL

| Reciter | QUL page | CDN slug | Local folder | Extractor script |
|---------|----------|----------|--------------|-----------------|
| Maher Al-Muaiqly | [/562](https://qul.tarteel.ai/resources/recitation/562) | `maherAlMuaiqly` | `maher` | `scripts/extract_maher_surah.py` |

Add rows here as new reciters are added. Always link to the Surah-by-Surah page, not the Ayah-by-Ayah page.

#### Verify all downloads before finishing

After downloading all 114 surah MP3s, always run this check. A mismatch of more than ~200ms
means either the wrong file was downloaded, or there is a data quality issue in the QUL export
(see known issues below).

```python
import json, os

RECITER = 'maher'
BITRATE = 128  # kbps — check the actual MP3 header if unsure

print(f'Checking {RECITER}...')
issues = []
for ch in range(1, 115):
    mp3  = f'audio/{RECITER}/recitation/{ch}.mp3'
    ts   = f'audio/{RECITER}/timestamps/{ch}.json'
    if not os.path.exists(mp3):
        issues.append(f'Ch {ch}: MP3 MISSING'); continue
    size     = os.path.getsize(mp3)
    est_ms   = size * 8 / (BITRATE * 1000) * 1000
    with open(ts) as f:
        last_ts = json.load(f)['audio_file']['timestamps'][-1]['timestamp_to']
    diff = abs(est_ms - last_ts)
    if diff > 200:
        issues.append(f'Ch {ch}: est={est_ms:.0f}ms, last_ts={last_ts}ms, diff={diff:.0f}ms ← MISMATCH')

if issues:
    for iss in issues: print(iss)
else:
    print('All 114 surahs OK.')
```

#### Known Tarteel QUL data quality issues (Maher Al-Muaiqly, discovered March 2026)

After verifying all 114 surahs, 6 had genuine mismatches where the CDN audio was shorter
than the timestamps expect — confirmed by re-downloading and getting identical file sizes:

| Surah | MP3 duration | Last timestamp | Difference |
|-------|-------------|---------------|-----------|
| 16 (An-Nahl) | 1989s | 2005s | -16s |
| 37 (As-Saffat) | 910s | 921s | -11s |
| 44 (Ad-Dukhan) | 371s | 387s | -17s |
| 75 (Al-Qiyamah) | 160s | 167s | -7s |
| 76 (Al-Insan) | 280s | 289s | -9s |
| 80 (Abasa) | 154s | 162s | -8s |

**Impact:** All internal verse/word highlights are correct. Only the final verse's
`timestamp_to` extends past the end of the audio, so the last verse highlight stays on a
few seconds after audio ends rather than clearing. Acceptable in practice.

**Root cause:** The Tarteel QUL `segments.json` for these surahs was calibrated from a
recording that included extra post-surah content (e.g. silence or outro) that isn't present
in the current CDN file. If Tarteel updates their CDN to match, re-run the verify script.

---

#### If the CDN URL or data format changes

Tarteel QUL URLs and formats may change. If downloads fail or the JSON structure looks
different to what's documented here, the steps to find the correct source are:

1. **Check the QUL page for the reciter** — log in to `qul.tarteel.ai` and re-download the
   latest JSON export. The `surah.json` inside will contain the current `audio_url` for each
   surah, which is the authoritative source.

2. **Inspect the JSON structure** before running any extractor:
   ```python
   import json
   with open('scripts/{reciter}_surah/surah.json') as f:
       d = json.load(f)
   print(list(d.items())[:2])  # check key format and fields
   with open('scripts/{reciter}_surah/segments.json') as f:
       d = json.load(f)
   print(list(d.items())[:2])  # check verse key format and segment structure
   ```
   Expected: surah keys are strings like `"1"`, verse keys like `"1:1"`, segments as
   `[word_num, start_ms, end_ms]` with `timestamp_from`/`timestamp_to` already absolute.

3. **Confirm a sample audio URL works** before running the full download:
   ```python
   import urllib.request
   url = 'https://audio-cdn.tarteel.ai/quran/surah/maherAlMuaiqly/murattal/mp3/001.mp3'
   req = urllib.request.Request(url, headers={'User-Agent': 'QuranKids/1.0'})
   with urllib.request.urlopen(req, timeout=10) as r:
       print(r.status, r.headers.get('Content-Length'), 'bytes')
   ```

4. **If the CDN changes entirely** — re-download the `surah.json` from QUL, extract all
   `audio_url` values, update `surah_downloads.txt`, and re-run the download script.
   The timestamp JSONs don't need to change as long as the QUL `segments.json` is the same.

---

## Step 2 — Generate Letter Audio (ElevenLabs voice clone)

The spelling mode plays individual Arabic letter sounds in the reciter's voice,
generated via ElevenLabs instant voice cloning.

**Requires:** `audio/generate_audio.py` (API key already embedded), Python `requests` library.

### First time (clone the voice)

The script uses `audio/{reciter}/recitation/1.mp3` as the voice sample. Make sure surah 1
is already downloaded before running.

```bash
cd audio
py generate_audio.py --reciter {reciter} --clone
```

This:
1. Reads `audio/{reciter}/recitation/1.mp3`
2. Sends it to ElevenLabs to create an instant voice clone
3. Saves the `voice_id` to `audio/voice_ids.json`
4. Generates 48 letter MP3s into `audio/{reciter}/letters/`

### Subsequent runs (voice already cloned)

```bash
py generate_audio.py --reciter {reciter}
```

### Force regenerate letters

```bash
py generate_audio.py --reciter {reciter} --force
```

### Known issue — fixed in March 2026

`generate_audio.py` had a bug where the sample MP3 file handle was closed before
`requests.post` could read it, causing `ValueError: read of closed file`. Fixed by reading
the bytes into memory inside the `with` block. If you see this error on an older copy of the
script, apply this fix in `clone_voice_from_mp3()`:

```python
# Before (broken):
with open(sample_path, "rb") as f:
    files = [("files", (os.path.basename(sample_path), f, "audio/mpeg"))]
    ...
r = requests.post(...)   # ← file is already closed here

# After (fixed):
with open(sample_path, "rb") as f:
    sample_bytes = f.read()
files = [("files", (os.path.basename(sample_path), sample_bytes, "audio/mpeg"))]
...
r = requests.post(...)
```

---

## Step 3 — Register in index.html

**Add to `RECITERS`** (search for `const RECITERS`):
```javascript
maher: { name: 'Maher Al-Muaiqly', recitationDir: 'audio/maher/recitation', timestampsDir: 'audio/maher/timestamps', lettersDir: 'audio/maher/letters' },
```

**Add to the `<select>`** (search for `reciter-select`):
```html
<option value="maher">Maher Al-Muaiqly</option>
```

---

## Step 4 — Upload to Server

```
audio/{reciter}/recitation/    ← 114 MP3s
audio/{reciter}/timestamps/    ← 114 JSONs
audio/{reciter}/letters/       ← 48 MP3s
```

Do not upload `scripts/`, zip files, or any intermediate working files.

---

## File Size Reference

| Folder | Typical size |
|--------|-------------|
| `recitation/` (114 MP3s) | 50–500 MB depending on reciter and bitrate |
| `timestamps/` (114 JSONs) | 1–3 MB |
| `letters/` (48 MP3s) | ~1 MB |

---

## Reciters currently in the app

| Key | Name | Timestamps source | Audio source |
|-----|------|------------------|--------------|
| `minshawi` | Muhammad Siddiq Al-Minshawi | Quran.com API (ID 9) | quranicaudio.com/qdc |
| `alafasy`  | Mishary Alafasy | Quran.com API (ID 7) | quranicaudio.com/qdc |
| `maher`    | Maher Al-Muaiqly | Tarteel QUL ([/562](https://qul.tarteel.ai/resources/recitation/562)) | audio-cdn.tarteel.ai |

---

## Troubleshooting

**Audio plays but no word highlighting**
→ Check `timestamps/{surah}.json` exists and `segments` arrays are non-empty.

**Letter sounds are wrong voice**
→ The ElevenLabs clone is only as good as the sample. Use a longer or clearer surah MP3
and re-run with `--clone --force`.

**Timestamps are all zero**
→ The Quran.com API returned empty segments. Try `--force` to re-fetch, or confirm the
reciter ID supports segments at `https://api.quran.com/api/v4/resources/recitations`.

**Word highlighting is one word behind throughout a surah**
→ The timestamp JSON has stale segment data. See the repair section below.

**`ValueError: read of closed file` during ElevenLabs clone**
→ See the known issue fix in Step 2 above.

---

## Diagnosing & Repairing Timestamp Issues

### Background

Each `.json` file has two layers:

| Layer | Fields | Controls |
|-------|--------|---------|
| Verse-level | `timestamp_from` / `timestamp_to` | When the app jumps to the next verse |
| Word-level | `segments` | Word-by-word highlight within a verse |

They can be wrong independently. Verse-level errors = wrong verse highlighted. Word-level
errors = highlighting lags or skips within a verse.

### Stale segment pattern (Quran.com API reciters)

The Quran.com API updated its word-boundary data at some point. Old fetches omitted the first
segment of each verse, so the word list was shifted by one and a filler was appended at the
end — keeping word counts identical, making the bug invisible without comparing to the live API.

Example — Minshawi surah 2, verse 2:2:

| | Stale (old fetch) | Current API |
|-|-------------------|-------------|
| verse range | 6520–15870 ms | 6520–15870 ms ✅ |
| word 1 | 7910–9040 ms ❌ | **6520–7910 ms** ✅ |
| word 2 | 9040–9380 ms | 7910–9040 ms |
| last word | 14925–15870 ms (filler) | 12710–14925 ms |

**Minshawi repair history:** chapters 78–114 were stale; repaired March 2026. Chapters 1–77
were already current.

### Step 1 — Confirm the MP3 matches the API

```
https://api.quran.com/api/v4/chapter_recitations/{reciter_id}/{chapter}
```
Compare the `audio_url` and `file_size` in the response against the local MP3.
If they match, the MP3 is the correct source.

### Step 2 — Scan all chapters for stale segments

Run from the project root (Quran.com API reciters only):

```python
import json, os, time, urllib.request

RECITER_ID = 9          # Minshawi = 9, Alafasy = 7, etc.
RECITER    = 'minshawi'
API_BASE   = 'https://api.quran.com/api/v4'

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'QuranKids/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

ts_dir = os.path.join('audio', RECITER, 'timestamps')
for ch in range(1, 115):
    path = os.path.join(ts_dir, f'{ch}.json')
    if not os.path.exists(path):
        print(f'Ch {ch:3d}: MISSING'); continue
    with open(path) as f:
        local = json.load(f)['audio_file']['timestamps']
    api_ts = (fetch_json(f'{API_BASE}/chapter_recitations/{RECITER_ID}/{ch}?segments=true')
              .get('audio_file') or {}).get('timestamps') or []
    by_key = {t['verse_key']: t for t in api_ts}
    stale = [
        v['verse_key'] for v in local
        if (a := by_key.get(v['verse_key']))
        and (a.get('segments') or [])
        and (v.get('segments') or [])
        and a['segments'][0][1] != v['segments'][0][1]
    ]
    if stale:
        print(f'Ch {ch:3d}: STALE — {len(stale)} verses')
    time.sleep(0.3)
```

### Step 3 — Repair one or more chapters

```python
import json, os, time, urllib.request

RECITER_ID = 9
RECITER    = 'minshawi'
CHAPTERS   = [2]        # or list(range(78, 115))
API_BASE   = 'https://api.quran.com/api/v4'
TS_DIR     = os.path.join('audio', RECITER, 'timestamps')

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'QuranKids/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

for ch in CHAPTERS:
    raw = (fetch_json(f'{API_BASE}/chapter_recitations/{RECITER_ID}/{ch}?segments=true')
           .get('audio_file') or {}).get('timestamps') or []
    if not raw:
        print(f'Ch {ch}: no data, skipped'); continue
    out = []
    for t in raw:
        f, to = int(t.get('timestamp_from', 0)), int(t.get('timestamp_to', 0))
        segs = [[int(s[0]), int(s[1]), int(s[2])] for s in (t.get('segments') or []) if len(s) >= 3]
        out.append({'verse_key': t.get('verse_key', ''), 'timestamp_from': f,
                    'timestamp_to': to, 'duration': to - f, 'segments': segs})
    result = {'audio_file': {'id': 0, 'chapter_id': ch,
              'audio_url': f'audio/{RECITER}/recitation/{ch}.mp3',
              'timestamps': out, 'file_size': 0, 'format': 'mp3'}}
    with open(os.path.join(TS_DIR, f'{ch}.json'), 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f'Ch {ch:3d}: written ({len(out)} verses)')
    time.sleep(0.25)
```

---

## AI-Powered Word-Level Repair (WhisperX Forced Alignment)

When the API-based approach above isn't available (e.g. Tarteel reciters like Maher) or the
word-level segments are simply inaccurate, use `audio/repair_timestamps.py`. It uses
**WhisperX forced alignment** — takes the known Arabic text for a verse and the surah MP3,
then computes precise word-level timestamps by aligning the text against the audio.

**What it changes:** only the `segments[]` array for the specified verse. It never touches
`timestamp_from` or `timestamp_to` (verse boundaries stay exactly as-is).

**What it does NOT do:** transcription or guessing — it aligns known text to audio, so it is
fast and accurate.

### Requirements

- Python 3.8+
- ffmpeg — either place `ffmpeg.exe` in `{project_root}/ffmpeg/` or add to system PATH
  - Download: https://ffmpeg.org/download.html
- `whisperx`, `scipy`, `torch` — auto-installed on first run

### Usage

Run from anywhere (the script locates the project root automatically):

```bash
# Dry run — shows what would change, writes nothing
python audio/repair_timestamps.py --reciter maher --surah 2 --verse 5 --dry-run

# Apply the repair (writes a .bak backup first)
python audio/repair_timestamps.py --reciter maher --surah 2 --verse 5
```

Arguments:

| Argument | Required | Description |
|----------|----------|-------------|
| `--reciter` | yes | Reciter folder name (e.g. `maher`, `minshawi`, `alafasy`) |
| `--surah` | yes | Surah number 1–114 |
| `--verse` | yes | Verse number |
| `--dry-run` | no | Print result without writing |

### What the script does (step by step)

1. Looks up the Arabic word list for the verse from `data/pages/*.json`
2. Loads existing timestamps from `audio/{reciter}/timestamps/{surah}.json`
3. Extracts the verse audio (± 300 ms buffer) from the surah MP3 as a 16 kHz mono WAV
4. Strips harakat and Quranic annotation marks from word text (so WhisperX counts tokens correctly)
5. Runs WhisperX Arabic forced alignment
6. Maps aligned word timestamps back to original MP3 coordinates
7. Writes a `.bak` backup then saves the updated JSON

### Known issue — Quranic pause signs in word text

Some words contain embedded pause signs (ۖ ۗ ۘ etc.) inside the `text_uthmani` field,
separated by spaces. The script strips these automatically before alignment. Without this
step, WhisperX would count extra tokens and the last word would be dropped.

### When to use this vs. the API approach

| Situation | Use |
|-----------|-----|
| Quran.com API reciter, stale/shifted segments | API repair (Step 3 above) |
| Tarteel reciter (e.g. Maher), bad word timing | `repair_timestamps.py` |
| Any reciter, one specific verse is noticeably off | `repair_timestamps.py` |
| Bulk repair of 100+ verses | API repair if available; otherwise run in a loop |
