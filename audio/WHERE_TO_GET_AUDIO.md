# Where to Get the Audio Files

All MP3 files are excluded from this repo. Place them in the correct folders as described below.

---

## 1. Surah Recitation MP3s

**Folder:** `audio/{reciter}/recitation/{surah_number}.mp3`
(e.g. `audio/maher/recitation/2.mp3`)

**Source:** Download from [Tarteel.ai](https://tarteel.ai) or any Quran audio CDN.
See `audio/maher/surah_downloads.txt` and `audio/maher/tarteel_downloads.txt` for the exact download URLs used for Maher Al-Muaiqly.

---

## 2. Letter Pronunciation MP3s (generated via ElevenLabs)

**Folder:** `audio/{reciter}/letters/{letter_name}.mp3`
(e.g. `audio/maher/letters/alif.mp3`)

**How to generate:**

1. Copy `.env.example` to `.env` and add your `ELEVENLABS_API_KEY`
2. Install dependencies:
   ```
   pip install requests python-dotenv
   ```
3. Run the generator:
   ```
   python audio/generate_audio.py --reciter maher
   ```
   - Use `--clone` on first run to create a voice clone from `audio/{reciter}/recitation/1.mp3`
   - Use `--force` to regenerate existing files

Voice IDs for each reciter are stored in `audio/voice_ids.json` (not tracked in git — create it locally or it will be populated automatically when you run `--clone`).
