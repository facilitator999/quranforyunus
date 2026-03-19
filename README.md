# Quran for Yunus

A Quran learning app built for my son Yunus — so he can read, listen, and learn word by word.

## What it does

- **Full Quran** — all 604 pages, 114 surahs, in the Uthmanic script
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

| Script | Purpose |
|--------|---------|
| `audio/generate_audio.py` | Clone a reciter's voice and generate letter/vowel MP3s via ElevenLabs |
| `audio/repair_surah_batch.py` | Repair word-level timestamps for an entire surah using WhisperX forced alignment |
| `audio/repair_timestamps.py` | Repair timestamps for a single verse |

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
