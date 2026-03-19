#!/usr/bin/env python3
"""Fetch Alafasy timestamps from Quran.com public API.
   Uses: https://api.quran.com/api/v4/chapter_recitations/{reciter_id}/{ch}?segments=true
   Builds audio/alafasy/timestamps/{ch}.json.
   No auth needed for the public API.

   Usage: py fetch_alafasy_timestamps_qf.py [--chapter N] [--chapters START END] [--force]
          [--reciter-id N]  (default 7 = Alafasy on api.quran.com)"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(line_buffering=True)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TS_DIR = os.path.join(SCRIPT_DIR, "audio", "alafasy", "timestamps")
API_BASE = "https://api.quran.com/api/v4"
DEFAULT_RECITER_ID = 7

VERSE_COUNTS = [
    7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128,
    111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73,
    54, 45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29, 18, 45, 60,
    49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30, 52, 52, 44,
    28, 28, 20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22, 17, 19, 26, 30,
    20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6, 3, 5, 4, 5, 6,
]


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "QuranKids/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def fetch_chapter(reciter_id, ch):
    """Fetch timestamps for one chapter. Returns list of verse dicts or None."""
    url = f"{API_BASE}/chapter_recitations/{reciter_id}/{ch}?segments=true"
    try:
        data = fetch_json(url)
    except Exception as e:
        print(f"  ERROR fetching ch {ch}: {e}", file=sys.stderr)
        return None

    raw = (data.get("audio_file") or data).get("timestamps")
    if not isinstance(raw, list) or not raw:
        return None

    out = []
    for t in raw:
        vk = t.get("verse_key") or f"{ch}:{len(out)+1}"
        from_ms = int(t.get("timestamp_from", 0))
        to_ms = int(t.get("timestamp_to", 0))
        segs = t.get("segments") or []
        clean_segs = []
        for seg in segs:
            if isinstance(seg, (list, tuple)) and len(seg) >= 3:
                clean_segs.append([int(seg[0]), int(seg[1]), int(seg[2])])
        out.append({
            "verse_key": vk,
            "timestamp_from": from_ms,
            "timestamp_to": to_ms,
            "duration": to_ms - from_ms,
            "segments": clean_segs,
        })
    return out if out else None


def fetch_and_save(ch, reciter_id, force=False):
    path = os.path.join(TS_DIR, f"{ch}.json")
    if os.path.exists(path) and not force:
        print(f"  {ch}.json exists, skip")
        return True
    n = VERSE_COUNTS[ch - 1]

    timestamps = fetch_chapter(reciter_id, ch)
    if timestamps and len(timestamps) >= n:
        by_key = {t["verse_key"]: t for t in timestamps}
        ordered = []
        for v in range(1, n + 1):
            vk = f"{ch}:{v}"
            ordered.append(by_key.get(vk, {"verse_key": vk, "timestamp_from": 0, "timestamp_to": 0, "duration": 0, "segments": []}))
        timestamps = ordered
    elif not timestamps:
        print(f"  {ch}.json FAILED (no data from API)")
        return False

    data = {
        "audio_file": {
            "id": 0,
            "chapter_id": ch,
            "audio_url": f"audio/alafasy/recitation/{ch}.mp3",
            "timestamps": timestamps,
        }
    }
    os.makedirs(TS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  {ch}.json ok ({len(timestamps)} verses)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Fetch Alafasy timestamps from Quran.com public API")
    parser.add_argument("--chapter", type=int, metavar="N", help="Chapter 1-114 only")
    parser.add_argument("--chapters", type=int, nargs=2, metavar=("START", "END"), help="Chapters START to END")
    parser.add_argument("--force", action="store_true", help="Overwrite existing JSON")
    parser.add_argument("--reciter-id", type=int, default=DEFAULT_RECITER_ID, metavar="ID",
                        help=f"Reciter ID (default {DEFAULT_RECITER_ID} = Alafasy)")
    args = parser.parse_args()

    reciter_id = args.reciter_id
    print(f"Using api.quran.com public API, reciter_id={reciter_id}")

    if args.chapter is not None:
        chapters = [args.chapter]
    elif args.chapters is not None:
        chapters = list(range(args.chapters[0], args.chapters[1] + 1))
    else:
        chapters = list(range(1, 115))

    print(f"Fetching {len(chapters)} chapters into {TS_DIR} ...")
    ok = 0
    for ch in chapters:
        if fetch_and_save(ch, reciter_id, force=args.force):
            ok += 1
        time.sleep(0.3)
    print(f"Done. {ok}/{len(chapters)} chapters saved.")


if __name__ == "__main__":
    main()
