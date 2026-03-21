#!/usr/bin/env python3
"""
Export [Qudratullah Indopak 13-line layout](https://qul.tarteel.ai/resources/mushaf-layout/236)
to JSON pages for qurankids.

Bundle folder may contain:
  - indopak-13-lines-layout-qudratullah.db  (pages)
  - indopak-nastaleeq.db.zip               → extract → indopak-nastaleeq.db (words: id, surah, ayah, text, location)

Or pass two .db paths. Words DB may use word_index (QUL) or id (indopak-nastaleeq.db).

Usage:
  py -3 scripts/import_indopak13_qudratullah.py path/to/bundle_folder
  py -3 scripts/import_indopak13_qudratullah.py LAYOUT.db WORDS.db
"""
from __future__ import annotations

import json
import sqlite3
import sys
import zipfile
from collections import defaultdict
from pathlib import Path


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0].lower()
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _tables_file(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return _tables(conn)
    finally:
        conn.close()


def _expand_db_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        p = p.resolve()
        if p.is_file() and p.suffix.lower() == ".db":
            out.append(p)
        elif p.is_dir():
            for f in sorted(p.glob("*.db")):
                if f.is_file():
                    out.append(f)
        elif p.is_file():
            out.append(p)
    return list(dict.fromkeys(out))


def _resolve_words_db(layout_path: Path) -> Path | None:
    """Find indopak-nastaleeq words DB next to layout; unzip indopak-nastaleeq.db.zip if needed."""
    parent = layout_path.parent
    for name in ("indopak-nastaleeq.db",):
        cand = parent / name
        if cand.is_file() and "pages" not in _tables_file(cand):
            t = _tables_file(cand)
            if "words" in t:
                return cand
    for sub in ("_nastaleeq_extract",):
        d = parent / sub
        if d.is_dir():
            for f in d.glob("*.db"):
                if "words" in _tables_file(f) and "pages" not in _tables_file(f):
                    return f
    z = parent / "indopak-nastaleeq.db.zip"
    if z.is_file():
        ed = parent / "_nastaleeq_extract"
        ed.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(z, "r") as zf:
            zf.extractall(ed)
        for f in ed.glob("*.db"):
            if "words" in _tables_file(f):
                return f
    return None


def _row_to_word(r: dict) -> tuple[int, dict]:
    if r.get("word_index") is not None:
        wid = int(r["word_index"])
    else:
        wid = int(r["id"])
    surah = int(r["surah"])
    ayah = int(r["ayah"])
    wk = str(r.get("word_key") or "").strip()
    if not wk:
        loc = str(r.get("location") or "")
        parts = loc.split(":")
        if len(parts) >= 2 and parts[0].isdigit():
            wk = f"{parts[0]}:{parts[1]}"
        else:
            wk = f"{surah}:{ayah}"
    return wid, {
        "word_index": wid,
        "word_key": wk,
        "surah": surah,
        "ayah": ayah,
        "text": str(r.get("text") or ""),
    }


def _load_words_from_cursor(cur) -> dict[int, dict]:
    words: dict[int, dict] = {}
    for row in cur:
        r = {k.lower(): v for k, v in zip(row.keys(), row)}
        wid, entry = _row_to_word(r)
        words[wid] = entry
    return words


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    raw = [Path(a) for a in sys.argv[1:] if a.strip()]
    if not raw:
        bundle = root / "indopak-13-lines-layout-qudratullah.db"
        raw = [bundle if bundle.exists() else root / "indopak-13-lines-layout-qudratullah.db"]
    args = _expand_db_paths(raw)
    if not args:
        for p in raw:
            if p.is_dir():
                print(
                    f"No .db file found in folder:\n  {p}\n"
                    "Expected indopak-13-lines-layout-qudratullah.db inside that directory.",
                    file=sys.stderr,
                )
                return 1

    layout_path: Path | None = None
    words_path: Path | None = None

    for p in args:
        if not p.is_file():
            continue
        try:
            t = _tables_file(p)
        except sqlite3.Error:
            continue
        if "pages" in t:
            layout_path = p
        if "words" in t and "pages" not in t:
            words_path = p

    if not layout_path:
        print(
            "No database with a `pages` table found.\n"
            "Pass the layout .db file, or the bundle folder.",
            file=sys.stderr,
        )
        return 1

    if not words_path:
        words_path = _resolve_words_db(layout_path)

    if not words_path:
        print(
            "\nNo words database found. Next to the layout, place either:\n"
            "  indopak-nastaleeq.db\n"
            "  indopak-nastaleeq.db.zip  (will be extracted automatically)\n"
            "Or download from https://qul.tarteel.ai/resources/quran-script/59\n",
            file=sys.stderr,
        )
        return 1

    conn = sqlite3.connect(str(layout_path))
    conn.row_factory = sqlite3.Row

    words: dict[int, dict] = {}

    if words_path.resolve() == layout_path.resolve():
        words = _load_words_from_cursor(conn.execute("SELECT * FROM words"))
        print(f"Using single file (pages + words): {layout_path.name}")
    else:
        ap = str(words_path.resolve()).replace("\\", "/")
        conn.execute("ATTACH DATABASE ? AS wdb", (ap,))
        wtabs = [
            row[0]
            for row in conn.execute("SELECT name FROM wdb.sqlite_master WHERE type='table'")
        ]
        wtab = "words" if "words" in wtabs else None
        if not wtab:
            for t in wtabs:
                if "word" in t.lower():
                    wtab = t
                    break
        if not wtab:
            print(f"No words table in {words_path}", file=sys.stderr)
            conn.close()
            return 1
        words = _load_words_from_cursor(conn.execute(f"SELECT * FROM wdb.{wtab}"))
        print(f"Layout: {layout_path.name} | Words: {words_path.name} ({len(words)} entries)")

    out = root / "data" / "indopak13"
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    def lower_keys(row: sqlite3.Row) -> dict:
        return {k.lower(): v for k, v in zip(row.keys(), row)}

    cur = conn.execute("SELECT * FROM pages ORDER BY page_number ASC, line_number ASC")
    page_rows: dict[int, list] = defaultdict(list)
    for row in cur:
        r = lower_keys(row)
        pn = int(r["page_number"])
        page_rows[pn].append(r)

    max_page = max(page_rows.keys()) if page_rows else 0
    surah_first_page: dict[int, int] = {}

    raw_pages: dict[int, list] = {}
    for pn in sorted(page_rows.keys()):
        lines_out = []
        for r in page_rows[pn]:
            lt = (r.get("line_type") or "").lower()
            centered = bool(r.get("is_centered"))
            sn = r.get("surah_number")

            if lt == "surah_name":
                s = int(sn) if sn is not None else 0
                if s and s not in surah_first_page:
                    surah_first_page[s] = pn
                lines_out.append({"line_type": "surah_name", "is_centered": True, "surah_number": s})
            elif lt == "basmallah":
                lines_out.append({"line_type": "basmallah", "is_centered": centered})
            elif lt == "ayah":
                f = r.get("first_word_id")
                l = r.get("last_word_id")
                if f is None or l is None:
                    lines_out.append({"line_type": "ayah", "is_centered": centered, "words": []})
                    continue
                f, l = int(f), int(l)
                wl = []
                for i in range(f, l + 1):
                    if i in words:
                        wl.append(dict(words[i]))
                lines_out.append({"line_type": "ayah", "is_centered": centered, "words": wl})
            else:
                lines_out.append({"line_type": lt or "unknown", "is_centered": centered, "words": []})

        raw_pages[pn] = lines_out

    verse_pos: dict[tuple[int, int], int] = defaultdict(int)
    for pn in sorted(raw_pages.keys()):
        for line in raw_pages[pn]:
            if line.get("line_type") != "ayah":
                continue
            for w in line["words"]:
                s, a = w["surah"], w["ayah"]
                w["word_in_ayah"] = verse_pos[(s, a)]
                verse_pos[(s, a)] += 1

    for pn in sorted(raw_pages.keys()):
        payload = {
            "layout": "indopak13_qudratullah",
            "page": pn,
            "lines": raw_pages[pn],
        }
        with open(pages_dir / f"{pn}.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    with open(out / "surah_start_pages.json", "w", encoding="utf-8") as f:
        json.dump(
            {str(k): v for k, v in sorted(surah_first_page.items())},
            f,
            ensure_ascii=False,
            indent=0,
        )

    conn.close()
    print(f"Wrote {len(raw_pages)} pages to {pages_dir} (max page {max_page})")
    print(f"Surah start pages -> {out / 'surah_start_pages.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
