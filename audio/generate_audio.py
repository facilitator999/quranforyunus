# -*- coding: utf-8 -*-
"""Generate letter pronunciation MP3s (ElevenLabs TTS) for a reciter.

   For a NEW reciter: put a sample MP3 at audio/{reciter}/recitation/1.mp3,
   then run with --clone to send it to ElevenLabs, create a voice clone, and
   generate letters.

   Examples:
     py generate_audio.py --reciter alafasy --clone --force   # clone from 1.mp3, then generate letters
     py generate_audio.py --reciter sudais --clone --sample audio/sudais/recitation/1.mp3  # custom path
     py generate_audio.py --reciter alafasy --force            # use saved voice_id, generate letters only
"""
import argparse
import io
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API_KEY = os.getenv("ELEVENLABS_API_KEY")
if not API_KEY:
    raise SystemExit("ERROR: ELEVENLABS_API_KEY not set in .env")
# Fallbacks when voice_ids.json has no entry (pre-cloned or library voices)
VOICE_ID_MINSHAWI = "SrQ0MDuMIsT4Rhykyn4D"
VOICE_ID_ALAFASY = "PYEuXpwlrUpRz3dbj9uf"
MODEL_ID = "eleven_multilingual_v2"

AUDIO_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_IDS_PATH = os.path.join(AUDIO_DIR, "voice_ids.json")
ADD_VOICE_URL = "https://api.elevenlabs.io/v1/voices/add"


def get_out_dir(reciter: str) -> str:
    return os.path.join(AUDIO_DIR, reciter, "letters")


