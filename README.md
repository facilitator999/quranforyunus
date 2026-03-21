# Quran for Yunus

A Quran learning app built for my son Yunus — so he can read, listen, and learn word by word.

## What it does

- **Full Quran** — all 604 pages, 114 surahs in three scripts:
  - **Uthmanic Hafs** — the standard mushaf font
  - **IndoPak Nastaleeq** — Hanafi style with waqf lazmi markers
  - **Tajweed coloured** — colour-coded by tajweed rules
- **Click any word** to hear it recited in isolation
- **Word-by-word highlighting** as the recitation plays
- **Letter pronunciation** — tap any Arabic letter to hear how it sounds
- **Multiple reciters** — Maher Al-Muaiqly, Al-Minshawi, Al-Afasy
- **Works offline** — installable as a PWA, cached via service worker
- **Mobile friendly** — designed for kids on phones and tablets

## How it works

### Recitation audio
Full surah MP3s are downloaded from [Tarteel.ai](https://tarteel.ai). Word-level timestamps (which tell the app exactly when each word is spoken) come from the Quran Foundation API and are refined using [WhisperX](https://github.com/m-bain/whisperX) forced alignment for precision.

### Letter audio (AI voice cloning)
Each reciter's letter and vowel pronunciation MP3s are generated using [ElevenLabs](https://elevenlabs.io) voice cloning — the reciter's own voice is cloned from their recitation, then used to pronounce each Arabic letter and vowel marker individually.

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/facilitator999/quranforyunus.git
cd quranforyunus
```

### 2. Add credentials
```bash
cp .env.example .env
# Edit .env with your ElevenLabs API key and Quran Foundation credentials
```

### 3. Get the audio files
MP3s are not included in this repo. See [`audio/WHERE_TO_GET_AUDIO.md`](audio/WHERE_TO_GET_AUDIO.md) for:
- Where to download recitation MP3s
- How to generate letter MP3s using the ElevenLabs voice clone script

### 4. Serve locally
```bash
python serve_fast.py
# Open http://localhost:3000
```

## Scripts

### `audio/generate_audio.py` — Generate letter audio via ElevenLabs

Clone a reciter's voice from their recitation and generate MP3s for every Arabic letter and vowel marker.

```bash
# First time — clone voice from recitation/1.mp3, then generate letters
python audio/generate_audio.py --reciter maher --clone

# After cloning — regenerate letters only (uses saved voice ID)
python audio/generate_audio.py --reciter maher

# Force overwrite existing files
python audio/generate_audio.py --reciter maher --force

# Use a custom sample file for cloning
python audio/generate_audio.py --reciter maher --clone --sample path/to/sample.mp3
```

Requires `ELEVENLABS_API_KEY` in `.env`. Voice IDs are saved to `audio/voice_ids.json` after cloning.

---

### `audio/repair_surah_batch.py` — Repair timestamps for a whole surah

Uses WhisperX forced alignment to fix word-level timestamps for every verse in a surah. Loads the Arabic model once and processes all verses sequentially. Automatically detects and fixes duplicate-segment export bugs.

```bash
# Repair all verses in surah 2 for Maher
python audio/repair_surah_batch.py --reciter maher --surah 2

# Resume from verse 100 if interrupted
python audio/repair_surah_batch.py --reciter maher --surah 2 --start-verse 100

# Preview changes without writing anything
python audio/repair_surah_batch.py --reciter maher --surah 2 --dry-run
```

**Repair all 114 surahs — Linux/Mac** (run inside `screen` or `tmux` so it survives disconnect):
```bash
screen -S repair
for i in $(seq 1 114); do python3.11 audio/repair_surah_batch.py --reciter maher --surah $i; done
# Ctrl+A then D to detach — screen -r repair to reattach
```

> On Rocky Linux 8 the system `python` is 3.6 — use `python3.11` (or whichever 3.8+ version is installed). The script will auto-detect and re-exec if you accidentally use the wrong one.

**Repair all 114 surahs — Windows PowerShell:**
```powershell
1..114 | ForEach-Object { python audio/repair_surah_batch.py --reciter maher --surah $_ }
```

Dependencies (`torch`, `whisperx`, `scipy`) are auto-installed on first run. Progress is saved every 10 verses. A `.bak` backup of the original timestamps is created before any changes.

---

### `audio/repair_timestamps.py` — Repair timestamps for a single verse

Fixes word-level timestamps for one specific verse using WhisperX.

```bash
python audio/repair_timestamps.py --reciter maher --verse 2:5
```

## Adding a New Reciter

Full instructions are in [`audio/ADDING_RECITER_AND_REPAIRING.md`](audio/ADDING_RECITER_AND_REPAIRING.md). Summary:

**1. Get timestamps + audio (matched pair)**

| Source | Use when |
|--------|----------|
| [Quran.com API](https://api.quran.com) | Reciter is in the 12 supported (Minshawi, Alafasy, Sudais, etc.) |
| [Tarteel QUL](https://qul.tarteel.ai/resources/recitation) | Any other reciter with segments — filter by "With Segments", use Surah by Surah (Gapless) |

**2. Generate letter audio**
```bash
python audio/generate_audio.py --reciter {name} --clone
```
Clones the reciter's voice from `audio/{name}/recitation/1.mp3` via ElevenLabs and generates 48 letter/vowel MP3s.

**3. Register in `index.html`**

Add one line to `RECITERS` and one `<option>` to the reciter `<select>`.

**4. Push — auto-deploys to server**

**Hard rules:**
- Only surah-level MP3s (`1.mp3`…`114.mp3`) — no per-verse files
- Audio and timestamps must be from the same source or word highlighting will drift
- Always verify MP3 duration matches the last `timestamp_to` in the JSON before pushing

### Reciters currently in the app

| Key | Name | Timestamps source |
|-----|------|------------------|
| `minshawi` | Muhammad Siddiq Al-Minshawi | Quran.com API (ID 9) |
| `alafasy` | Mishary Alafasy | Quran.com API (ID 7) |
| `maher` | Maher Al-Muaiqly | Tarteel QUL |

---

## Deployment

Auto-deploys to the server on every push to `main` via GitHub Actions.

## Built with

- Vanilla HTML/CSS/JS — no framework
- [WhisperX](https://github.com/m-bain/whisperX) — forced audio alignment
- [ElevenLabs](https://elevenlabs.io) — AI voice cloning for letter audio
- [Quran Foundation API](https://quran.foundation) — Quranic text and timestamp data
- Nginx on Rocky Linux 8

---

*Made with love for Yunus.*