def load_voice_ids() -> dict:
    if os.path.exists(VOICE_IDS_PATH):
        try:
            with open(VOICE_IDS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_voice_id(reciter: str, voice_id: str) -> None:
    data = load_voice_ids()
    data[reciter] = voice_id
    with open(VOICE_IDS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Saved voice_id for '{reciter}' to {VOICE_IDS_PATH}")


def get_voice_id(reciter: str) -> str:
    data = load_voice_ids()
    if reciter in data:
        return data[reciter]
    if reciter == "minshawi":
        return VOICE_ID_MINSHAWI
    if reciter == "alafasy":
        return VOICE_ID_ALAFASY
    raise SystemExit(
        f"No voice_id for reciter '{reciter}'. "
        f"Run with --clone and a sample MP3 at audio/{reciter}/recitation/1.mp3 (or use --sample path)."
    )


def clone_voice_from_mp3(reciter: str, sample_path: str) -> str:
    """Send sample MP3 to ElevenLabs, create instant voice clone, return voice_id."""
    if not os.path.exists(sample_path) or os.path.getsize(sample_path) < 1000:
        raise SystemExit(f"Sample file not found or too small: {sample_path}")
    name = reciter.replace("_", " ").replace("-", " ").title()
    with open(sample_path, "rb") as f:
        sample_bytes = f.read()
    files = [("files", (os.path.basename(sample_path), sample_bytes, "audio/mpeg"))]
    data = [
        ("name", (None, name)),
        ("description", (None, f"Cloned from recitation sample for {reciter}")),
    ]
    headers = {"xi-api-key": API_KEY}
    print(f"Cloning voice from {sample_path} ...")
    r = requests.post(ADD_VOICE_URL, headers=headers, files=files + data, timeout=120)
    if r.status_code != 200:
        raise SystemExit(f"ElevenLabs clone failed ({r.status_code}): {r.text[:500]}")
    out = r.json()
    voice_id = out.get("voice_id")
    if not voice_id:
        raise SystemExit(f"ElevenLabs response missing voice_id: {out}")
    print(f"Created voice: {voice_id}")
    return voice_id


ITEMS = [
    ("alif", "\u0623\u064e\u0644\u0650\u0641"),
    ("ba", "\u0628\u064e\u0627\u0621"),
    ("ta", "\u062a\u064e\u0627\u0621"),
    ("tha", "\u062b\u064e\u0627\u0621"),
    ("jeem", "\u062c\u0650\u064a\u0645"),
    ("ha-letter", "\u062d\u064e\u0627\u0621"),
    ("kha", "\u062e\u064e\u0627\u0621"),
    ("dal", "\u062f\u064e\u0627\u0644"),
    ("dhal", "\u0630\u064e\u0627\u0644"),
    ("ra", "\u0631\u064e\u0627\u0621"),
    ("zay", "\u0632\u064e\u0627\u064a"),
    ("seen", "\u0633\u0650\u064a\u0646"),
    ("sheen", "\u0634\u0650\u064a\u0646"),
    ("sad", "\u0635\u064e\u0627\u062f"),
    ("dad", "\u0636\u064e\u0627\u062f"),
    ("taa-letter", "\u0637\u064e\u0627\u0621"),
    ("dhaa", "\u0638\u064e\u0627\u0621"),
    ("ayn", "\u0639\u064e\u064a\u0652\u0646"),
    ("ghayn", "\u063a\u064e\u064a\u0652\u0646"),
    ("fa", "\u0641\u064e\u0627\u0621"),
    ("qaf", "\u0642\u064e\u0627\u0641"),
    ("kaf", "\u0643\u064e\u0627\u0641"),
    ("lam", "\u0644\u064e\u0627\u0645"),
    ("meem", "\u0645\u0650\u064a\u0645"),
    ("noon", "\u0646\u064f\u0648\u0646"),
    ("haa", "\u0647\u064e\u0627\u0621"),
    ("waw", "\u0648\u064e\u0627\u0648"),
    ("ya", "\u064a\u064e\u0627\u0621"),
    ("hamza", "\u0647\u064e\u0645\u0652\u0632\u064e\u0629"),
    ("ta-marbuta", "\u062a\u064e\u0627\u0621 \u0645\u064e\u0631\u0652\u0628\u064f\u0648\u0637\u064e\u0629"),
    ("alif-wasla", "\u0623\u064e\u0644\u0650\u0641 \u0648\u064e\u0635\u0652\u0644"),
    ("lam-alif", "\u0644\u064e\u0627\u0645 \u0623\u064e\u0644\u0650\u0641"),
    ("alif-madd", "\u0623\u064e\u0644\u0650\u0641 \u0645\u064e\u062f\u0651"),
    ("alif-khanjariya", "\u0623\u064e\u0644\u0650\u0641 \u062e\u064e\u0646\u0652\u062c\u064e\u0631\u0650\u064a\u0651\u064e\u0629"),
    ("fatha", "\u0641\u064e\u062a\u0652\u062d\u064e\u0629"),
    ("damma", "\u0636\u064e\u0645\u0651\u064e\u0629"),
    ("kasra", "\u0643\u064e\u0633\u0652\u0631\u064e\u0629"),
    ("sukun", "\u0633\u064f\u0643\u064f\u0648\u0646"),
    ("shadda", "\u0634\u064e\u062f\u0651\u064e\u0629"),
    ("fathatan", "\u0641\u064e\u062a\u0652\u062d\u064e\u062a\u064e\u0627\u0646"),
    ("dammatan", "\u0636\u064e\u0645\u0651\u064e\u062a\u064e\u0627\u0646"),
    ("kasratan", "\u0643\u064e\u0633\u0652\u0631\u064e\u062a\u064e\u0627\u0646"),
    ("shadda-fatha", "\u0634\u064e\u062f\u0651\u064e\u0629 \u0641\u064e\u062a\u0652\u062d\u064e\u0629"),
    ("shadda-damma", "\u0634\u064e\u062f\u0651\u064e\u0629 \u0636\u064e\u0645\u0651\u064e\u0629"),
    ("shadda-kasra", "\u0634\u064e\u062f\u0651\u064e\u0629 \u0643\u064e\u0633\u0652\u0631\u064e\u0629"),
    ("shadda-fathatan", "\u0634\u064e\u062f\u0651\u064e\u0629 \u0641\u064e\u062a\u0652\u062d\u064e\u062a\u064e\u0627\u0646"),
    ("shadda-dammatan", "\u0634\u064e\u062f\u0651\u064e\u0629 \u0636\u064e\u0645\u0651\u064e\u062a\u064e\u0627\u0646"),
    ("shadda-kasratan", "\u0634\u064e\u062f\u0651\u064e\u0629 \u0643\u064e\u0633\u0652\u0631\u064e\u062a\u064e\u0627\u0646"),
]


def main():
    parser = argparse.ArgumentParser(
        description="Generate letter audio (ElevenLabs). Use --clone to create a voice from a reciter's 1.mp3."
    )
    parser.add_argument("--reciter", default="minshawi",
                        help="Reciter name (folder under audio/). Default: minshawi")
    parser.add_argument("--clone", action="store_true",
                        help="Send audio/{reciter}/recitation/1.mp3 to ElevenLabs to clone voice, then generate letters")
    parser.add_argument("--sample", metavar="PATH",
                        help="Path to sample MP3 for cloning (default: audio/{reciter}/recitation/1.mp3)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing letter MP3s")
    args = parser.parse_args()
    reciter = args.reciter.strip().lower().replace(" ", "_")

    # Resolve voice_id: clone first if requested, else load from file or fallback
    if args.clone:
        sample = args.sample
        if not sample:
            sample = os.path.join(AUDIO_DIR, reciter, "recitation", "1.mp3")
        voice_id = clone_voice_from_mp3(reciter, sample)
        save_voice_id(reciter, voice_id)
    else:
        voice_id = get_voice_id(reciter)

    OUT_DIR = get_out_dir(reciter)
    os.makedirs(OUT_DIR, exist_ok=True)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": API_KEY, "Content-Type": "application/json"}

    print(f"Output: {OUT_DIR}")
    print(f"Voice ID: {voice_id}\n")

    total = len(ITEMS)
    for i, (filename, text) in enumerate(ITEMS, 1):
        outpath = os.path.join(OUT_DIR, f"{filename}.mp3")
        if not args.force and os.path.exists(outpath) and os.path.getsize(outpath) > 1000:
            print(f"[{i}/{total}] SKIP (exists): {filename}")
            continue

        body = {
            "text": text,
            "model_id": MODEL_ID,
            "voice_settings": {
                "stability": 0.75,
                "similarity_boost": 0.85,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }
        try:
            r = requests.post(url, headers=headers, json=body, timeout=30)
            if r.status_code == 200:
                with open(outpath, "wb") as f:
                    f.write(r.content)
                print(f"[{i}/{total}] OK: {filename} - {len(r.content)} bytes")
            else:
                print(f"[{i}/{total}] FAIL ({r.status_code}): {filename} - {r.text[:200]}")
        except Exception as e:
            print(f"[{i}/{total}] ERROR: {filename} - {e}")

        time.sleep(0.5)

    print(f"\nDone! Check {OUT_DIR}")


if __name__ == "__main__":
    main()
